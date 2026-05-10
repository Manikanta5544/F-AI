"""Document classification API — Task #10."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.storage import upload_file
from app.models.db.models import User
from app.models.schemas.schemas import ApiResponse, ClassificationResult, JobOut
from app.repositories.job import JobRepository

router = APIRouter(prefix="/classification", tags=["classification"])

_ALLOWED = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}


@router.post("/submit", response_model=ApiResponse, status_code=202)
async def submit_classification(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Classify a document using both TF-IDF LR (ML) and DistilBERT (DL).
    Results appear side-by-side in the UI for comparison.
    """
    if file.content_type not in _ALLOWED:
        raise HTTPException(status_code=415, detail="Unsupported file type")

    file_bytes = await file.read()
    storage_key, file_hash = await upload_file(file_bytes, file.filename or "document")

    repo = JobRepository(db)
    job = await repo.create(
        user_id=current_user.id,
        job_type="classification",
        meta={"filename": file.filename, "storage_key": storage_key},
    )

    from app.workers.classification_tasks import run_classification

    task = run_classification.apply_async(
        args=[job.id, storage_key, file.filename],
        task_id=f"cls-{job.id}",
    )
    await repo.update_status(job.id, "pending", celery_task_id=task.id)
    await db.refresh(job)
    return ApiResponse(data=JobOut.model_validate(job))


@router.get("/{job_id}", response_model=ApiResponse)
async def get_classification(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = JobRepository(db)
    job = await repo.get_by_id(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Not found")
    if job.status != "success":
        raise HTTPException(status_code=202, detail=job.status)
    return ApiResponse(data=ClassificationResult.model_validate(job.result))