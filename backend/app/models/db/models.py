"""
All ORM models in one module.
Import order: Base → models (Alembic autogenerate requires all models visible).
"""
from __future__ import annotations

import os

from sqlalchemy import (
    Boolean, Float, ForeignKey, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db.base import Base  


# ── Vector Support ────────────────────────────────────────────────────────────
if os.getenv("TESTING", "false").lower() == "true":
    def _vector_col(dims: int):
        return mapped_column(Text, nullable=True)
else:
    from pgvector.sqlalchemy import Vector
    def _vector_col(dims: int):
        return mapped_column(Vector(dims), nullable=True)


# ── User ──────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    jobs: Mapped[list["Job"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ── Job ───────────────────────────────────────────────────────────────────────
class Job(Base):
    __tablename__ = "jobs"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped["User"] = relationship(back_populates="jobs")
    document: Mapped["Document | None"] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )


# ── Document ──────────────────────────────────────────────────────────────────
class Document(Base):
    __tablename__ = "documents"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ocr_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraction_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    classification_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="document")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


# ── Document Chunk ────────────────────────────────────────────────────────────
class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    embedding: Mapped[list[float] | None] = _vector_col(1536)
    chunk_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_idx"),
    )


# ── Scraped Product ───────────────────────────────────────────────────────────
class ScrapedProduct(Base):
    __tablename__ = "scraped_products"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    platform: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    product_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount: Mapped[float | None] = mapped_column(Float, nullable=True)

    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    availability: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(512), nullable=True)

    url: Mapped[str] = mapped_column(Text, nullable=False)

    images: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    extra_meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# ── Chat Session ──────────────────────────────────────────────────────────────
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(512), default="New chat", nullable=False)
    rag_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    document_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    user: Mapped["User"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


# ── Chat Message ──────────────────────────────────────────────────────────────
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    sources: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")