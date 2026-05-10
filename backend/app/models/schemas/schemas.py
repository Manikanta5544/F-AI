"""
All Pydantic v2 schemas — single source of truth for API request/response shapes.
Split into sections by domain. Strict typing throughout.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ── Base Schema ───────────────────────────────────────────────────────────────
class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Envelope ──────────────────────────────────────────────────────────────────
class ApiResponse(BaseModel):
    data: Any
    meta: dict[str, Any] | None = None


# ── Shared primitives ─────────────────────────────────────────────────────────
class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class ExtractedField(BaseModel):
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["regex", "ml", "ocr"]
    engine: str
    bbox: BoundingBox | None = None
    raw_ocr: str = ""


# ── Auth ──────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int = 900


class UserOut(ORMBase):
    id: str
    email: str
    name: str
    role: str
    avatar_url: str | None
    created_at: datetime


# ── Job ───────────────────────────────────────────────────────────────────────
class JobOut(ORMBase):
    id: str
    status: str
    progress: int
    job_type: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None


# ── OCR ───────────────────────────────────────────────────────────────────────
class OCRToken(BaseModel):
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox
    engine: str


class OCRRegion(BaseModel):
    id: str
    type: Literal["text", "table", "figure", "header", "stamp", "signature"]
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0)
    tokens: list[OCRToken] = Field(default_factory=list)
    text: str


class OCRMetrics(BaseModel):
    processing_ms: int
    characters_extracted: int
    avg_confidence: float


class OCRResult(BaseModel):
    job_id: str
    filename: str
    page_count: int
    mode: str
    regions: list[OCRRegion] = Field(default_factory=list)
    engine_used: str
    fallback_triggered: bool = False
    metrics: OCRMetrics


# ── Scraper ───────────────────────────────────────────────────────────────────
class ScrapeSubmitRequest(BaseModel):
    platform: Literal["amazon", "flipkart", "swiggy", "zomato", "manual"]
    urls: list[str] = Field(min_length=1, max_length=50)
    brand_filter: list[str] | None = None

    @field_validator("urls")
    @classmethod
    def strip_and_filter_urls(cls, v: list[str]) -> list[str]:
        cleaned = [u.strip() for u in v if u.strip()]
        if not cleaned:
            raise ValueError("At least one valid URL is required")
        return cleaned


class ScrapedProductOut(ORMBase):
    id: str
    platform: str
    title: str
    price: float | None
    original_price: float | None
    discount: float | None
    currency: str
    rating: float | None
    review_count: int | None
    availability: str
    brand: str | None
    category: str | None
    url: str
    images: list[str]
    extra_meta: dict[str, Any]
    created_at: datetime


class ScrapeResultsOut(BaseModel):
    items: list[ScrapedProductOut]
    total: int
    job_id: str


# ── Extraction — Bank Statement ───────────────────────────────────────────────
class BankTransaction(BaseModel):
    date: ExtractedField
    narration: ExtractedField
    debit: ExtractedField
    credit: ExtractedField
    balance: ExtractedField


class BankStatementResult(BaseModel):
    job_id: str
    account_number: ExtractedField
    ifsc: ExtractedField
    bank_name: ExtractedField
    account_holder: ExtractedField
    opening_balance: ExtractedField
    closing_balance: ExtractedField
    statement_period_from: ExtractedField
    statement_period_to: ExtractedField
    transactions: list[BankTransaction] = Field(default_factory=list)
    is_structured: bool
    template_used: str | None
    human_review_required: bool


# ── Extraction — Invoice ──────────────────────────────────────────────────────
class InvoiceLineItem(BaseModel):
    description: ExtractedField
    quantity: ExtractedField
    unit_price: ExtractedField
    total: ExtractedField


class InvoiceResult(BaseModel):
    job_id: str
    invoice_number: ExtractedField
    invoice_date: ExtractedField
    due_date: ExtractedField
    vendor: ExtractedField
    buyer: ExtractedField
    subtotal: ExtractedField
    tax: ExtractedField
    total: ExtractedField
    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    human_review_required: bool


# ── Classification ────────────────────────────────────────────────────────────
class ClassificationPrediction(BaseModel):
    document_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    model: Literal["tfidf_lr", "distilbert"]


class ClassificationResult(BaseModel):
    job_id: str
    predictions: list[ClassificationPrediction]
    top_prediction: str
    is_multi_label: bool = False


# ── Chatbot / RAG ─────────────────────────────────────────────────────────────
class ChatSource(BaseModel):
    document_id: str
    filename: str
    page_number: int
    chunk_text: str
    similarity: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox | None = None


class ChatMessageOut(ORMBase):
    id: str
    role: str
    content: str
    created_at: datetime
    sources: list[ChatSource] = Field(default_factory=list)
    tokens_used: int | None = None


class ChatSessionOut(ORMBase):
    id: str
    title: str
    rag_enabled: bool
    document_ids: list[str]
    created_at: datetime
    messages: list[ChatMessageOut] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    rag_enabled: bool = True
    document_ids: list[str] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)