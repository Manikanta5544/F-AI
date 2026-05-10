"""
app/services/scraper/lead_store.py — Persistent DB storage for scraped leads.

BUG FIXES
─────────
1. Wrong model (CRASH): Original used `LeadModel` from `app.models.lead` which
   doesn't exist; the correct model is `ScrapedProduct` from
   `app.models.db.models`. Every save silently failed with ImportError.

2. Field name mismatch (CRASH): scraper.py API reads `p.title`, `p.extra_meta`,
   `p.platform` from ScrapedProduct rows. This store now writes those exact
   fields so the API gets real data instead of empty strings:
     - company_name → ScrapedProduct.title
     - source       → ScrapedProduct.platform
     - all contacts → ScrapedProduct.extra_meta (not extra_data)
     - category     → ScrapedProduct.brand

3. Batch logic (prev fix): Moved to a LeadStore class with a cumulative pending
   buffer so flush() always writes everything. No more "last N % 100" truncation.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.scrapers.lead_scraper import Lead


class LeadStore:
    """
    Stateful batch-writer. Call add() as leads arrive, flush() when done.

    Column mapping (ScrapedProduct → Lead):
        title       ← company_name
        brand       ← category
        platform    ← source
        url         ← website
        rating      ← quality_score()
        extra_meta  ← {phone, mobile, email, address, city, description, …}
    """

    FLUSH_EVERY = 150  # auto-flush threshold

    def __init__(self, job_id: str, user_id: str = ""):
        self.job_id   = job_id
        self.user_id  = user_id
        self._pending: list[Lead] = []
        self._total_saved = 0

    def add(self, leads: list[Lead]) -> None:
        self._pending.extend(leads)
        if len(self._pending) >= self.FLUSH_EVERY:
            self._write()

    def flush(self) -> int:
        if self._pending:
            self._write()
        return self._total_saved

    # ─── Internal ──────────────────────────────────────────────────────────────

    def _write(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending[:], []
        try:
            self._insert(batch)
            self._total_saved += len(batch)
            logger.debug(
                f"LeadStore: persisted {len(batch)} rows "
                f"(cumulative={self._total_saved}) job={self.job_id}"
            )
        except Exception as exc:
            logger.error(
                f"LeadStore: insert failed for {len(batch)} leads "
                f"job={self.job_id}: {exc}"
            )
            # Non-fatal — pipeline must continue.

    def _insert(self, leads: list[Lead]) -> None:
        """
        BUG-FIX 1+2: Uses ScrapedProduct (correct model) with correct field names
        that match what scraper.py's _to_lead_out() reads back.

        Field contract (write here ↔ read in scraper.py):
          ScrapedProduct.title      ← lead.company_name
          ScrapedProduct.brand      ← lead.category
          ScrapedProduct.platform   ← lead.source
          ScrapedProduct.url        ← lead.website
          ScrapedProduct.rating     ← lead.quality_score()
          ScrapedProduct.extra_meta ← {phone, mobile, email, address, city, …}
        """
        # BUG-FIX 1: correct model import path
        from app.db.session import get_sync_session
        from app.models.db.models import ScrapedProduct   # ← correct, not LeadModel

        now = datetime.now(timezone.utc)
        rows = [
            ScrapedProduct(
                id=str(uuid.uuid4()),
                job_id=self.job_id,
                # BUG-FIX 2: field names that scraper.py _to_lead_out() actually reads
                title=lead.company_name[:200],        # p.title in API
                brand=lead.category[:100],            # p.brand used as category
                platform=lead.source[:100],           # p.platform in API
                url=lead.website[:500] if lead.website else "",
                rating=min(float(lead.quality_score()), 5.0),  # stored 0-5
                description=lead.description[:500] if lead.description else "",
                # All contact + location data stored in extra_meta (not extra_data)
                # so that p.extra_meta in _to_lead_out() reads correctly
                extra_meta={
                    "phone":          lead.phone,
                    "mobile":         lead.mobile,
                    "email":          lead.email,
                    "address":        lead.address,
                    "city":           lead.city,
                    "description":    lead.description,
                    "website":        lead.website,
                    "source":         lead.source,
                    "source_url":     lead.website,
                    "services":       [],
                    "employee_count": "",
                    "founded_year":   "",
                },
                image_url="",
                price=None,
                created_at=now,
                updated_at=now,
            )
            for lead in leads
        ]

        with get_sync_session() as session:
            session.bulk_save_objects(rows)
            session.commit()


# ── Backwards-compat thin wrapper ─────────────────────────────────────────────

def save_leads_batch(
    leads: list,
    job_id: str = "",
    user_id: str = "",
) -> None:
    """
    One-shot stateless save. Prefer LeadStore for pipeline use.
    Never raises — failure is logged only.
    """
    if not leads:
        return
    store = LeadStore(job_id=job_id or "unknown", user_id=user_id)
    store.add(leads)
    store.flush()