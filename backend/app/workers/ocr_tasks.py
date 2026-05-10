"""OCR Celery tasks — Tasks #4, #6, #7 — queued on 'critical'."""
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
    name="app.workers.ocr_tasks.run_ocr",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    queue="critical",
)
def run_ocr(self, job_id: str, storage_key: str, filename: str, mode: str = "full"):
    """
    Full OCR pipeline:
      Download → YOLO layout detection (#7) → image preprocessing (#6)
      → OCR ensemble Paddle/Easy/Tesseract (#4) → persist → SSE events
    """
    async def _run():
        async with task_db_session() as db:
            repo = JobRepository(db)
            await repo.update_status(job_id, "processing", progress=5)
            await push_progress(job_id, 5)

            try:
                file_bytes = await download_from_storage(storage_key)
            except Exception as exc:
                err = f"Download failed: {exc}"
                logger.error("ocr_download_failed", job_id=job_id, error=str(exc))
                await repo.set_error(job_id, err)
                await push_error(job_id, err)
                return

            await push_progress(job_id, 15)

            from app.services.ocr.pipeline import run_ocr_pipeline

            async def on_progress(pct: int) -> None:
                mapped = 15 + int(pct * 0.80)   # remap 0–100 → 15–95
                await repo.update_status(job_id, "processing", progress=mapped)
                await push_progress(job_id, mapped)

            try:
                result = await run_ocr_pipeline(
                    file_bytes=file_bytes,
                    filename=filename,
                    mode=mode,
                    progress_callback=on_progress,
                )
            except Exception as exc:
                err = f"OCR pipeline failed: {exc}"
                logger.error("ocr_pipeline_failed", job_id=job_id, error=str(exc))
                await repo.set_error(job_id, err)
                await push_error(job_id, err)
                return

            result_dict = result.model_dump()
            await repo.set_result(job_id, result_dict)
            await push_complete(job_id, result_dict)
            logger.info("ocr_complete", job_id=job_id, regions=len(result.regions),
                        engine=result.engine_used, avg_conf=result.metrics.avg_confidence)

    try:
        run_async(_run())
    except Exception as exc:
        logger.error("ocr_task_exception", job_id=job_id, exc=str(exc))
        raise self.retry(exc=exc)

    logger.info("OCR_TASK_STARTED", job_id=job_id)
    logger.info("OCR_TASK_COMPLETED", job_id=job_id)