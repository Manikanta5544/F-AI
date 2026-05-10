"""
Job repository — single place for all DB access on the Job model.
All callers use this instead of writing raw queries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db.models import Job


class JobRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        user_id: str,
        job_type: str,
        meta: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Job:
        job = Job(
            user_id=user_id,
            job_type=job_type,
            status="pending",
            progress=0,
            meta=meta or {},
            idempotency_key=idempotency_key,
        )
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        await self.db.commit()
        return job

    async def get_by_id(self, job_id: str) -> Job | None:
        result = await self.db.execute(select(Job).where(Job.id == job_id))
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> Job | None:
        result = await self.db.execute(
            select(Job).where(Job.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        job_id: str,
        status: str,
        progress: int | None = None,
        celery_task_id: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if progress is not None:
            values["progress"] = progress
        if celery_task_id is not None:
            values["celery_task_id"] = celery_task_id
        await self.db.execute(update(Job).where(Job.id == job_id).values(**values))
        await self.db.flush()
        await self.db.refresh(await self.get_by_id(job_id))
        await self.db.commit()

    async def set_result(self, job_id: str, result: dict[str, Any]) -> None:
        await self.db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="success",
                progress=100,
                result=result,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.db.flush()
        # await self.db.refresh(await self.get_by_id(job_id)))
        # await self.db.commit()

    async def set_error(self, job_id: str, error: str) -> None:
        await self.db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="failed",
                error=error,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.db.flush()

    async def list_by_user(
        self,
        user_id: str,
        job_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Job]:
        q = select(Job).where(Job.user_id == user_id)
        if job_type:
            q = q.where(Job.job_type == job_type)
        q = q.order_by(Job.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def count_by_user(self, user_id: str, job_type: str | None = None) -> int:
        from sqlalchemy import func
        q = select(func.count()).where(Job.user_id == user_id)
        if job_type:
            q = q.where(Job.job_type == job_type)
        return (await self.db.execute(q)).scalar_one()