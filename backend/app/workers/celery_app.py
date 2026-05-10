"""
Celery application factory.

Three priority queues:
  critical — user-facing real-time tasks (OCR, classification)
  default  — scraping, extraction, chatbot indexing
  batch    — future: bulk reprocessing, model training
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "ai_platform",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.ocr_tasks",
        # "app.workers.scraper_tasks",
        "app.workers.lead_scraper_tasks",
        "app.workers.extraction_tasks",
        "app.workers.classification_tasks",
        "app.workers.chatbot_tasks",
    ],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Queue routing
    task_routes={
        "app.workers.ocr_tasks.*":            {"queue": "critical"},
        "app.workers.classification_tasks.*": {"queue": "critical"},
        # "app.workers.scraper_tasks.*":        {"queue": "default"},
        "app.workers.lead_scraper_tasks.*":   {"queue": "default"},
        "app.workers.extraction_tasks.*":     {"queue": "default"},
        "app.workers.chatbot_tasks.*":        {"queue": "default"},
    },

    # Reliability
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    # print("INSIDE CELERY TASK START")

    # Silence the Celery 6.0 deprecation warning
    broker_connection_retry_on_startup=True,

    # Result TTL — 24 hours
    result_expires=86400,

    # Fair dispatch — no task hoarding per worker
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,

    enable_utc=True,
)

# print("FASTAPI DB:", settings.DATABASE_URL)
