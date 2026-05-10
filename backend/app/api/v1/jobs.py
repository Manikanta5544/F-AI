"""
Job status polling + SSE streaming.
GET /api/v1/jobs/{job_id} - returns current job status and metadata.
GET /api/v1/jobs/{job_id}/stream - Server-Sent Events for real-time updates.
"""
from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.db.models import User
from app.models.schemas.schemas import ApiResponse, JobOut
from app.repositories.job import JobRepository

logger = structlog.get_logger()

# ── NO prefix — router.py adds prefix="/jobs" when including this ─────────────
router = APIRouter(tags=["jobs"])


@router.get("/{job_id}", response_model=ApiResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /api/v1/jobs/{job_id}
    Frontend polls this every 2 s until status == 'success' or 'failed'.
    """
    repo = JobRepository(db)
    job = await repo.get_by_id(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return ApiResponse(data=JobOut.model_validate(job))


@router.get("/{job_id}/stream")
async def stream_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /api/v1/jobs/{job_id}/stream
    Server-Sent Events for real-time progress updates.
    """
    repo = JobRepository(db)
    job = await repo.get_by_id(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        try:
            from app.core.redis import get_queue_redis
            redis = await get_queue_redis()
            stream_key = f"job:{job_id}:events"
            last_id = "0"

            # Emit current state immediately
            job_data = JobOut.model_validate(job).model_dump(mode="json")
            yield f"event: job_update\ndata: {json.dumps(job_data)}\n\n"

            for _ in range(600):  # max 10 minutes
                try:
                    messages = await redis.xread(
                        {stream_key: last_id}, count=10, block=1000
                    )
                except Exception as exc:
                    logger.warning("sse_read_failed", job_id=job_id, error=str(exc))
                    await asyncio.sleep(1)
                    continue

                if not messages:
                    continue

                for _, entries in messages:
                    for msg_id, fields in entries:
                        last_id = msg_id
                        event_type = fields.get("event", "update")
                        try:
                            data = json.loads(fields.get("data", "{}"))
                        except json.JSONDecodeError:
                            data = {}
                        yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                        if event_type in ("complete", "error"):
                            return

            yield "event: timeout\ndata: {}\n\n"
        except Exception as exc:
            logger.error("sse_error", job_id=job_id, error=str(exc))
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )