"""
Celery worker utilities.

Includes:
- Async event loop runner for sync tasks
- Async DB session context manager
- MinIO/S3 download helper
- SSE event pushers for progress, completion, and errors
"""
from __future__ import annotations

import asyncio
import io
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionFactory
from app.core.redis import publish_job_event

logger = structlog.get_logger()


# ── Event loop ────────────────────────────────────────────────────────────────
def run_async(coro):
    """
    Execute an async coroutine from a synchronous Celery task.
    Creates a fresh event loop — never reuses across tasks.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()
            asyncio.set_event_loop(None)


# ── Database session ──────────────────────────────────────────────────────────
@asynccontextmanager
async def task_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Per-task async DB session with automatic commit/rollback."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── MinIO / S3 download ───────────────────────────────────────────────────────
async def download_from_storage(storage_key: str) -> bytes:
    """
    Download a file from MinIO/S3 by storage key.

    BUG FIXED: storage_key is saved as "uploads/abc123.pdf" (bucket prefix included).
    When used with Bucket="uploads", boto3 constructs URL /uploads/uploads/abc123.pdf.
    This is wrong. We now strip the bucket-name prefix from storage_key if present.
    """
    import aioboto3
    from aiobotocore.config import AioConfig
    from app.core.config import settings

    endpoint = settings.MINIO_ENDPOINT.strip()
    if not endpoint.startswith(("http://", "https://")):
        prefix = "https://" if settings.MINIO_USE_SSL else "http://"
        endpoint = f"{prefix}{endpoint}"

    bucket = settings.MINIO_BUCKET_UPLOADS

    # Strip bucket-name prefix from storage_key to prevent double-path
    # "uploads/abc123.pdf" -> bucket="uploads", key="abc123.pdf"
    # "abc123.pdf"         -> bucket="uploads", key="abc123.pdf"
    key = storage_key
    bucket_prefix = f"{bucket}/"
    if key.startswith(bucket_prefix):
        key = key[len(bucket_prefix):]

    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=AioConfig(signature_version="s3v4"),
    ) as s3:
        obj = await s3.get_object(Bucket=bucket, Key=key)
        return await obj["Body"].read()


# ── SSE event helpers ─────────────────────────────────────────────────────────
# Never raise — a failed Redis publish must not cancel a completed task.

async def push_progress(job_id: str, pct: int) -> None:
    try:
        await publish_job_event(job_id, "progress", {"progress": pct})
    except Exception as e:
        logger.warning("sse_push_failed", job_event="progress", job_id=job_id, error=str(e))


async def push_complete(job_id: str, result: dict) -> None:
    try:
        await publish_job_event(job_id, "complete", result)
    except Exception as e:
        logger.warning("sse_push_failed", job_event="complete", job_id=job_id, error=str(e))


async def push_error(job_id: str, error: str) -> None:
    try:
        await publish_job_event(job_id, "error", {"message": error})
    except Exception as e:
        logger.warning("sse_push_failed", job_event="error", job_id=job_id, error=str(e))