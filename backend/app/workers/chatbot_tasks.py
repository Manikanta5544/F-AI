"""
Chatbot document indexing task — supports Task #9 (RAG).

Indexes a document into pgvector so it can be retrieved during RAG chat.
Triggered after a document is uploaded to a chat session.
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
    name="app.workers.chatbot_tasks.index_document",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    queue="default",
)
def index_document(self, job_id: str, document_id: str, storage_key: str, filename: str):
    """
    Chunk, embed, and store a document in pgvector for RAG retrieval.

    Pipeline:
      Download → fast OCR → chunk text → embed chunks → store in document_chunks
    """
    async def _run():
        async with task_db_session() as db:
            repo = JobRepository(db)
            await repo.update_status(job_id, "processing", progress=5)
            await push_progress(job_id, 5)

            # Download
            try:
                file_bytes = await download_from_storage(storage_key)
            except Exception as exc:
                err = f"Download failed: {exc}"
                await repo.set_error(job_id, err)
                await push_error(job_id, err)
                return

            await push_progress(job_id, 20)

            # OCR
            try:
                from app.services.ocr.pipeline import run_ocr_pipeline
                ocr_result = await run_ocr_pipeline(file_bytes, filename, mode="fast")
                full_text = " ".join(r.text for r in ocr_result.regions)
            except Exception as exc:
                await repo.set_error(job_id, f"OCR failed: {exc}")
                await push_error(job_id, str(exc))
                return

            await push_progress(job_id, 50)

            # Chunk + embed + store
            try:
                from app.services.chatbot.rag import index_document as rag_index
                chunk_count = await rag_index(db, document_id, full_text, filename)
            except Exception as exc:
                await repo.set_error(job_id, f"Indexing failed: {exc}")
                await push_error(job_id, str(exc))
                return

            await push_progress(job_id, 90)

            # Mark document as indexed
            from sqlalchemy import update
            from app.models.db.models import Document
            await db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(is_indexed=True)
            )

            result = {"chunk_count": chunk_count, "document_id": document_id}
            await repo.set_result(job_id, result)
            await push_complete(job_id, result)
            logger.info("index_complete", document_id=document_id, chunks=chunk_count)

    try:
        run_async(_run())
    except Exception as exc:
        logger.error("index_task_exception", job_id=job_id, exc=str(exc))
        raise self.retry(exc=exc)