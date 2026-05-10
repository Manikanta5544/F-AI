"""
app/api/v1/download.py

Download endpoint — stream any completed job result as an Excel file.
GET /api/v1/download/{job_id}

BUG FIXED:
  BUG 11 — normalize_category() remapped already-correct brand values
    Root: tasks.py stores lead.category (already a valid segment key like
    'ca_firm', 'logistics') in the brand column. download.py was running
    normalize_category() on these correct values, sometimes getting wrong
    results. e.g. 'ca_firm' contains 'ca' → matched correctly, but
    'logistics' contains neither 'logistic' nor 'ca' → fell to 'other'.
    Fix: Use p.brand directly — it's already the correct segment key.
    The normalize_category() function is removed entirely from this file.
"""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.db.models import Job, ScrapedProduct, User
from app.repositories.job import JobRepository
from app.services.export.excel_exporter import generate_excel

router = APIRouter(tags=["download"])

_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/{job_id}")
async def download_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /api/v1/download/{job_id}
    Stream completed job result as Excel (.xlsx).
    Works for: invoice, bank_statement, scraper, ocr, classification.
    """
    repo = JobRepository(db)
    job  = await repo.get_by_id(job_id)

    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "success":
        raise HTTPException(
            status_code=409,
            detail=f"Job not complete (status: {job.status}). Retry when status=success.",
        )

    job_type = job.job_type

    # Scraper: results live in ScrapedProduct table, not job.result
    if "scraper" in job_type or "lead" in job_type:
        rows = (await db.execute(
            select(ScrapedProduct)
            .where(ScrapedProduct.job_id == job_id)
            .order_by(
                ScrapedProduct.rating.desc().nullslast(),
                ScrapedProduct.created_at.asc(),
            )
        )).scalars().all()

        if not rows:
            raise HTTPException(status_code=404, detail="No scraped data found")

        from app.services.export.lead_excel_exporter import export_leads_excel

        leads = []
        for p in rows:
            meta = p.extra_meta or {}
            # BUG FIX: Use p.brand directly — already the correct segment key
            # stored by tasks.py. Do NOT re-normalize; that was causing wrong
            # category assignments.
            svc = meta.get("services", "")
            if isinstance(svc, list):
                svc = ", ".join(svc)
            leads.append({
                "company_name":     p.title or "",
                "category":         p.brand or "other",   # already correct
                "city":             meta.get("city", ""),
                "phone":            meta.get("phone", ""),
                "email":            meta.get("email", ""),
                "website":          meta.get("website", ""),
                "address":          meta.get("address", ""),
                "description":      meta.get("description", ""),
                "services":         svc,
                "source_platform":  p.platform or "",
                "source_url":       meta.get("source_url", "") or p.url or "",
                "confidence_score": p.rating / 5.0 if p.rating else 0.3,
                "founded_year":     meta.get("founded_year", ""),
                "employee_count":   meta.get("employee_count", ""),
            })

        try:
            excel_bytes = export_leads_excel(leads, job_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Excel generation failed: {exc}")

        filename = f"b2b_leads_{job_id[:8]}.xlsx"
        encoded  = urllib.parse.quote(filename)
        return Response(
            content=excel_bytes,
            media_type=_EXCEL_MIME,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"; '
                    f"filename*=UTF-8''{encoded}"
                ),
                "Content-Length": str(len(excel_bytes)),
                "Cache-Control":  "no-store",
            },
        )

    # Non-scraper jobs: use job.result dict
    if not job.result:
        raise HTTPException(status_code=404, detail="No result data for this job")
    result = job.result

    source_filename = str((job.meta or {}).get("filename", "")) if job.meta else ""
    try:
        excel_bytes = generate_excel(result, job_type, source_filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Excel generation failed: {exc}")

    type_label = (
        job_type.replace("extraction_", "").replace("_", " ").strip().replace(" ", "_")
    )
    filename = f"{type_label}_{job_id[:8]}.xlsx"
    encoded  = urllib.parse.quote(filename)
    return Response(
        content=excel_bytes,
        media_type=_EXCEL_MIME,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{encoded}"
            ),
            "Content-Length": str(len(excel_bytes)),
            "Cache-Control":  "no-store",
        },
    )