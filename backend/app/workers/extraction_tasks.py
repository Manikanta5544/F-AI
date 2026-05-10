"""
Extraction Celery tasks — Tasks #5 (bank statement) and #11 (invoice + auto).
"""
from __future__ import annotations

import io
import structlog

from app.workers.celery_app import celery_app
from app.workers.utils import (
    download_from_storage,
    push_complete,
    push_error,
    push_progress,
    run_async,
    task_db_session,
)
from app.repositories.job import JobRepository

logger = structlog.get_logger()

_PDF_TEXT_MIN_CHARS = 80


def _extract_pdf_text(file_bytes: bytes) -> str | None:
    """Fast direct text extraction from digital PDF. Returns None if scanned."""
    try:
        import pdfplumber
        texts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t and t.strip():
                    texts.append(t.strip())
        full = "\n".join(texts)
        if len(full.strip()) >= _PDF_TEXT_MIN_CHARS:
            return full
    except Exception as exc:
        logger.debug("pdf_direct_text_failed", error=str(exc))
    return None


def _is_pdf(filename: str | None, file_bytes: bytes) -> bool:
    if filename and filename.lower().endswith(".pdf"):
        return True
    return file_bytes[:4] == b"%PDF"


async def _get_full_text(file_bytes: bytes, filename: str) -> str:
    """Smart text extraction: fast PDF path, OCR fallback for images/scans."""
    if _is_pdf(filename, file_bytes):
        direct = _extract_pdf_text(file_bytes)
        if direct:
            logger.info("text_extraction_direct", filename=filename, chars=len(direct))
            return direct
        logger.info("pdf_is_scanned_using_ocr", filename=filename)

    from app.services.ocr.pipeline import run_ocr_pipeline
    ocr = await run_ocr_pipeline(file_bytes, filename, mode="fast")
    full_text = "\n".join(r.text for r in ocr.regions if r.text.strip())
    logger.info("text_extraction_ocr", filename=filename, chars=len(full_text), engine=ocr.engine_used)
    return full_text


async def _upload_excel(excel_bytes: bytes, job_id: str, label: str) -> str | None:
    try:
        import aioboto3
        from aiobotocore.config import AioConfig
        from app.core.config import settings

        endpoint = settings.MINIO_ENDPOINT.strip()
        if not endpoint.startswith(("http://", "https://")):
            endpoint = f"http{'s' if settings.MINIO_USE_SSL else ''}://{endpoint}"

        key = f"exports/{job_id}/{label}_export.xlsx"
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=AioConfig(signature_version="s3v4"),
        ) as s3:
            await s3.put_object(
                Bucket=settings.MINIO_BUCKET_PROCESSED, Key=key, Body=excel_bytes,
                ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        return key
    except Exception as exc:
        logger.warning("excel_upload_failed", job_id=job_id, error=str(exc))
        return None


@celery_app.task(name="app.workers.extraction_tasks.run_extraction", bind=True, max_retries=2, default_retry_delay=15, queue="default")
def run_extraction(self, job_id: str, storage_key: str, filename: str, doc_type: str):
    """Full extraction pipeline. Guaranteed to reach set_result or set_error."""
    async def _run():
        async with task_db_session() as db:
            repo = JobRepository(db)
            await repo.update_status(job_id, "processing", progress=5)
            await push_progress(job_id, 5)

            try:
                file_bytes = await download_from_storage(storage_key)
            except Exception as exc:
                err = f"File download failed: {exc}"
                logger.error("extraction_download_failed", job_id=job_id, error=str(exc))
                await repo.set_error(job_id, err); await push_error(job_id, err); return

            await push_progress(job_id, 20)

            try:
                full_text = await _get_full_text(file_bytes, filename or "document")
            except Exception as exc:
                err = f"Text extraction failed: {exc}"
                logger.error("extraction_text_failed", job_id=job_id, error=str(exc))
                await repo.set_error(job_id, err); await push_error(job_id, err); return

            if not full_text.strip():
                err = "No text extracted. File may be blank or corrupted."
                await repo.set_error(job_id, err); await push_error(job_id, err); return

            await push_progress(job_id, 55)

            try:
                if doc_type == "bank_statement":
                    from app.services.extraction.bank_statement import extract_bank_statement
                    # Pass file_bytes so table extraction can be used for structured PDFs
                    result = extract_bank_statement(
                        full_text, job_id,
                        file_bytes=file_bytes if _is_pdf(filename, file_bytes) else None
                    )
                else:
                    from app.services.extraction.invoice import extract_invoice
                    result = extract_invoice(full_text, job_id)
            except Exception as exc:
                err = f"Extraction failed: {exc}"
                logger.error("extraction_service_failed", job_id=job_id, doc_type=doc_type, error=str(exc))
                await repo.set_error(job_id, err); await push_error(job_id, err); return

            await push_progress(job_id, 80)

            excel_key = None
            try:
                from app.services.export.excel_exporter import generate_excel
                excel_bytes = generate_excel(result.model_dump(), f"extraction_{doc_type}", filename or "")
                excel_key = await _upload_excel(excel_bytes, job_id, doc_type)
            except Exception as exc:
                logger.warning("extraction_excel_failed", job_id=job_id, error=str(exc))

            await push_progress(job_id, 95)

            result_dict = result.model_dump()
            result_dict["excel_export_key"] = excel_key
            await repo.set_result(job_id, result_dict)
            await push_complete(job_id, result_dict)
            logger.info(
                "extraction_complete",
                job_id=job_id, doc_type=doc_type, has_excel=excel_key is not None,
                transactions=len(result_dict.get("transactions", [])),
                line_items=len(result_dict.get("line_items", [])),
            )

    try:
        run_async(_run())
    except Exception as exc:
        logger.error("extraction_task_crashed", job_id=job_id, exc=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(name="app.workers.extraction_tasks.run_auto_extract", bind=True, max_retries=2, default_retry_delay=15, queue="default")
def run_auto_extract(self, job_id: str, storage_key: str, filename: str):
    """Auto-classify then extract. Passes file_bytes to bank extractor."""
    async def _run():
        async with task_db_session() as db:
            repo = JobRepository(db)
            await repo.update_status(job_id, "processing", progress=5)
            await push_progress(job_id, 5)

            try:
                file_bytes = await download_from_storage(storage_key)
            except Exception as exc:
                err = f"File download failed: {exc}"
                await repo.set_error(job_id, err); await push_error(job_id, err); return

            await push_progress(job_id, 20)

            try:
                full_text = await _get_full_text(file_bytes, filename or "document")
            except Exception as exc:
                err = f"Text extraction failed: {exc}"
                await repo.set_error(job_id, err); await push_error(job_id, err); return

            if not full_text.strip():
                err = "No text extracted from document."
                await repo.set_error(job_id, err); await push_error(job_id, err); return

            await push_progress(job_id, 40)

            doc_type = "invoice"
            cls_confidence = 0.0
            try:
                from app.services.classification.classifier import classify_document
                cls = classify_document(full_text, job_id)
                doc_type = cls.top_prediction
                cls_confidence = max((p.confidence for p in cls.predictions if p.document_type == doc_type), default=0.0)
                if doc_type not in ("bank_statement", "invoice"):
                    bank_kw = {"ifsc", "account no", "account title", "trans date", "narration", "debit amount", "credit amount", "balance brought", "neft", "rtgs", "upi", "atm", "cheque"}
                    doc_type = "bank_statement" if any(k in full_text.lower() for k in bank_kw) else "invoice"
            except Exception as exc:
                logger.warning("auto_classify_failed", job_id=job_id, error=str(exc))
                # Keyword heuristic as fallback
                bank_kw = {"account no", "account title", "trans date", "narration", "debit amount", "credit amount", "balance brought", "neft", "rtgs", "atm"}
                if any(k in full_text.lower() for k in bank_kw):
                    doc_type = "bank_statement"

            await push_progress(job_id, 55)

            is_pdf = _is_pdf(filename, file_bytes)
            try:
                if doc_type == "bank_statement":
                    from app.services.extraction.bank_statement import extract_bank_statement
                    result = extract_bank_statement(full_text, job_id, file_bytes=file_bytes if is_pdf else None)
                else:
                    from app.services.extraction.invoice import extract_invoice
                    result = extract_invoice(full_text, job_id)
            except Exception as exc:
                err = f"Extraction failed: {exc}"
                await repo.set_error(job_id, err); await push_error(job_id, err); return

            await push_progress(job_id, 80)

            excel_key = None
            try:
                from app.services.export.excel_exporter import generate_excel
                excel_bytes = generate_excel(result.model_dump(), f"extraction_{doc_type}", filename or "")
                excel_key = await _upload_excel(excel_bytes, job_id, doc_type)
            except Exception as exc:
                logger.warning("auto_extract_excel_failed", job_id=job_id, error=str(exc))

            await push_progress(job_id, 95)
            result_dict = result.model_dump()
            result_dict["auto_classified_as"] = doc_type
            result_dict["classification_confidence"] = round(cls_confidence, 4)
            result_dict["excel_export_key"] = excel_key
            await repo.set_result(job_id, result_dict)
            await push_complete(job_id, result_dict)
            logger.info("auto_extract_complete", job_id=job_id, doc_type=doc_type, has_excel=excel_key is not None)

    try:
        run_async(_run())
    except Exception as exc:
        logger.error("auto_extract_crashed", job_id=job_id, exc=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(name="app.workers.extraction_tasks.run_excel_export", bind=True, max_retries=1, queue="default")
def run_excel_export(self, job_id: str, doc_type: str):
    """Re-generate Excel from a completed extraction result."""
    async def _run():
        async with task_db_session() as db:
            repo = JobRepository(db)
            job = await repo.get_by_id(job_id)
            if not job or not job.result:
                logger.error("excel_export_no_result", job_id=job_id); return
            filename = (job.meta or {}).get("filename", "document")
            try:
                from app.services.export.excel_exporter import generate_excel
                excel_bytes = generate_excel(job.result, f"extraction_{doc_type}", filename)
                excel_key = await _upload_excel(excel_bytes, job_id, doc_type)
                if excel_key:
                    await repo.set_result(job_id, {**job.result, "excel_export_key": excel_key})
                    logger.info("excel_reexport_complete", job_id=job_id, key=excel_key)
            except Exception as exc:
                logger.error("excel_reexport_failed", job_id=job_id, error=str(exc))
    try:
        run_async(_run())
    except Exception as exc:
        raise self.retry(exc=exc)