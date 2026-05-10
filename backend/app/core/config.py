from __future__ import annotations

from functools import lru_cache
from typing import Literal
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "AI Platform"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # ── Database ──────────────────────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "localdev"
    POSTGRES_DB: str = "f_ai"

    # Direct URLs (preferred if provided in .env)
    DATABASE_URL: str | None = None
    DATABASE_SYNC_URL: str | None = None

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        if self.DATABASE_SYNC_URL:
            return self.DATABASE_SYNC_URL
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_CACHE_PORT: int = 6380
    REDIS_PASSWORD: str = ""

    REDIS_URL: str | None = None

    @property
    def REDIS_URI(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    @property
    def REDIS_CACHE_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_CACHE_PORT}/1"

    # ── Storage ───────────────────────────────────────────────────────────────
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_UPLOADS: str = "uploads"
    MINIO_BUCKET_PROCESSED: str = "processed"
    MINIO_BUCKET_MODELS: str = "models"
    MINIO_USE_SSL: bool = False
    MINIO_REGION: str = "us-east-1"

    # ── Auth ──────────────────────────────────────────────────────────────────
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_USE_OPENSSL_RAND_HEX_32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── OCR Pipeline ─────────────────────────────────────────────────────────
    ENABLE_YOLO: bool = True
    ENABLE_OCR_ENSEMBLE: bool = True
    YOLO_CONFIDENCE_THRESHOLD: float = 0.55
    OCR_CONFIDENCE_THRESHOLD: float = 0.80
    YOLO_MODEL_PATH: str = "models/yolov8x-doclaynet.pt"

    # ── Scraper ───────────────────────────────────────────────────────────────
    SCRAPER_PROXY_URL: str = ""
    SCRAPER_MIN_DELAY_S: float = 2.0
    SCRAPER_MAX_DELAY_S: float = 6.0
    SCRAPER_MAX_RETRIES: int = 3
    PLAYWRIGHT_HEADLESS: bool = True

    # ── AI / LLM ─────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMS: int = 1536
    RAG_CHUNK_SIZE: int = 512
    RAG_CHUNK_OVERLAP: int = 128
    RAG_TOP_K: int = 5
    DEFAULT_RAG_ENABLED: bool = True

    # ── ML Models ────────────────────────────────────────────────────────────
    CLASSIFICATION_MODEL_PATH: str = "models/classification"
    MLFLOW_TRACKING_URI: str = "http://localhost:5000"

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_WORKER_CONCURRENCY: int = 4

    # ── Validation ────────────────────────────────────────────────────────────
    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_not_default(cls, v: str, info):
        if info.data.get("ENVIRONMENT") == "production" and "CHANGE_ME" in v:
            raise ValueError("SECRET_KEY must be changed in production")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
