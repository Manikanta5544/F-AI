"""
app/workers/lead_scraper_tasks.py — Production-Grade Celery Task

BUG FIXES
─────────
HIGH-1  autoretry_for=(Exception,) caused any failure (including zero leads)
        to retry 3× with exponential backoff → up to 30 wasted minutes per job.
        FIX: removed. Per-request retries happen inside the scraper itself.

HIGH-2  main.py (create_app factory) was concatenated into this file.
        FIX: this file contains ONLY the Celery task.

HIGH-3  MAX_TASK_RUNTIME used time.time() (wall clock) inconsistently.
        FIX: uses time.monotonic() throughout (immune to system clock changes).

HIGH-4  Excel upload failure raised → job marked failed even though
        all leads are in DB and downloadable via /results.
        FIX: upload failure is logged as error but does NOT propagate.
        Job still completes as success.
"""
from __future__ import annotations

import logging
import time
import traceback
from typing import Optional

from celery import shared_task

logger = logging.getLogger(__name__)

PROGRESS_THROTTLE_SECS = 2      # min gap between DB progress writes
MAX_TASK_RUNTIME_SECS  = 900    # 15-minute hard ceiling


@shared_task(
    name="app.workers.lead_scraper_tasks.run_lead_scrape",
    bind=True,
    # HIGH-1 FIX: autoretry_for REMOVED.
    # Retrying on every Exception (including zero-leads errors) wasted up to
    # 30 minutes per job. Per-request retries happen inside run_lead_scrape_sync.
    acks_late=True,
    max_retries=0,
)
def run_lead_scrape(
    self,
    job_id:         str,
    search_queries: Optional[list[str]] = None,
    categories:     Optional[list[str]] = None,
    cities:         Optional[list[str]] = None,
    sources:        Optional[list[str]] = None,
    max_leads:      int = 500,
) -> None:
    """
    Celery entry point for B2B lead scraping.
    job_id must reference an existing row in the jobs table.
    All params are passed through to run_lead_scrape_sync unchanged.
    """
    from datetime import datetime, timezone

    from app.db.session import get_sync_session
    from app.models.job import Job
    from app.utils.storage import upload_file_to_s3
    from app.scrapers.lead_scraper import run_lead_scrape_sync

    start       = time.monotonic()    # HIGH-3 FIX: monotonic clock
    last_db_upd = 0.0

    def _update(session, job: Job, status: str, progress: int) -> None:
        """Throttled progress write — at most once per PROGRESS_THROTTLE_SECS."""
        nonlocal last_db_upd
        now = time.monotonic()
        if now - last_db_upd < PROGRESS_THROTTLE_SECS:
            return
        job.status     = status
        job.progress   = progress
        job.updated_at = datetime.now(timezone.utc)
        session.commit()
        last_db_upd = now

    with get_sync_session() as session:
        job: Optional[Job] = (
            session.query(Job).filter(Job.id == job_id).first()
        )
        if not job:
            logger.error(f"[lead_scraper] Job not found: {job_id}")
            return

        logger.info(
            f"[lead_scraper] START job={job_id} "
            f"cats={categories} cities={cities} "
            f"sources={sources} max_leads={max_leads} "
            f"custom_queries={bool(search_queries)}"
        )

        try:
            _update(session, job, "processing", 5)

            def progress_cb(pct: int) -> None:
                elapsed = time.monotonic() - start   # HIGH-3 FIX
                if elapsed > MAX_TASK_RUNTIME_SECS:
                    raise TimeoutError(
                        f"Lead scraping exceeded {MAX_TASK_RUNTIME_SECS}s "
                        f"(elapsed={elapsed:.0f}s)"
                    )
                # Map pipeline pct (0-100) into DB progress range (5-95)
                db_pct = 5 + int(pct * 0.90)
                _update(session, job, "processing", db_pct)

            # ── Run scraping pipeline ─────────────────────────────────────────
            result = run_lead_scrape_sync(
                job_id=job_id,
                search_queries=search_queries,
                categories=categories,
                cities=cities,
                sources=sources,
                max_leads=max_leads,
                progress_cb=progress_cb,
                user_id=str(job.user_id),
            )

            total      = result.get("total_leads", 0)
            excel_path = result.pop("excel_path", "")

            if total == 0:
                logger.warning(
                    f"[lead_scraper] ZERO leads scraped job={job_id}. "
                    "Check source availability and search parameters."
                )

            # ── Upload Excel ──────────────────────────────────────────────────
            s3_key = f"exports/{job_id}/b2b_leads.xlsx"
            if excel_path:
                try:
                    upload_file_to_s3(local_path=excel_path, s3_key=s3_key)
                    logger.info(f"[lead_scraper] Excel uploaded: {s3_key}")
                except Exception as upload_err:
                    # HIGH-4 FIX: upload failure must NOT fail the job.
                    # Leads are already in DB and retrievable via /results.
                    logger.error(
                        f"[lead_scraper] Excel upload failed (non-fatal): "
                        f"{upload_err}"
                    )

            result["excel_export_key"] = s3_key

            # ── Mark complete ─────────────────────────────────────────────────
            job.status     = "success"
            job.progress   = 100
            job.result     = result
            job.updated_at = datetime.now(timezone.utc)
            session.commit()

            elapsed = time.monotonic() - start
            logger.info(
                f"[lead_scraper] COMPLETE job={job_id} "
                f"total={total} phone={result.get('with_phone', 0)} "
                f"email={result.get('with_email', 0)} "
                f"elapsed={elapsed:.1f}s"
            )

        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(
                f"[lead_scraper] FAILED job={job_id} error={exc}\n{tb}"
            )
            job.status     = "failed"
            job.error      = f"{type(exc).__name__}: {exc}\n\n{tb}"
            job.updated_at = datetime.now(timezone.utc)
            session.commit()
            raise  # surface to Celery for monitoring visibility