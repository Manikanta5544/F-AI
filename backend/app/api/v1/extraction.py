"""
Document extraction API — Tasks #5 (bank statement) and #11 (combined FastAPI app).

Task #11 specifically: one unified endpoint /extract that auto-classifies
the document type and dispatches to the correct extractor.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.storage import upload_file
from app.models.db.models import User
from app.models.schemas.schemas import (
    ApiResponse, BankStatementResult, InvoiceResult, JobOut,
)
from app.repositories.job import JobRepository

router = APIRouter( tags=["extraction"])

_ALLOWED = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}
_MAX_BYTES = 30 * 1024 * 1024   # 30 MB


async def _submit(
    file: UploadFile,
    doc_type: str,
    db: AsyncSession,
    current_user: User,
) -> ApiResponse:
    """Shared upload + job creation logic for both extractors."""
    if file.content_type not in _ALLOWED:
        raise HTTPException(status_code=415, detail="Unsupported file type")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 30MB limit")

    storage_key, file_hash = await upload_file(file_bytes, file.filename or "document")
    repo = JobRepository(db)
    job = await repo.create(
        user_id=current_user.id,
        job_type=f"extraction_{doc_type}",
        meta={"doc_type": doc_type, "filename": file.filename, "storage_key": storage_key},
    )

    from app.workers.extraction_tasks import run_extraction

    task = run_extraction.apply_async(
        args=[job.id, storage_key, file.filename, doc_type],
        task_id=f"extract-{job.id}",
    )
    await repo.update_status(job.id, "pending", celery_task_id=task.id)
    await db.refresh(job)
    return ApiResponse(data=JobOut.model_validate(job))


# ── Task #5: Bank statement ───────────────────────────────────────────────────
@router.post("/bank-statement", response_model=ApiResponse, status_code=202)
async def submit_bank_statement(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _submit(file, "bank_statement", db, current_user)


@router.get("/bank-statement/{job_id}", response_model=ApiResponse)
async def get_bank_statement(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = JobRepository(db)
    job = await repo.get_by_id(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "success":
        raise HTTPException(status_code=202, detail=job.status)
    return ApiResponse(data=BankStatementResult.model_validate(job.result))


# ── Task #11: Invoice (combined FastAPI app) ──────────────────────────────────
@router.post("/invoice", response_model=ApiResponse, status_code=202)
async def submit_invoice(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _submit(file, "invoice", db, current_user)


@router.get("/invoice/{job_id}", response_model=ApiResponse)
async def get_invoice_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = JobRepository(db)

    job = await repo.get_by_id(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if job.status in ("pending", "processing"):
        return ApiResponse(
            data={
                "status": job.status,
                "progress": job.progress,
                "job_id": job.id,
            }
        )

    if job.status == "failed":
        raise HTTPException(status_code=500, detail=job.error or "Processing failed")

    if not job.result:
        raise HTTPException(status_code=404, detail="Result not available yet")

    return ApiResponse(data=job.result)

# ── Task #11: Universal auto-classify + extract ───────────────────────────────
@router.post("/extract", response_model=ApiResponse, status_code=202)
async def submit_universal_extract(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Task #11 — combined endpoint: upload file, dispatch to Celery worker.
    The worker runs fast OCR → ML classify → extract → Excel export.
    """
    if file.content_type not in _ALLOWED:
        raise HTTPException(status_code=415, detail="Unsupported file type")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 30MB limit")

    storage_key, file_hash = await upload_file(file_bytes, file.filename or "document")

    repo = JobRepository(db)
    job = await repo.create(
        user_id=current_user.id,
        job_type="extraction_auto",
        meta={
            "filename": file.filename,
            "storage_key": storage_key,
            "auto_classified": True,
        },
    )

    from app.workers.extraction_tasks import run_auto_extract

    task = run_auto_extract.apply_async(
        args=[job.id, storage_key, file.filename],
        task_id=f"auto-extract-{job.id}",
    )
    await repo.update_status(job.id, "pending", celery_task_id=task.id)
    await db.refresh(job)
    return ApiResponse(data=JobOut.model_validate(job))


@router.get("/extract/{job_id}", response_model=ApiResponse)
async def get_auto_extract(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get result of an auto-extraction job."""
    repo = JobRepository(db)
    job = await repo.get_by_id(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "success":
        raise HTTPException(status_code=202, detail=job.status)
    if not job.result:
        raise HTTPException(status_code=404, detail="No result available")
    return ApiResponse(data=job.result)