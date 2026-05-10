"""
Classification Celery task — Task #10.

Runs two models in sequence:
  1. TF-IDF + Logistic Regression (ML baseline) — fast, explainable
  2. DistilBERT fine-tuned (DL)                 — higher accuracy

Results are stored side-by-side so the UI can compare both predictions.
"""
from __future__ import annotations

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


@celery_app.task(
    name="app.workers.classification_tasks.run_classification",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    queue="critical",
)
def run_classification(self, job_id: str, storage_key: str, filename: str):
    """
    Classify a document using ML (TF-IDF LR) and DL (DistilBERT) models.

    Pipeline:
      Download → fast OCR (text extraction only) → classify → persist
    """
    async def _run():
        async with task_db_session() as db:
            repo = JobRepository(db)
            await repo.update_status(job_id, "processing", progress=5)
            await push_progress(job_id, 5)

            # Step 1: Download
            try:
                file_bytes = await download_from_storage(storage_key)
            except Exception as exc:
                err = f"Download failed: {exc}"
                logger.error("classification_download_failed", job_id=job_id, error=str(exc))
                await repo.set_error(job_id, err)
                await push_error(job_id, err)
                return

            await push_progress(job_id, 20)

            # Step 2: Fast OCR — classification only needs text, not structure
            try:
                from app.services.ocr.pipeline import run_ocr_pipeline
                ocr_result = await run_ocr_pipeline(
                    file_bytes=file_bytes,
                    filename=filename,
                    mode="fast",   # no YOLO, single engine — 4× faster
                )
                full_text = " ".join(r.text for r in ocr_result.regions)
            except Exception as exc:
                err = f"OCR failed: {exc}"
                logger.error("classification_ocr_failed", job_id=job_id, error=str(exc))
                await repo.set_error(job_id, err)
                await push_error(job_id, err)
                return

            await push_progress(job_id, 65)

            # Step 3: Classify (both ML and DL models)
            try:
                from app.services.classification.classifier import classify_document
                result = classify_document(full_text, job_id)
            except Exception as exc:
                err = f"Classification failed: {exc}"
                logger.error("classification_service_failed", job_id=job_id, error=str(exc))
                await repo.set_error(job_id, err)
                await push_error(job_id, err)
                return

            await push_progress(job_id, 90)

            result_dict = result.model_dump()
            await repo.set_result(job_id, result_dict)
            await push_complete(job_id, result_dict)
            logger.info(
                "classification_complete",
                job_id=job_id,
                top_prediction=result.top_prediction,
                predictions={p.document_type: round(p.confidence, 3) for p in result.predictions},
            )

    try:
        run_async(_run())
    except Exception as exc:
        logger.error("classification_task_exception", job_id=job_id, exc=str(exc))
        raise self.retry(exc=exc)