"""app/models/schemas/lead_schemas.py"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Supported categories ──────────────────────────────────────────────────────
LeadCategory = Literal[
    "importer", "exporter", "manufacturer", "trader",
    "freight_forwarder", "customs_broker", "insurer", "bank_trade_finance",
    "ca_firm", "virtual_cfo", "accounting", "logistics", "fintech",
    "startup_sme", "ecommerce", "marketing_sales", "operations",
]

# ── Supported sources ─────────────────────────────────────────────────────────
LeadSource = Literal[
    "justdial", "indiamart", "tradeindia", "sulekha", "yellowpages",
]


class LeadScrapeRequest(BaseModel):
    """Request body for POST /scraper/submit."""

    search_queries: list[str] = Field(
        default_factory=list,
        description=(
            "Free-text search queries (optional). "
            "If empty, category-based defaults are used."
        ),
    )
    categories: list[LeadCategory] = Field(
        default_factory=list,
        description="Business categories to scrape.",
    )
    locations: list[str] = Field(
        default_factory=list,
        description="Target cities e.g. ['Hyderabad', 'Mumbai'].",
    )
    sources: list[LeadSource] = Field(
        default_factory=lambda: ["justdial", "indiamart", "tradeindia"],
        description="Data sources to use.",
    )
    max_leads: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Hard cap on unique leads returned.",
    )

    @field_validator("search_queries")
    @classmethod
    def clean_queries(cls, v: list[str]) -> list[str]:
        return [q.strip() for q in v if q.strip()]

    @field_validator("locations")
    @classmethod
    def clean_locations(cls, v: list[str]) -> list[str]:
        return [loc.strip().title() for loc in v if loc.strip()]

    def normalized_cities(self) -> list[str]:
        return self.locations


class LeadOut(BaseModel):
    """Single lead row returned by the API."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    company_name: str
    category: str
    city: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    address: str = ""
    description: str = ""
    employee_count: str = ""
    founded_year: str = ""
    services: list[str] = Field(default_factory=list)
    source_platform: str = ""
    source_url: str = ""
    # FIX: clamped to [0.0, 1.0] — previous code divided by 5.0
    # but quality_score() max is 8, producing values > 1.0
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: datetime
    extra_meta: dict[str, Any] = Field(default_factory=dict)


class LeadResultsOut(BaseModel):
    """
    Paginated result set returned by the API.

    FIX: Added page, per_page, total_pages which were missing,
    causing the frontend pagination controls to receive undefined.
    """
    items: list[LeadOut]
    total: int
    page: int = 1
    per_page: int = 100
    total_pages: int = 0
    job_id: str
    summary: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Auto-compute total_pages from total and per_page."""
        if self.per_page > 0 and self.total_pages == 0:
            object.__setattr__(
                self, "total_pages",
                math.ceil(self.total / self.per_page) if self.total else 0,
            )


# ── Metadata response items ───────────────────────────────────────────────────

class CategoryItem(BaseModel):
    """One item in the /categories array response."""
    id: str
    label: str
    icon: str = ""


class SourceItem(BaseModel):
    """One item in the /sources array response."""
    id: str
    label: str
    coverage: str = ""
    best_for: str = ""


class CityItem(BaseModel):
    """One item in the /cities array response."""
    id: str           # slug used as form value
    label: str        # display name
    region: str = ""  # optional region grouping