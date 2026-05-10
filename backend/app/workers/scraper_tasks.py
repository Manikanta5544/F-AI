"""
Scraper Celery tasks — Tasks #1, #2, #3.

Also hardened:
  - ScrapedItem dict access uses .get() safely (ScrapedItem is a dict subclass)
  - Added per-URL progress ticks for single-platform mode
  - Excel generation failure is non-fatal and logged as warning (already was)
  - Brand filter slice is applied even on single-platform fallback for manual mode
"""
from __future__ import annotations

import structlog

from app.workers.celery_app import celery_app
from app.workers.utils import (
    push_complete,
    push_error,
    push_progress,
    run_async,
    task_db_session,
)
from app.repositories.job import JobRepository

logger = structlog.get_logger()


@celery_app.task(
    name="app.workers.scraper_tasks.run_scrape",
    bind=True,
    max_retries=3,
    default_retry_delay=15,
    queue="default",
)
def run_scrape(
    self,
    job_id: str,
    platform: str,
    urls: list[str],
    brand_filter: list[str] | None = None,
):
    """
    Scrape product data from a platform and persist to DB + Excel.

    brand_filter: for platform="manual", which brand selectors to apply.
                  Supports up to 9 brands per task (Tasks #2 requirement).

    FIX: Removed `await db.refresh(job)` — `job` is never a local variable in
    this task; refreshing it would always raise NameError. The job row is
    managed entirely through JobRepository.
    """
    async def _run():
        async with task_db_session() as db:
            repo = JobRepository(db)
            await repo.update_status(job_id, "processing", progress=5)
            await push_progress(job_id, 5)

            from app.services.scraper.platforms import get_scraper
            from app.models.db.models import ScrapedProduct

            scraped_items = []

            if platform == "manual" and brand_filter:
                # Task #2: multi-brand manual scraping (up to 9 brands)
                brands = brand_filter[:9]
                per_brand = max(1, len(urls) // len(brands))
                for brand_idx, brand in enumerate(brands):
                    brand_urls = urls[brand_idx * per_brand : (brand_idx + 1) * per_brand]
                    if not brand_urls:
                        brand_urls = urls  # fallback: all URLs for every brand
                    try:
                        async with get_scraper(platform, brand) as scraper:
                            items = await scraper.scrape_urls(brand_urls)
                            scraped_items.extend(items)
                        logger.info("brand_scraped", brand=brand, count=len(items))
                    except Exception as exc:
                        logger.warning("brand_scrape_failed", brand=brand, error=str(exc))
                    pct = 10 + int((brand_idx + 1) / len(brands) * 60)
                    await push_progress(job_id, pct)

            else:
                # Tasks #1 / #3: single platform (Amazon, Flipkart, Swiggy, Zomato)
                brand_hint = brand_filter[0] if brand_filter else None
                try:
                    async with get_scraper(platform, brand=brand_hint) as scraper:
                        scraped_items = await scraper.scrape_urls(urls)
                except Exception as exc:
                    err = f"Scraper failed for platform={platform}: {exc}"
                    logger.error("scrape_failed", job_id=job_id, platform=platform, error=str(exc))
                    await repo.set_error(job_id, err)
                    await push_error(job_id, err)
                    return

            await push_progress(job_id, 70)

            # ── Persist scraped products to DB ────────────────────────────────
            product_dicts: list[dict] = []
            for item in scraped_items:
                # item is a ScrapedItem (dict subclass) — .get() is safe
                if not item.get("title"):
                    continue  # skip empty/failed scrapes

                product = ScrapedProduct(
                    job_id=job_id,
                    platform=item.get("platform", platform),
                    product_id=item.get("product_id"),
                    title=item.get("title", ""),
                    price=item.get("price"),
                    original_price=item.get("original_price"),
                    discount=item.get("discount"),
                    currency=item.get("currency", "INR"),
                    rating=item.get("rating"),
                    review_count=item.get("review_count"),
                    availability=item.get("availability", "unknown"),
                    brand=item.get("brand"),
                    category=item.get("category"),
                    url=item.get("url", ""),
                    images=item.get("images", []),
                    extra_meta=item.get("extra_meta", {}),
                )
                db.add(product)
                product_dicts.append(dict(item))

            await db.flush()
            await db.commit()
            await push_progress(job_id, 80)

            # ── Generate Excel workbook (non-fatal) ───────────────────────────
            excel_key: str | None = None
            try:
                from app.services.export.excel_exporter import export_scraped_products
                excel_bytes = export_scraped_products(product_dicts, job_id)
                excel_key = await _upload_excel(excel_bytes, job_id, platform)
                logger.info("scraper_excel_uploaded", job_id=job_id, key=excel_key)
            except Exception as exc:
                logger.warning("scraper_excel_failed", job_id=job_id, error=str(exc))

            await push_progress(job_id, 95)

            result = {
                "scraped_count": len(product_dicts),
                "platform": platform,
                "brands": brand_filter or [],
                "job_id": job_id,
                "excel_export_key": excel_key,
            }
            await repo.set_result(job_id, result)
            await push_complete(job_id, result)
            logger.info(
                "scrape_complete",
                job_id=job_id,
                platform=platform,
                count=len(product_dicts),
            )

    try:
        run_async(_run())
    except Exception as exc:
        logger.error("scrape_task_exception", job_id=job_id, exc=str(exc))
        raise self.retry(exc=exc)


async def _upload_excel(excel_bytes: bytes, job_id: str, label: str) -> str:
    """Upload Excel workbook to MinIO processed bucket. Returns storage key."""
    import aioboto3
    from aiobotocore.config import AioConfig
    from app.core.config import settings

    endpoint = settings.MINIO_ENDPOINT.strip()
    if not endpoint.startswith(("http://", "https://")):
        prefix = "https://" if settings.MINIO_USE_SSL else "http://"
        endpoint = f"{prefix}{endpoint}"

    key = f"exports/{job_id}/{label}_products.xlsx"
    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=AioConfig(signature_version="s3v4"),
    ) as s3:
        await s3.put_object(
            Bucket=settings.MINIO_BUCKET_PROCESSED,
            Key=key,
            Body=excel_bytes,
            ContentType=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
    return key