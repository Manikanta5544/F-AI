"""
OCR API routes
"""
from __future__ import annotations

import structlog

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.storage import upload_file
from app.models.db.models import Document, Job, User
from app.models.schemas.schemas import ApiResponse, JobOut, OCRResult
from app.repositories.job import JobRepository

logger = structlog.get_logger()

router = APIRouter(tags=["ocr"])

_ALLOWED_TYPES = {
    "application/pdf", "image/png", "image/jpeg",
    "image/jpg", "image/tiff", "image/bmp", "image/webp",
}

_MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
_VALID_MODES = {"fast", "full", "ci"}


def _sanitize_filename(filename: str | None) -> str:
    if not filename:
        return "document"
    # Replace spaces and strip dangerous chars
    return filename.replace(" ", "_").strip()


def _validate_file(file: UploadFile) -> None:
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {file.content_type}. "
                   f"Accepted: PDF, PNG, JPEG, TIFF, BMP, WebP",
        )


# ── Submit OCR ────────────────────────────────────────────────────────────────

@router.post("/submit", response_model=ApiResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_ocr(
    file: UploadFile = File(...),
    mode: str = Form(default="full"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Submit document → create OCR job → async Celery processing.

    Guarantees:
    - Idempotency via SHA-256(file_bytes) + mode key
    - Safe upload to MinIO before DB write
    - Atomic Job + Document creation
    - Returns job_id immediately; client polls /api/v1/jobs/{job_id}

    FIX: Removed the misplaced logger.info("dispatching_ocr_task", job_id=job.id)
    that was placed before `job` was ever assigned, causing UnboundLocalError → 500
    on every OCR upload → manifesting as a CORS error on the frontend.
    """
    # ── 1. Validate file type ─────────────────────────────────────────────────
    _validate_file(file)

    filename = _sanitize_filename(file.filename)

    # ── 2. Read bytes ─────────────────────────────────────────────────────────
    try:
        file_bytes = await file.read()
    except Exception as exc:
        logger.exception("file_read_failed", error=str(exc))
        raise HTTPException(status_code=400, detail="Failed to read uploaded file")

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    if len(file_bytes) > _MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    # Normalise mode — silently fall back to "full" for unknown values
    mode = mode if mode in _VALID_MODES else "full"

    # ── 3. Upload to MinIO ────────────────────────────────────────────────────
    try:
        storage_key, file_hash = await upload_file(file_bytes, filename)
    except Exception as exc:
        logger.exception("upload_failed", filename=filename, error=str(exc))
        raise HTTPException(status_code=500, detail="File upload to storage failed")

    idempotency_key = f"{file_hash}:{mode}"
    repo = JobRepository(db)

    # ── 4. Idempotency check ──────────────────────────────────────────────────
    existing = await repo.get_by_idempotency_key(idempotency_key)
    if existing and existing.user_id == current_user.id:
        logger.info("idempotent_ocr_hit", job_id=existing.id, status=existing.status)
        return ApiResponse(data=JobOut.model_validate(existing))

    # ── 5. Create Job + Document (atomic) ─────────────────────────────────────
    try:
        job = await repo.create(
            user_id=current_user.id,
            job_type="ocr",
            meta={
                "filename": filename,
                "mode": mode,
                "storage_key": storage_key,
                "file_size_bytes": len(file_bytes),
            },
            idempotency_key=idempotency_key,
        )

        document = Document(
            job_id=job.id,
            user_id=current_user.id,
            filename=filename,
            file_hash=file_hash,
            storage_key=storage_key,
            file_size_bytes=len(file_bytes),
            mime_type=file.content_type or "application/octet-stream",
        )

        db.add(document)
        await db.flush()
        await db.refresh(document)
        await db.commit()

    except Exception as exc:
        logger.exception("db_write_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Database error while creating OCR job")

    # ── 6. Dispatch Celery task ───────────────────────────────────────────────
    try:
        from app.workers.ocr_tasks import run_ocr

        task = run_ocr.apply_async(
            args=[job.id, storage_key, filename, mode],
            queue="critical",
            routing_key="critical",
            retry=True,
            retry_policy={
                "max_retries": 3,
                "interval_start": 0,
                "interval_step": 0.2,
                "interval_max": 0.5,
            },
        )

        await repo.update_status(job.id, "pending", celery_task_id=task.id)

    except Exception as exc:
        logger.exception("celery_dispatch_failed", job_id=job.id, error=str(exc))
        # Job is already created — mark it failed so the client gets a clear signal
        await repo.set_error(job.id, f"Failed to queue OCR task: {exc}")
        raise HTTPException(status_code=500, detail="Failed to dispatch OCR task to worker queue")

    logger.info(
        "ocr_job_created",
        job_id=job.id,
        user_id=current_user.id,
        mode=mode,
        filename=filename,
        celery_task_id=task.id,
    )

    return ApiResponse(data=JobOut.model_validate(job))


# ── Get OCR Result ────────────────────────────────────────────────────────────

@router.get("/results/{job_id}", response_model=ApiResponse)
async def get_ocr_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = JobRepository(db)
    job = await repo.get_by_id(job_id)

    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "success":
        return ApiResponse(
            data={"status": job.status, "message": "Processing not complete yet"}
        )

    if not job.result:
        raise HTTPException(status_code=404, detail="No OCR result available")

    return ApiResponse(data=OCRResult.model_validate(job.result))


# ── OCR History ───────────────────────────────────────────────────────────────

@router.get("/history", response_model=ApiResponse)
async def ocr_history(
    page: int = 1,
    per_page: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if page < 1 or per_page < 1 or per_page > 100:
        raise HTTPException(status_code=400, detail="Invalid pagination params")

    offset = (page - 1) * per_page

    q = (
        select(Job)
        .where(Job.user_id == current_user.id, Job.job_type == "ocr")
        .order_by(Job.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )

    jobs = (await db.execute(q)).scalars().all()

    total = (
        await db.execute(
            select(func.count()).where(
                Job.user_id == current_user.id,
                Job.job_type == "ocr",
            )
        )
    ).scalar_one()

    items = [
        {
            "job_id": j.id,
            "filename": (j.meta or {}).get("filename", ""),
            "mode": (j.meta or {}).get("mode", ""),
            "created_at": j.created_at.isoformat(),
            "status": j.status,
            "avg_confidence": (j.result or {}).get("metrics", {}).get("avg_confidence"),
        }
        for j in jobs
    ]

    return ApiResponse(
        data={"items": items, "total": total},
        meta={"page": page, "per_page": per_page},
    )