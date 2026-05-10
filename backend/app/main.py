"""
FastAPI application factory.

Startup:
  - Configure structured logging
  - Ensure MinIO buckets exist
  - Log settings summary

Shutdown:
  - Close Redis connections

All routers registered under /api/v1 prefix.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # ── Startup ───────────────────────────────────────────────────────────────

    configure_logging()
    logger = structlog.get_logger()
    logger.info(
        "startup",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.ENVIRONMENT,
    )

    try:
        from app.core.storage import ensure_buckets_exist
        await ensure_buckets_exist()
        logger.info("storage_ready")
    except Exception as e:
        # Non-fatal: MinIO may not be available in test/CI environments
        logger.warning("storage_init_failed", error=str(e))

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    await close_redis()
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        # Docs only available in debug / dev — never expose in production
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
        openapi_url="/api/openapi.json",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request ID middleware ─────────────────────────────────────────────────
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger = structlog.get_logger()  
        logger.exception("unhandled_error", path=str(request.url.path), exc=str(exc), exc_info=True)
        return ORJSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                    "request_id": request.headers.get("X-Request-ID", ""),
                }
            },
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    from app.api.v1.router import api_router
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # ── Health check (always available, not under /api/v1) ───────────────────
    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok", "version": settings.APP_VERSION, "env": settings.ENVIRONMENT}

    return app



app = create_app()