"""
app/api/v1/scraper.py — B2B Lead Intelligence API

NO prefix on APIRouter — router.py provides prefix="/scraper".

BUG FIXES IN THIS FILE
──────────────────────
CRASH-1 │ /categories returned ApiResponse(data=_CAT_META) — a plain dict.
        │ Frontend does cats.map(...) → TypeError: cats.map is not a function.
        │ FIX: returns [{id, label, icon}, ...] array always.

CRASH-2 │ _to_lead_out read p.extra_meta but lead_store wrote to extra_data.
        │ FIX: reads extra_meta (matching what lead_store now writes).

CRASH-3 │ _to_lead_out read p.title; store wrote p.name → company_name blank.
        │ FIX: reads p.title (store now writes title=lead.company_name).

CRASH-4 │ _to_lead_out read p.platform; store didn't write it → AttributeError.
        │ FIX: reads p.platform with getattr fallback; store now writes it.

CRASH-5 │ confidence_score = p.rating / 5.0 but quality_score() max = 8.
        │ Values > 1.0 → Pydantic Field(le=1.0) validation error on every row.
        │ FIX: clamp → min(p.rating / 8.0, 1.0)

HIGH-1  │ has_phone / has_email filters applied in Python AFTER pagination.
        │ total was unfiltered, items were short-paged → pagination broken.
        │ FIX: SQL WHERE clause before LIMIT/OFFSET.

HIGH-2  │ /status/{job_id} endpoint missing → frontend 404 when polling.
        │ FIX: added.

HIGH-3  │ LeadResultsOut lacked page, per_page, total_pages → frontend undefined.
        │ FIX: all three fields now included in response.

HIGH-4  │ /results had no job ownership check → data leak between users.
        │ FIX: 403 if job.user_id != current_user.id.

MED-1   │ /cities endpoint missing → frontend city dropdown empty/hardcoded.
        │ FIX: added, returns all supported cities.

MED-2   │ Content-Disposition header malformed on /download in some cases.
        │ FIX: strict RFC 5987 encoding.
"""
from __future__ import annotations

import math
import urllib.parse
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, func, and_, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.db.models import ScrapedProduct, Job, User
from app.models.schemas.schemas import ApiResponse, JobOut
from app.repositories.job import JobRepository
from app.models.schemas.lead_schemas import (
    LeadScrapeRequest,
    LeadOut,
    LeadResultsOut,
    CategoryItem,
    SourceItem,
    CityItem,
)

router   = APIRouter(tags=["B2B Lead Intelligence"])
_XL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ══════════════════════════════════════════════════════════════════════════════
# STATIC METADATA — returned as ARRAYS so frontend can call .map()
# ══════════════════════════════════════════════════════════════════════════════

# CRASH-1 FIX: defined as list of dicts, NOT as a plain dict.
# The previous code (my earlier fix) returned ApiResponse(data=_CAT_META) where
# _CAT_META was a dict → frontend did cats.map(...) → TypeError crash.
_CATEGORIES: list[dict] = [
    {"id": "importer",           "label": "Importer",             "icon": "📦"},
    {"id": "exporter",           "label": "Exporter",             "icon": "✈️"},
    {"id": "manufacturer",       "label": "Manufacturer",         "icon": "🏭"},
    {"id": "trader",             "label": "Trader",               "icon": "🤝"},
    {"id": "freight_forwarder",  "label": "Freight Forwarder",    "icon": "🚢"},
    {"id": "customs_broker",     "label": "Customs Broker",       "icon": "🔎"},
    {"id": "insurer",            "label": "Insurer",              "icon": "🛡️"},
    {"id": "bank_trade_finance", "label": "Bank / Trade Finance", "icon": "🏦"},
    {"id": "ca_firm",            "label": "CA Firm",              "icon": "📋"},
    {"id": "virtual_cfo",        "label": "Virtual CFO",          "icon": "💼"},
    {"id": "accounting",         "label": "Accounting",           "icon": "📒"},
    {"id": "logistics",          "label": "Logistics",            "icon": "🚚"},
    {"id": "fintech",            "label": "Fintech",              "icon": "💳"},
    {"id": "startup_sme",        "label": "Startup / SME",        "icon": "🚀"},
    {"id": "ecommerce",          "label": "E-commerce",           "icon": "🛒"},
    {"id": "marketing_sales",    "label": "Marketing & Sales",    "icon": "📣"},
    {"id": "operations",         "label": "Operations / Tech",    "icon": "⚙️"},
]

_SOURCES: list[dict] = [
    {"id": "justdial",    "label": "JustDial",          "coverage": "High",
     "best_for": "All categories, phones, JSON-LD"},
    {"id": "indiamart",   "label": "IndiaMart",         "coverage": "High",
     "best_for": "Importers, exporters, manufacturers"},
    {"id": "tradeindia",  "label": "TradeIndia",        "coverage": "High",
     "best_for": "Freight, customs, trade"},
    {"id": "sulekha",     "label": "Sulekha",           "coverage": "Medium",
     "best_for": "CA, CFO, professional services"},
    {"id": "yellowpages", "label": "YellowPages India", "coverage": "Medium",
     "best_for": "Local business phone listings"},
]

_CITIES: list[dict] = [
    {"id": "Hyderabad",  "label": "Hyderabad",  "region": "South"},
    {"id": "Mumbai",     "label": "Mumbai",     "region": "West"},
    {"id": "Bangalore",  "label": "Bangalore",  "region": "South"},
    {"id": "Delhi",      "label": "Delhi",      "region": "North"},
    {"id": "Chennai",    "label": "Chennai",    "region": "South"},
    {"id": "Pune",       "label": "Pune",       "region": "West"},
    {"id": "Kolkata",    "label": "Kolkata",    "region": "East"},
    {"id": "Ahmedabad",  "label": "Ahmedabad",  "region": "West"},
    {"id": "Surat",      "label": "Surat",      "region": "West"},
    {"id": "Jaipur",     "label": "Jaipur",     "region": "North"},
    {"id": "Lucknow",    "label": "Lucknow",    "region": "North"},
    {"id": "Kochi",      "label": "Kochi",      "region": "South"},
    {"id": "Coimbatore", "label": "Coimbatore", "region": "South"},
    {"id": "Nagpur",     "label": "Nagpur",     "region": "Central"},
    {"id": "Visakhapatnam", "label": "Visakhapatnam", "region": "South"},
]


# ══════════════════════════════════════════════════════════════════════════════
# HELPER: ScrapedProduct → schema
# ══════════════════════════════════════════════════════════════════════════════

def _meta(p: ScrapedProduct) -> dict[str, Any]:
    """
    Safely read extra_meta from ScrapedProduct.

    CRASH-2 FIX: The original used p.extra_meta but some versions stored
    data in extra_data. We check both to be resilient.
    """
    val = getattr(p, "extra_meta", None) or getattr(p, "extra_data", None)
    if isinstance(val, dict):
        return val
    return {}


def _to_lead_out(p: ScrapedProduct) -> LeadOut:
    """
    Map a ScrapedProduct DB row → LeadOut schema.

    CRASH-3 FIX: Use p.title (not p.name) — lead_store now writes title.
    CRASH-4 FIX: Read platform via getattr with fallback so no AttributeError.
    CRASH-5 FIX: Clamp confidence to [0, 1]; quality_score max=8 not 5.
    """
    m = _meta(p)

    # CRASH-3: p.title; fallback to p.name for older rows
    company_name = (
        getattr(p, "title", None)
        or getattr(p, "name", None)
        or m.get("company_name", "")
    )

    # CRASH-4: p.platform; fallback to extra_meta["source"]
    source_platform = (
        getattr(p, "platform", None)
        or m.get("source", "")
        or m.get("source_platform", "")
    )

    # CRASH-5: quality_score max=8 → divide by 8, not 5
    raw_rating = getattr(p, "rating", None) or 0.0
    confidence = round(min(float(raw_rating) / 8.0, 1.0), 3)

    services = m.get("services", [])
    if isinstance(services, str):
        services = [s.strip() for s in services.split(",") if s.strip()]

    return LeadOut(
        id=str(p.id),
        job_id=str(p.job_id),
        company_name=company_name,
        category=getattr(p, "brand", "") or m.get("category", "other"),
        city=m.get("city", ""),
        phone=m.get("phone", "") or m.get("mobile", ""),
        email=m.get("email", ""),
        website=m.get("website", "") or getattr(p, "url", "") or "",
        address=m.get("address", ""),
        description=m.get("description", "") or getattr(p, "description", "") or "",
        employee_count=m.get("employee_count", ""),
        founded_year=m.get("founded_year", ""),
        services=services,
        source_platform=source_platform,
        source_url=m.get("source_url", "") or getattr(p, "url", "") or "",
        confidence_score=confidence,
        created_at=p.created_at,
        extra_meta={
            k: v for k, v in m.items()
            if k not in {
                "phone", "mobile", "email", "website", "address", "city",
                "description", "services", "employee_count", "founded_year",
                "source", "source_url", "source_platform", "company_name",
                "category",
            }
        },
    )


def _to_lead_dict(p: ScrapedProduct) -> dict[str, Any]:
    """Map ScrapedProduct → plain dict for the Excel exporter."""
    m = _meta(p)

    company_name = (
        getattr(p, "title", None)
        or getattr(p, "name", None)
        or m.get("company_name", "")
    )
    source_platform = (
        getattr(p, "platform", None)
        or m.get("source", "")
    )
    raw_rating  = getattr(p, "rating", None) or 0.0
    confidence  = round(min(float(raw_rating) / 8.0, 1.0), 3)

    services = m.get("services", "")
    if isinstance(services, list):
        services = ", ".join(services)

    return {
        "company_name":     company_name,
        "category":         getattr(p, "brand", "") or m.get("category", ""),
        "city":             m.get("city", ""),
        "phone":            m.get("phone", "") or m.get("mobile", ""),
        "email":            m.get("email", ""),
        "website":          m.get("website", "") or getattr(p, "url", "") or "",
        "address":          m.get("address", ""),
        "description":      m.get("description", "") or getattr(p, "description", "") or "",
        "services":         services,
        "source_platform":  source_platform,
        "source_url":       m.get("source_url", "") or getattr(p, "url", "") or "",
        "confidence_score": confidence,
        "founded_year":     m.get("founded_year", ""),
        "employee_count":   m.get("employee_count", ""),
        "created_at":       p.created_at.isoformat() if p.created_at else "",
    }


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/submit", response_model=ApiResponse, status_code=202)
async def submit_lead_scrape(
    body:         LeadScrapeRequest,
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """
    POST /api/v1/scraper/submit — submit B2B lead scraping job.

    BROKER-ERROR FIX:
    The original code let kombu.exceptions.OperationalError propagate when
    RabbitMQ / Redis broker is down, crashing the request with HTTP 500 and
    leaving the job row stuck in "pending" status forever.

    Fix:
      1. Catch all broker-level connection errors after job creation.
      2. Mark the job as "failed" with a human-readable error message.
      3. Return HTTP 503 with a clear action message so the frontend can
         display "Celery broker is not reachable" instead of a crash page.
    """
    repo = JobRepository(db)
    job  = await repo.create(
        user_id=current_user.id,
        job_type="lead_scrape",
        meta={
            "search_queries": body.search_queries,
            "categories":     body.categories,
            "locations":      body.locations,
            "sources":        body.sources,
            "max_leads":      body.max_leads,
        },
    )

    from app.workers.lead_scraper_tasks import run_lead_scrape

    try:
        task = run_lead_scrape.apply_async(
            kwargs={
                "job_id":         job.id,
                "search_queries": body.search_queries,
                "categories":     body.categories,
                "cities":         body.locations,   # normalise: locations → cities
                "sources":        body.sources,
                "max_leads":      body.max_leads,
            },
            task_id=f"lead-{job.id}",
            queue="default",
        )

    except Exception as broker_exc:
        # ── Broker is down (RabbitMQ / Redis not running) ─────────────────────
        # Covers:
        #   kombu.exceptions.OperationalError  (AMQP / RabbitMQ refused)
        #   redis.exceptions.ConnectionError   (Redis refused)
        #   OSError / ConnectionRefusedError   (socket-level)
        import traceback
        err_msg = (
            f"Celery broker unreachable: {type(broker_exc).__name__}: {broker_exc}\n\n"
            "ACTION REQUIRED: Start RabbitMQ (or Redis) before submitting jobs.\n"
            "  Windows: net start RabbitMQ  (or start the RabbitMQ service)\n"
            "  Docker:  docker start rabbitmq\n\n"
            + traceback.format_exc()
        )

        # Mark the already-created job as failed so it doesn't stay in limbo
        await repo.update_status(
            job.id,
            "failed",
            error=err_msg,
        )

        raise HTTPException(
            status_code=503,
            detail={
                "error":   "broker_unavailable",
                "message": (
                    "The task queue broker (RabbitMQ) is not running on "
                    "127.0.0.1:5672. Start RabbitMQ and try again."
                ),
                "job_id":  job.id,
                "hint":    (
                    "Windows: open Services → RabbitMQ → Start, "
                    "or run: net start RabbitMQ"
                ),
            },
        )

    await repo.update_status(job.id, "pending", celery_task_id=task.id)
    await db.refresh(job)
    return ApiResponse(data=JobOut.model_validate(job))


@router.get("/status/{job_id}", response_model=ApiResponse)
async def get_job_status(
    job_id:       str,
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """
    GET /api/v1/scraper/status/{job_id}

    HIGH-2 FIX: This endpoint was completely missing, causing frontend job
    polling to receive 404 and get stuck showing a permanent loading state.

    Returns job status, progress percentage, and result summary once done.
    """
    job_row = (await db.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()

    if not job_row:
        raise HTTPException(status_code=404, detail="Job not found")

    # HIGH-4 FIX: ownership check (same applied below in /results)
    if str(job_row.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    result  = job_row.result or {}
    summary = {
        "job_id":       job_row.id,
        "status":       job_row.status,
        "progress":     job_row.progress or 0,
        "total_leads":  result.get("total_leads", 0),
        "with_phone":   result.get("with_phone", 0),
        "with_email":   result.get("with_email", 0),
        "with_website": result.get("with_website", 0),
        "by_category":  result.get("by_category", {}),
        "by_city":      result.get("by_city", {}),
        "by_source":    result.get("by_source", {}),
        "error":        job_row.error,
        "created_at":   job_row.created_at.isoformat() if job_row.created_at else None,
        "updated_at":   job_row.updated_at.isoformat() if job_row.updated_at else None,
    }
    return ApiResponse(data=summary)


@router.get("/results/{job_id}", response_model=ApiResponse)
async def get_lead_results(
    job_id:    str,
    page:      int            = Query(1,   ge=1),
    per_page:  int            = Query(100, ge=1, le=500),
    category:  Optional[str]  = Query(None),
    city:      Optional[str]  = Query(None),
    has_phone: Optional[bool] = Query(None),
    has_email: Optional[bool] = Query(None),
    db:        AsyncSession   = Depends(get_db),
    current_user: User        = Depends(get_current_user),
):
    """
    GET /api/v1/scraper/results/{job_id}

    HIGH-1 FIX: has_phone / has_email are now filtered in the SQL WHERE clause
    before LIMIT/OFFSET. The original code applied them as Python list
    comprehensions AFTER fetching a page, which:
      • Returned fewer items than per_page even when more existed
      • Gave wrong total (unfiltered) → pagination controls showed wrong page count
      • Made page 2+ completely unreachable for filtered queries

    HIGH-3 FIX: Returns page, per_page, total_pages so frontend pagination works.
    HIGH-4 FIX: Ownership check added.
    """
    job_row = (await db.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()

    if not job_row:
        raise HTTPException(status_code=404, detail="Job not found")

    # HIGH-4 FIX: ownership guard
    if str(job_row.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    summary = job_row.result or {}

    # ── Build SQL WHERE conditions ────────────────────────────────────────────
    # HIGH-1 FIX: ALL filters go into SQL, not post-fetch Python.
    conditions: list = [ScrapedProduct.job_id == job_id]

    if category:
        conditions.append(ScrapedProduct.brand == category)

    if city:
        # Filter on extra_meta JSON field. Cast to string and use LIKE as a
        # DB-agnostic approach that works on both PostgreSQL and SQLite.
        conditions.append(
            cast(ScrapedProduct.extra_meta, String).contains(f'"city": "{city}"')
        )

    if has_phone is True:
        # Non-empty phone in extra_meta
        conditions.append(
            cast(ScrapedProduct.extra_meta, String).regexp_match(r'"phone":\s*"[^"]{7,}"')
        )

    if has_email is True:
        conditions.append(
            cast(ScrapedProduct.extra_meta, String).regexp_match(r'"email":\s*"[^@"]+@[^@"]+\.[^@"]+"')
        )

    where_clause = and_(*conditions)

    # Filtered total count (correct denominator for pagination)
    total_filtered: int = (await db.execute(
        select(func.count()).where(where_clause)
    )).scalar_one()

    # Fetch exactly one page
    offset = (page - 1) * per_page
    rows   = (await db.execute(
        select(ScrapedProduct)
        .where(where_clause)
        .order_by(
            ScrapedProduct.rating.desc().nullslast(),
            ScrapedProduct.created_at.asc(),
        )
        .offset(offset)
        .limit(per_page)
    )).scalars().all()

    items       = [_to_lead_out(p) for p in rows]
    total_pages = math.ceil(total_filtered / per_page) if total_filtered else 0

    # HIGH-3 FIX: include page, per_page, total_pages
    return ApiResponse(
        data=LeadResultsOut(
            items=items,
            total=total_filtered,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            job_id=job_id,
            summary=summary,
        ),
        meta={
            "page":        page,
            "per_page":    per_page,
            "total":       total_filtered,
            "total_pages": total_pages,
        },
    )


@router.get("/download/{job_id}")
async def download_leads_excel(
    job_id:       str,
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """
    GET /api/v1/scraper/download/{job_id}

    Downloads ALL leads as Excel. No row limit.
    Reads from scraped_products table (full rows), NOT job.result (summary only).
    """
    repo = JobRepository(db)
    job  = await repo.get_by_id(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if str(job.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    if job.status != "success":
        raise HTTPException(
            status_code=409,
            detail=f"Job not complete yet (status: {job.status})",
        )

    # Fetch ALL rows — no LIMIT
    products = (await db.execute(
        select(ScrapedProduct)
        .where(ScrapedProduct.job_id == job_id)
        .order_by(
            ScrapedProduct.rating.desc().nullslast(),
            ScrapedProduct.created_at.asc(),
        )
    )).scalars().all()

    if not products:
        raise HTTPException(status_code=404, detail="No leads found for this job")

    rows = [_to_lead_dict(p) for p in products]

    from app.services.export.lead_excel_exporter import export_leads_excel
    try:
        excel_bytes = export_leads_excel(rows, job_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Excel generation failed: {exc}",
        )

    filename = f"b2b_leads_{job_id[:8]}.xlsx"
    encoded  = urllib.parse.quote(filename)
    return Response(
        content=excel_bytes,
        media_type=_XL_MIME,
        headers={
            # MED-2 FIX: RFC 5987 compliant Content-Disposition
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{encoded}"
            ),
            "Content-Length": str(len(excel_bytes)),
            "Cache-Control":  "no-store, no-cache",
            "Pragma":         "no-cache",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# METADATA ENDPOINTS — all return ARRAYS, never plain dicts
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/categories", response_model=ApiResponse)
async def list_categories(
    _: User = Depends(get_current_user),
):
    """
    GET /api/v1/scraper/categories

    CRASH-1 FIX: Returns an ARRAY [{id, label, icon}, ...] so the frontend
    can call cats.map(...) without crashing.

    The previous broken version returned ApiResponse(data=_CAT_META) where
    _CAT_META was a plain dict → TypeError: cats.map is not a function.
    """
    return ApiResponse(data=_CATEGORIES)


@router.get("/sources", response_model=ApiResponse)
async def list_sources(
    _: User = Depends(get_current_user),
):
    """
    GET /api/v1/scraper/sources

    Returns [{id, label, coverage, best_for}, ...] array.
    Same fix applied as /categories — must be an array.
    """
    return ApiResponse(data=_SOURCES)


@router.get("/cities", response_model=ApiResponse)
async def list_cities(
    _: User = Depends(get_current_user),
):
    """
    GET /api/v1/scraper/cities

    MED-1 FIX: This endpoint was missing, causing the frontend city
    multiselect to have no dynamic data source.

    Returns [{id, label, region}, ...] sorted alphabetically.
    """
    sorted_cities = sorted(_CITIES, key=lambda c: c["label"])
    return ApiResponse(data=sorted_cities)


@router.get("/jobs", response_model=ApiResponse)
async def list_user_jobs(
    page:         int        = Query(1,  ge=1),
    per_page:     int        = Query(20, ge=1, le=100),
    status:       Optional[str] = Query(None),
    db:           AsyncSession  = Depends(get_db),
    current_user: User          = Depends(get_current_user),
):
    """
    GET /api/v1/scraper/jobs — list all scraping jobs for the current user.

    Useful for a job history / dashboard view.
    """
    conditions: list = [
        Job.user_id  == current_user.id,
        Job.job_type == "lead_scrape",
    ]
    if status:
        conditions.append(Job.status == status)

    where_clause = and_(*conditions)

    total: int = (await db.execute(
        select(func.count()).where(where_clause)
    )).scalar_one()

    offset = (page - 1) * per_page
    jobs   = (await db.execute(
        select(Job)
        .where(where_clause)
        .order_by(Job.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )).scalars().all()

    items = [
        {
            "job_id":      j.id,
            "status":      j.status,
            "progress":    j.progress or 0,
            "created_at":  j.created_at.isoformat() if j.created_at else None,
            "updated_at":  j.updated_at.isoformat() if j.updated_at else None,
            "total_leads": (j.result or {}).get("total_leads", 0),
            "meta":        j.meta or {},
        }
        for j in jobs
    ]

    return ApiResponse(
        data=items,
        meta={
            "page":        page,
            "per_page":    per_page,
            "total":       total,
            "total_pages": math.ceil(total / per_page) if total else 0,
        },
    )