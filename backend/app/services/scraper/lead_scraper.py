"""
app/scrapers/lead_scraper.py — Production-Grade B2B Lead Scraper

ALL BUG FIXES IN THIS FILE
───────────────────────────
CRASH-1  build_client: proxies= kwarg removed in httpx>=0.23 → TypeError/ConnectionError
         FIX: uses proxy= (correct kwarg). Falls back to direct when None.

CRASH-2  build_client: import certifi inside function body, unused
         FIX: removed. verify=True uses system certs (correct default).

CRASH-3  save_leads_batch used broken LeadModel — ImportError every time,
         all DB saves silently failed (no leads ever persisted to DB)
         FIX: replaced with LeadStore which writes to ScrapedProduct correctly.

HIGH-1   run_lead_scrape_sync missing search_queries, sources, max_leads params
         Celery task passes all three; they were silently dropped.
         FIX: all three added to signature and wired through to pipeline.

HIGH-2   LeadScrapingPipeline ignored sources — all scrapers always ran
         regardless of what the user selected in the frontend.
         FIX: pipeline gates each phase on sources set membership.

HIGH-3   LeadScrapingPipeline ignored max_leads — always scraped unlimited.
         FIX: _saturated() check in _add(); pipeline stops early when limit hit.

HIGH-4   LeadScrapingPipeline ignored search_queries — custom user queries dropped.
         FIX: Bing phase adds one task per custom query per city.

HIGH-5   RuntimeError("CRITICAL: No leads") on empty result triggered Celery
         autoretry 3× — up to 30 min wasted per zero-result job.
         FIX: logs a warning and returns gracefully with total=0.

HIGH-6   SEARCH_CATEGORIES keys did not match LeadCategory schema IDs.
         e.g. schema uses "ca_firm" but scraper had "chartered_accountant";
         schema uses "startup_sme" but scraper had "startup_consulting";
         schema uses "marketing_sales" but scraper had "marketing_agency".
         Mismatched keys caused KeyError crashes when frontend-selected categories
         were passed to the pipeline.
         FIX: SEARCH_CATEGORIES now uses the exact same IDs as LeadCategory
         and covers all 17 categories the API advertises.

HIGH-7   _add() batch-save logic: checked len(added) per-call (always < 100)
         → BATCH_SIZE condition never fired. Final save only wrote last N%100.
         FIX: all persistence delegated to LeadStore (proper cumulative buffer).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

from app.utils.proxy import get_proxy

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# § 1  DATA MODEL
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Lead:
    company_name: str
    category: str
    city: str
    phone:       str = ""
    mobile:      str = ""
    email:       str = ""
    website:     str = ""
    address:     str = ""
    source:      str = ""
    description: str = ""

    @property
    def dedup_key(self) -> str:
        name = re.sub(r"\W+", "", self.company_name.lower())[:40]
        return hashlib.md5(f"{name}:{self.city.lower()}".encode()).hexdigest()

    def has_contact(self) -> bool:
        return bool(self.phone or self.mobile or self.email)

    def quality_score(self) -> int:
        """0–8. Used for DB rating column and confidence calculation."""
        score = 0
        if self.phone or self.mobile: score += 3
        if self.email:                score += 3
        if self.website:              score += 1
        if self.address:              score += 1
        return score


# ══════════════════════════════════════════════════════════════════════════════
# § 2  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Indian phone — three non-overlapping patterns
PHONE_RE = re.compile(
    r"""
    (?:
        (?:\+91|91|0)[\s\-.]?[6-9]\d[\s\-.]?\d{4}[\s\-.]?\d{4}   # A: prefixed mobile
        |
        (?<!\d)[6-9]\d{9}(?!\d)                                     # B: bare 10-digit
        |
        \(?\d{2,4}\)?[\s\-.]\d{3,4}[\s\-.]\d{3,4}                  # C: landline
    )
    """,
    re.VERBOSE,
)

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]{2,}@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,7}"
)
EMAIL_BLACKLIST = re.compile(
    r"@(sentry\.|example\.|test\.|domain\.|email\.|noreply|no-reply"
    r"|yoursite|yourcompany|yourdomain|localhost)",
    re.IGNORECASE,
)
IMAGE_EXT = re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|css|js|woff2?)$", re.I)

USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

BASE_HEADERS: dict[str, str] = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8,hi;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# HIGH-6 FIX: Keys now exactly match LeadCategory schema IDs.
# Previously used "chartered_accountant", "startup_consulting", "marketing_agency"
# which are NOT valid LeadCategory values → KeyError when frontend passed valid IDs.
SEARCH_CATEGORIES: dict[str, dict] = {
    # ── Trade ──────────────────────────────────────────────────────────────
    "importer": {
        "label": "Importer",
        "keywords": [
            "importer trading company India",
            "import agent supplier India",
            "bulk importer India",
        ],
        "indiamart_ss": "importer",
        "sulekha_slug": None,
    },
    "exporter": {
        "label": "Exporter",
        "keywords": [
            "exporter company India",
            "export trading firm",
            "export supplier manufacturer",
        ],
        "indiamart_ss": "exporter",
        "sulekha_slug": None,
    },
    "manufacturer": {
        "label": "Manufacturer",
        "keywords": [
            "manufacturer supplier India",
            "manufacturing company India",
            "OEM manufacturer India",
        ],
        "indiamart_ss": "manufacturer",
        "sulekha_slug": None,
    },
    "trader": {
        "label": "Trader",
        "keywords": [
            "wholesale trader company India",
            "trading company wholesale India",
        ],
        "indiamart_ss": "trader",
        "sulekha_slug": None,
    },
    "freight_forwarder": {
        "label": "Freight Forwarder",
        "keywords": [
            "freight forwarding cargo agents",
            "customs clearance freight forwarder",
            "international cargo shipping agent",
        ],
        "indiamart_ss": "freight forwarding agent",
        "sulekha_slug": "custom-clearance-agents",
    },
    "customs_broker": {
        "label": "Customs Broker",
        "keywords": [
            "customs clearance broker CHA India",
            "customs house agent India",
        ],
        "indiamart_ss": "customs broker",
        "sulekha_slug": None,
    },
    "insurer": {
        "label": "Insurer",
        "keywords": [
            "marine cargo insurance company India",
            "trade insurance broker India",
        ],
        "indiamart_ss": "insurance company",
        "sulekha_slug": None,
    },
    "bank_trade_finance": {
        "label": "Bank / Trade Finance",
        "keywords": [
            "trade finance bank LC India",
            "documentary credit export finance",
        ],
        "indiamart_ss": "trade finance",
        "sulekha_slug": None,
    },
    # ── Finance / Professional ─────────────────────────────────────────────
    "ca_firm": {   # FIX HIGH-6: was "chartered_accountant" → KeyError from frontend
        "label": "CA Firm",
        "keywords": [
            "chartered accountant CA firm GST",
            "CA firm audit tax services",
            "chartered accountant financial services",
        ],
        "indiamart_ss": "chartered accountant",
        "sulekha_slug": "chartered-accountants",
    },
    "virtual_cfo": {
        "label": "Virtual CFO",
        "keywords": [
            "virtual CFO finance consulting services",
            "CFO services financial advisory",
            "outsourced CFO financial management",
        ],
        "indiamart_ss": "CFO services",
        "sulekha_slug": "ca-services",
    },
    "accounting": {
        "label": "Accounting",
        "keywords": [
            "accounting bookkeeping tax consultants",
            "GST filing bookkeeping services",
            "tax consultant accounting firm",
        ],
        "indiamart_ss": "accounting services",
        "sulekha_slug": "accounting-services",
    },
    # ── Logistics / Ops ────────────────────────────────────────────────────
    "logistics": {
        "label": "Logistics",
        "keywords": [
            "logistics company transport India",
            "courier freight transport company",
            "supply chain logistics services",
        ],
        "indiamart_ss": "logistics company",
        "sulekha_slug": "packers-movers",
    },
    # ── Tech / Digital ─────────────────────────────────────────────────────
    "fintech": {
        "label": "Fintech",
        "keywords": [
            "fintech startup company India",
            "financial technology firm India",
        ],
        "indiamart_ss": "fintech",
        "sulekha_slug": None,
    },
    "ecommerce": {
        "label": "E-commerce",
        "keywords": [
            "ecommerce company India online retail",
            "online marketplace seller India",
        ],
        "indiamart_ss": "ecommerce",
        "sulekha_slug": None,
    },
    "marketing_sales": {  # FIX HIGH-6: was "marketing_agency"
        "label": "Marketing & Sales",
        "keywords": [
            "digital marketing agency advertising",
            "SEO social media marketing agency",
            "branding advertising digital agency",
        ],
        "indiamart_ss": "digital marketing agency",
        "sulekha_slug": "digital-marketing",
    },
    "operations": {
        "label": "Operations / Tech",
        "keywords": [
            "IT services technology company India",
            "software development company India",
        ],
        "indiamart_ss": "IT services",
        "sulekha_slug": None,
    },
    "startup_sme": {  # FIX HIGH-6: was "startup_consulting"
        "label": "Startup / SME",
        "keywords": [
            "startup SME small business consulting",
            "business advisory management consulting",
            "SME growth consulting services",
        ],
        "indiamart_ss": "business consultant",
        "sulekha_slug": "management-consulting",
    },
}

# Default city list — matches /cities endpoint
TARGET_CITIES: list[str] = [
    "Hyderabad", "Mumbai", "Bangalore", "Delhi", "Chennai",
]

# All source IDs — matches /sources endpoint
ALL_SOURCES: frozenset[str] = frozenset([
    "indiamart", "bing", "sulekha", "justdial",
])


# ══════════════════════════════════════════════════════════════════════════════
# § 3  HTTP UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _random_headers(referer: str = "") -> dict[str, str]:
    h = {**BASE_HEADERS, "User-Agent": random.choice(USER_AGENTS)}
    if referer:
        h["Referer"] = referer
    return h


def build_client(timeout: int = 25) -> httpx.AsyncClient:
    """
    CRASH-1 FIX: proxies= was removed from httpx ≥ 0.23 → TypeError.
                 Now uses proxy= (the correct kwarg since 0.23).
    CRASH-2 FIX: removed `import certifi` inside function body.
                 verify=True (default) uses system CA bundle.
    """
    proxy = get_proxy()  # None when SCRAPER_PROXIES env var is unset

    kwargs: dict = {
        "headers":          _random_headers(),
        "timeout":          timeout,
        "follow_redirects": True,
        "verify":           True,
        "limits": httpx.Limits(
            max_connections=30,
            max_keepalive_connections=15,
        ),
    }
    if proxy:
        # CRASH-1 FIX: use proxy= not proxies=
        kwargs["proxy"] = proxy

    return httpx.AsyncClient(**kwargs)


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    retries: int = 3,
    base_delay: float = 1.5,
    referer: str = "",
) -> Optional[str]:
    """GET with exponential-backoff retry and jitter. Returns HTML or None."""
    for attempt in range(retries):
        try:
            jitter = random.uniform(0.4, 1.2)
            await asyncio.sleep(base_delay * (1.2 ** attempt) + jitter)

            resp = await client.get(url, headers=_random_headers(referer))

            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 429:
                wait = 15 + attempt * 10
                logger.warning(
                    f"Rate-limited by {urlparse(url).netloc}. Waiting {wait}s"
                )
                await asyncio.sleep(wait)
                continue
            if resp.status_code in (403, 406):
                logger.debug(
                    f"Blocked ({resp.status_code}) {urlparse(url).netloc} "
                    f"attempt {attempt + 1}"
                )
                await asyncio.sleep(4 + attempt * 2)
                continue
            if resp.status_code in (404, 410):
                return None   # permanent — no retry
        except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            logger.debug(f"Timeout {url} attempt {attempt + 1}: {e}")
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.warning(f"Request error {url} attempt {attempt + 1}: {e}")
            await asyncio.sleep(2 ** attempt)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# § 4  EXTRACTION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def extract_phones(text: str) -> list[str]:
    """
    Two-pass Indian phone extractor — mobiles sorted before landlines.
    Pass 1: prefix-anchored (catches spaced formats like +91 98765 43210).
    Pass 2: PHONE_RE for bare/landline numbers.
    """
    seen: dict[str, int] = {}   # digits → priority (0=mobile, 1=landline)

    def _add(digits: str, priority: int) -> None:
        if digits not in seen or priority < seen[digits]:
            seen[digits] = priority

    # Pass 1 — handle spaced formats
    for m in re.finditer(r"(?:\+91|91|0)[\s\-.]*([6-9][\d\s\-.]{9,15})", text):
        d = re.sub(r"\D", "", m.group(1))[:10]
        if len(d) == 10 and d[0] in "6789":
            _add(d, 0)

    # Pass 2
    for raw in PHONE_RE.findall(text):
        d = re.sub(r"\D", "", raw)
        if len(d) == 12 and d.startswith("91"):   d = d[2:]
        elif len(d) == 11 and d.startswith("0"):  d = d[1:]
        elif len(d) == 13 and d.startswith("091"): d = d[3:]

        if len(d) == 10 and d[0] in "6789":
            _add(d, 0)
        elif 8 <= len(d) <= 10:
            _add(d, 1)

    return sorted(seen.keys(), key=lambda d: seen[d])


def extract_emails(text: str) -> list[str]:
    clean: list[str] = []
    seen:  set[str]  = set()
    for e in EMAIL_RE.findall(text):
        e = e.lower().rstrip(".")
        if e in seen or IMAGE_EXT.search(e) or EMAIL_BLACKLIST.search(e):
            continue
        seen.add(e)
        clean.append(e)
    return clean


def extract_jsonld_contacts(html: str) -> tuple[list[str], list[str]]:
    """Extract phones and emails from JSON-LD blocks — highest accuracy."""
    phones: list[str] = []
    emails: list[str] = []
    for script in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(script)
            for obj in ([data] if isinstance(data, dict) else (data if isinstance(data, list) else [])):
                if not isinstance(obj, dict):
                    continue
                for key in ("telephone", "phone"):
                    v = obj.get(key)
                    if isinstance(v, str):
                        phones.extend(extract_phones(v))
                    elif isinstance(v, dict):
                        phones.extend(extract_phones(str(v.get("telephone", ""))))
                v = obj.get("email", "")
                if v:
                    emails.extend(extract_emails(v))
        except Exception:
            pass
    return phones, emails


def clean_name(raw: str) -> str:
    raw = re.sub(r"\s*[-–|]\s*.*$", "", raw)
    raw = re.sub(r"\s+(in|at|located in)\s+\w[\w\s]{0,30}$", "", raw, flags=re.I)
    return " ".join(raw.split()).strip()[:120]


def soup_text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def first_el(soup, selectors: list[str]):
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el
    return None


# ══════════════════════════════════════════════════════════════════════════════
# § 5  SOURCE SCRAPERS  (original working code — not modified)
# ══════════════════════════════════════════════════════════════════════════════

class IndiaMARTScraper:
    """
    Uses dir.indiamart.com/search.mp (confirmed 200 responses).
    www.indiamart.com/{slug}/city-suppliers.html always 404s — never use it.
    """
    BASE = "https://dir.indiamart.com/search.mp"
    NAME_SEL  = [".dspname", ".company-name", "h3.elname", "h3 a", "h2 a",
                 ".sup-name", "[class*='compname']", "[class*='supplier-name']",
                 "strong.bname"]
    PHONE_SEL = [".phn", "[class*='phone']", "[class*='contact']",
                 "a[href^='tel:']"]
    ADDR_SEL  = [".addrs", ".loc", "[class*='address']",
                 "[class*='location']", ".city"]

    def __init__(self, sem: asyncio.Semaphore):
        self.sem = sem

    async def search(
        self, client: httpx.AsyncClient,
        keyword: str, city: str, category: str,
    ) -> list[Lead]:
        url = (
            f"{self.BASE}?ss={quote_plus(keyword)}"
            f"&City={quote_plus(city)}&catids=&bcat="
        )
        async with self.sem:
            html = await safe_get(
                client, url, referer="https://www.indiamart.com/"
            )
        if not html:
            return []
        leads = self._parse_dom(html, category, city)
        if not leads:
            leads = self._regex_fallback(html, category, city)
        logger.info(
            f"IndiaMARTScraper [{city}/{category}]: {len(leads)} leads"
        )
        return leads

    def _parse_dom(self, html: str, category: str, city: str) -> list[Lead]:
        soup  = BeautifulSoup(html, "html.parser")
        leads: list[Lead] = []
        cards = (
            soup.select("div.bx")
            or soup.select("div.lst-bx")
            or soup.select("div.card")
            or soup.select("li.bx")
            or soup.select("[class*='supplier']")
            or soup.select("[class*='company']")
            or soup.select("article")
        )
        for card in cards:
            name_el = first_el(card, self.NAME_SEL)
            if not name_el:
                continue
            name = clean_name(soup_text(name_el))
            if not name or len(name) < 3:
                continue

            phone = ""
            phone_el = first_el(card, self.PHONE_SEL)
            if phone_el:
                tel = phone_el.get("href", "")
                if tel.startswith("tel:"):
                    phone = re.sub(r"\D", "", tel[4:])
                else:
                    ps = extract_phones(soup_text(phone_el))
                    phone = ps[0] if ps else ""
            if not phone:
                ps = extract_phones(card.get_text(" ", strip=True))
                phone = ps[0] if ps else ""

            text   = card.get_text(" ", strip=True)
            jld_phones, jld_emails = extract_jsonld_contacts(str(card))
            emails = jld_emails or extract_emails(text)
            for tag in card.find_all(attrs={"data-email": True}):
                emails.insert(0, tag["data-email"])

            addr_el = first_el(card, self.ADDR_SEL)
            website = ""
            for a in card.find_all("a", href=True):
                href = a["href"]
                if (href.startswith("http")
                        and "indiamart" not in href
                        and not IMAGE_EXT.search(href)):
                    website = href
                    break

            leads.append(Lead(
                company_name=name, category=category, city=city,
                phone=phone[:15],
                email=emails[0] if emails else "",
                website=website,
                address=soup_text(addr_el)[:200] if addr_el else "",
                source="indiamart",
            ))
        return leads

    def _regex_fallback(self, html: str, category: str, city: str) -> list[Lead]:
        soup  = BeautifulSoup(html, "html.parser")
        leads: list[Lead] = []
        used:  set[str]   = set()
        for h in soup.find_all(["h2", "h3", "h4", "strong"], limit=80):
            name = clean_name(h.get_text(strip=True))
            if not 4 <= len(name) <= 120:
                continue
            parts = [name]
            p = h.parent
            if p:
                parts.append(p.get_text(" ", strip=True))
                if p.parent:
                    parts.append(p.parent.get_text(" ", strip=True))
            ctx    = " ".join(parts)
            phones = [p for p in extract_phones(ctx) if p not in used]
            emails = extract_emails(ctx)
            if phones:
                used.add(phones[0])
            leads.append(Lead(
                company_name=name, category=category, city=city,
                phone=phones[0] if phones else "",
                email=emails[0] if emails else "",
                source="indiamart_regex",
            ))
        seen:   set[str]   = set()
        unique: list[Lead] = []
        for l in leads:
            k = re.sub(r"\W", "", l.company_name.lower())
            if k not in seen:
                seen.add(k)
                unique.append(l)
        return unique


class BingSerpScraper:
    """
    SERP scraper — 5-level fallback chain.
    Bot-detection guard: page < 5 KB or missing b_results → skip.
    """
    BASE = "https://www.bing.com/search"
    SKIP = frozenset([
        "bing.com", "microsoft.com", "msn.com", "live.com",
        "youtube.com", "facebook.com", "wikipedia.org",
        "twitter.com", "x.com", "instagram.com",
    ])

    def __init__(self, sem: asyncio.Semaphore):
        self.sem = sem

    async def search(
        self, client: httpx.AsyncClient,
        query: str, category: str, city: str,
    ) -> list[Lead]:
        url = (
            f"{self.BASE}?q={quote_plus(query)}"
            "&count=10&mkt=en-IN&setlang=en-IN&cc=IN"
        )
        async with self.sem:
            html = await safe_get(
                client, url, retries=2, base_delay=2.0,
                referer="https://www.bing.com/",
            )
        if not html:
            return []
        if len(html) < 5000 or "b_results" not in html:
            logger.warning(f"BingSerpScraper: bot-detection page for [{query}]")
            return []
        return self._parse(html, category, city)

    def _parse(self, html: str, category: str, city: str) -> list[Lead]:
        soup  = BeautifulSoup(html, "html.parser")
        items = (
            soup.select("li.b_algo")
            or soup.select("div.b_algo")
            or soup.select("#b_results > li:not(.b_ad)")
            or soup.select("main article, main section")
        )
        if not items:
            return self._raw_links(soup, category, city)

        leads: list[Lead] = []
        for item in items:
            title_el = item.select_one("h2 a, .b_title a, h3 a, h2")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            url   = title_el.get("href", "")
            if not url:
                continue
            if any(d in urlparse(url).netloc for d in self.SKIP):
                continue
            snippet = soup_text(item.select_one(".b_caption p, .b_snippet, p"))
            text    = title + " " + snippet
            phones  = extract_phones(text)
            emails  = extract_emails(text)
            name    = clean_name(title)
            if not name:
                continue
            leads.append(Lead(
                company_name=name, category=category, city=city,
                phone=phones[0] if phones else "",
                email=emails[0] if emails else "",
                website=url,
                source="bing",
            ))
        logger.info(f"BingSerpScraper [{city}/{category}]: {len(leads)} leads")
        return leads

    def _raw_links(self, soup: BeautifulSoup, category: str, city: str) -> list[Lead]:
        leads: list[Lead] = []
        seen_domains: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                continue
            domain = urlparse(href).netloc.lstrip("www.")
            if any(s in domain for s in self.SKIP) or domain in seen_domains:
                continue
            seen_domains.add(domain)
            label = a.get_text(strip=True)
            if len(label) < 4:
                continue
            leads.append(Lead(
                company_name=clean_name(label),
                category=category, city=city,
                website=href, source="bing",
            ))
            if len(leads) >= 8:
                break
        return leads


class SulekhaScraper:
    """sulekha.com — strong for professional services (CA, CFO, marketing)."""
    CITY_SLUGS: dict[str, str] = {
        "Hyderabad": "hyderabad", "Mumbai": "mumbai",
        "Bangalore": "bangalore", "Delhi": "delhi-ncr",
        "Chennai": "chennai",
    }

    def __init__(self, sem: asyncio.Semaphore):
        self.sem = sem

    async def search(
        self, client: httpx.AsyncClient,
        cat_slug: str, city: str, category: str,
    ) -> list[Lead]:
        city_slug = self.CITY_SLUGS.get(city, city.lower())
        url = (
            f"https://www.sulekha.com/{cat_slug}"
            f"/{city_slug}-service-providers"
        )
        async with self.sem:
            html = await safe_get(client, url)
        if not html:
            return []
        return self._parse(html, category, city)

    def _parse(self, html: str, category: str, city: str) -> list[Lead]:
        soup  = BeautifulSoup(html, "html.parser")
        leads: list[Lead] = []
        cards = (
            soup.select(".sp-card")
            or soup.select(".provider-card")
            or soup.select("[class*='provider']")
            or soup.select("[class*='listing']")
            or soup.select("article")
        )
        for card in cards:
            name_el = first_el(card, [
                "h2", "h3", ".sp-name", "[class*='name']", "strong",
            ])
            if not name_el:
                continue
            name = clean_name(soup_text(name_el))
            if len(name) < 3:
                continue
            text   = card.get_text(" ", strip=True)
            phones = extract_phones(text)
            emails = extract_emails(text)
            addr_el = first_el(card, [
                ".address", "[class*='addr']", "[class*='location']",
            ])
            leads.append(Lead(
                company_name=name, category=category, city=city,
                phone=phones[0] if phones else "",
                email=emails[0] if emails else "",
                address=soup_text(addr_el)[:200],
                source="sulekha",
            ))
        logger.info(f"SulekhaScraper [{city}/{category}]: {len(leads)} leads")
        return leads


class SiteSearchScraper:
    """
    Uses Bing `site:justdial.com <keyword> <city>` to find JD URLs,
    then scrapes individual pages — avoids JS-rendered homepage.
    """
    def __init__(self, bing_sem: asyncio.Semaphore, page_sem: asyncio.Semaphore):
        self.bing_sem = bing_sem
        self.page_sem = page_sem

    async def get_urls(
        self, client: httpx.AsyncClient, site: str,
        keyword: str, city: str,
    ) -> list[str]:
        q   = f"site:{site} {keyword} {city}"
        url = (
            f"https://www.bing.com/search?q={quote_plus(q)}"
            "&count=8&mkt=en-IN"
        )
        async with self.bing_sem:
            html = await safe_get(client, url, base_delay=2.0)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if site in href and href.startswith("http"):
                urls.append(href)
        return list(dict.fromkeys(urls))[:6]

    async def scrape_page(
        self, client: httpx.AsyncClient, url: str,
        category: str, city: str, source_label: str,
    ) -> Optional[Lead]:
        async with self.page_sem:
            html = await safe_get(
                client, url, referer="https://www.bing.com/"
            )
        if not html:
            return None
        soup    = BeautifulSoup(html, "html.parser")
        name_el = first_el(soup, [
            "h1", "[class*='comp-name']",
            "[class*='fn']", "[class*='biz']", "title",
        ])
        if not name_el:
            return None
        name = clean_name(soup_text(name_el))
        if len(name) < 3:
            return None
        text   = soup.get_text(" ", strip=True)
        jld_ph, jld_em = extract_jsonld_contacts(html)
        phones = jld_ph or extract_phones(text)
        emails = jld_em or extract_emails(text)
        return Lead(
            company_name=name, category=category, city=city,
            phone=phones[0] if phones else "",
            email=emails[0] if emails else "",
            website=url, source=source_label,
        )


class WebsiteEnricher:
    """Crawl company websites to fill missing phone/email on existing leads."""
    PATHS = [
        "/contact", "/contact-us", "/contactus",
        "/about", "/about-us", "/reach-us", "/get-in-touch", "/",
    ]

    def __init__(self, sem: asyncio.Semaphore):
        self.sem = sem

    async def enrich(self, client: httpx.AsyncClient, lead: Lead) -> Lead:
        if not lead.website or (lead.phone and lead.email):
            return lead
        parsed = urlparse(lead.website)
        if not parsed.scheme or not parsed.netloc:
            return lead
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in self.PATHS:
            try:
                async with self.sem:
                    html = await safe_get(
                        client, base + path,
                        retries=2, base_delay=0.5, referer=base,
                    )
                if not html:
                    continue
                jld_ph, jld_em = extract_jsonld_contacts(html)
                phones = jld_ph or extract_phones(html)
                emails = jld_em or extract_emails(html)
                if not lead.phone and phones:
                    lead.phone = phones[0]
                if not lead.email and emails:
                    lead.email = emails[0]
                if not lead.address:
                    s = BeautifulSoup(html, "html.parser")
                    el = first_el(s, [
                        "address", "[class*='address']",
                        "[class*='location']", "[itemprop='address']",
                    ])
                    if el:
                        lead.address = soup_text(el)[:200]
                if lead.phone and lead.email:
                    break
            except Exception as exc:
                logger.debug(f"WebsiteEnricher {base + path}: {exc}")
        return lead


# ══════════════════════════════════════════════════════════════════════════════
# § 6  PIPELINE ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

class LeadScrapingPipeline:
    """
    Multi-phase, multi-source B2B lead scraping pipeline.

    HIGH-2 FIX: constructor accepts sources → only requested scrapers run.
    HIGH-3 FIX: constructor accepts max_leads → stops early when limit hit.
    HIGH-4 FIX: constructor accepts search_queries → custom Bing queries run.
    HIGH-6 FIX: SEARCH_CATEGORIES keys now match LeadCategory schema IDs.
    HIGH-7 FIX: DB persistence uses LeadStore (correct model, cumulative save).

    Phase 1 — IndiaMART   (most reliable — confirmed 200 responses)
    Phase 2 — Bing SERP   (5-selector fallback + custom queries)
    Phase 3 — Sulekha     (professional services speciality)
    Phase 4 — JustDial    (via Bing site: search — avoids JS rendering)
    Phase 5 — Enrichment  (website crawl for missing phone/email)
    """

    def __init__(
        self,
        categories:     Optional[list[str]] = None,
        cities:         Optional[list[str]] = None,
        sources:        Optional[list[str]] = None,   # HIGH-2 FIX
        max_leads:      int = 500,                    # HIGH-3 FIX
        search_queries: Optional[list[str]] = None,   # HIGH-4 FIX
        progress_cb:    Optional[Callable[[int], None]] = None,
        job_id:         str = "",
        user_id:        str = "",
    ):
        # HIGH-6 FIX: only keep categories that exist in SEARCH_CATEGORIES
        raw_cats = categories or list(SEARCH_CATEGORIES.keys())
        self.categories = [c for c in raw_cats if c in SEARCH_CATEGORIES]
        if not self.categories:
            # Fall back to all known categories if none of the requested ones match
            self.categories = list(SEARCH_CATEGORIES.keys())

        self.cities         = cities or TARGET_CITIES
        self.sources        = frozenset(sources or ALL_SOURCES)
        self.max_leads      = max(1, max_leads)
        self.search_queries = search_queries or []
        self.progress_cb    = progress_cb or (lambda _p: None)
        self.job_id         = job_id
        self.user_id        = user_id

        # Per-source semaphores — conservative for rate-limit hygiene
        self._bing_sem       = asyncio.Semaphore(2)
        self._indiamart_sem  = asyncio.Semaphore(4)
        self._sulekha_sem    = asyncio.Semaphore(3)
        self._page_sem       = asyncio.Semaphore(8)
        self._enrich_sem     = asyncio.Semaphore(12)

        self._seen_keys: set[str]   = set()
        self._all_leads: list[Lead] = []
        self._stats: dict[str, int] = {
            "indiamart": 0, "bing": 0, "sulekha": 0,
            "justdial": 0, "enriched_phone": 0, "enriched_email": 0,
        }

    # ── Dedup + max_leads guard ───────────────────────────────────────────────

    def _saturated(self) -> bool:
        return len(self._all_leads) >= self.max_leads

    def _add(self, leads: list[Lead]) -> int:
        """
        HIGH-7 FIX: no longer calls save_leads_batch internally.
        DB persistence is done once via LeadStore.flush() at the end of run().
        """
        added = 0
        for lead in leads:
            if self._saturated():
                break
            if not lead.company_name or len(lead.company_name) < 3:
                continue
            key = lead.dedup_key
            if key not in self._seen_keys:
                self._seen_keys.add(key)
                self._all_leads.append(lead)
                added += 1
        return added

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(self) -> list[Lead]:
        async with build_client() as client:
            # HIGH-2 FIX: each phase is gated on sources membership
            if "indiamart" in self.sources and not self._saturated():
                logger.info("=== Phase 1: IndiaMART ===")
                await self._phase_indiamart(client)
            self.progress_cb(20)

            if "bing" in self.sources and not self._saturated():
                logger.info("=== Phase 2: Bing SERP ===")
                await self._phase_bing(client)
            self.progress_cb(40)

            if "sulekha" in self.sources and not self._saturated():
                logger.info("=== Phase 3: Sulekha ===")
                await self._phase_sulekha(client)
            self.progress_cb(55)

            if "justdial" in self.sources and not self._saturated():
                logger.info("=== Phase 4: JustDial ===")
                await self._phase_justdial(client)
            self.progress_cb(65)

            logger.info("=== Phase 5: Website Enrichment ===")
            await self._phase_enrich(client)
            self.progress_cb(92)

        logger.info(
            f"Pipeline complete: {len(self._all_leads)} unique leads "
            f"(cap={self.max_leads}, sources={set(self.sources)}) | "
            f"stats={self._stats}"
        )
        return self._all_leads

    # ── Phase implementations ─────────────────────────────────────────────────

    async def _phase_indiamart(self, client: httpx.AsyncClient) -> None:
        scraper = IndiaMARTScraper(self._indiamart_sem)
        tasks = [
            scraper.search(
                client,
                SEARCH_CATEGORIES[cat]["indiamart_ss"],
                city,
                SEARCH_CATEGORIES[cat]["label"],
            )
            for cat in self.categories
            for city in self.cities
        ]
        for r in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(r, list):
                self._stats["indiamart"] += self._add(r)

    async def _phase_bing(self, client: httpx.AsyncClient) -> None:
        scraper = BingSerpScraper(self._bing_sem)
        tasks   = []

        # Category default queries
        for cat in self.categories:
            info = SEARCH_CATEGORIES[cat]
            kw   = info["keywords"][0]
            for city in self.cities:
                tasks.append(
                    scraper.search(
                        client,
                        f"{kw} {city} India contact phone",
                        info["label"],
                        city,
                    )
                )

        # HIGH-4 FIX: add user-supplied custom queries
        for query in self.search_queries:
            for city in self.cities:
                tasks.append(
                    scraper.search(client, f"{query} {city} India", "Custom", city)
                )

        for r in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(r, list):
                self._stats["bing"] += self._add(r)

    async def _phase_sulekha(self, client: httpx.AsyncClient) -> None:
        scraper = SulekhaScraper(self._sulekha_sem)
        tasks   = []
        for cat in self.categories:
            info      = SEARCH_CATEGORIES[cat]
            cat_slug  = info.get("sulekha_slug")
            if not cat_slug:
                continue
            for city in self.cities:
                tasks.append(
                    scraper.search(client, cat_slug, city, info["label"])
                )
        for r in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(r, list):
                self._stats["sulekha"] += self._add(r)

    async def _phase_justdial(self, client: httpx.AsyncClient) -> None:
        jd        = SiteSearchScraper(self._bing_sem, self._page_sem)
        url_tasks = []
        meta:     list[tuple[str, str]] = []

        for cat in self.categories:
            info = SEARCH_CATEGORIES[cat]
            kw   = " ".join(info["keywords"][0].split()[:3])
            for city in self.cities:
                url_tasks.append(jd.get_urls(client, "justdial.com", kw, city))
                meta.append((info["label"], city))

        url_batches = await asyncio.gather(*url_tasks, return_exceptions=True)

        page_tasks = [
            jd.scrape_page(client, url, category, city, "justdial")
            for (category, city), batch in zip(meta, url_batches)
            if isinstance(batch, list)
            for url in batch
        ]
        for r in await asyncio.gather(*page_tasks, return_exceptions=True):
            if isinstance(r, Lead):
                self._stats["justdial"] += self._add([r])

    async def _phase_enrich(self, client: httpx.AsyncClient) -> None:
        enricher   = WebsiteEnricher(self._enrich_sem)
        to_enrich  = [
            l for l in self._all_leads
            if l.website and not l.has_contact()
        ][:400]
        logger.info(f"Enriching {len(to_enrich)} leads via website crawl")
        if not to_enrich:
            return
        enriched = await asyncio.gather(
            *[enricher.enrich(client, l) for l in to_enrich],
            return_exceptions=True,
        )
        for lead, result in zip(to_enrich, enriched):
            if isinstance(result, Lead):
                if not lead.phone  and result.phone:  lead.phone  = result.phone
                if not lead.email  and result.email:  lead.email  = result.email
                if not lead.address and result.address: lead.address = result.address
            if lead.phone:  self._stats["enriched_phone"] += 1
            if lead.email:  self._stats["enriched_email"] += 1


# ══════════════════════════════════════════════════════════════════════════════
# § 7  EXCEL EXPORT — NO TRUNCATION
# ══════════════════════════════════════════════════════════════════════════════

def export_to_excel(leads: list[Lead], filepath: str) -> int:
    """
    Write ALL leads to a single Excel workbook with no slicing or limits.
    Returns exact number of data rows written.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as e:
        raise RuntimeError("pip install openpyxl") from e

    wb = Workbook()
    ws = wb.active
    ws.title = "B2B Leads"

    COLUMNS = [
        ("Company Name",   36),
        ("Phone",          15),
        ("Mobile",         15),
        ("Email",          34),
        ("Website",        42),
        ("Address",        46),
        ("Category",       24),
        ("City",           14),
        ("Source",         18),
        ("Has Phone",      10),
        ("Has Email",      10),
        ("Quality Score",  13),
    ]

    hdr_font  = Font(bold=True, color="FFFFFF", size=11)
    hdr_fill  = PatternFill(
        start_color="1F497D", end_color="1F497D", fill_type="solid"
    )
    hdr_align = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    for col_i, (col_name, col_w) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=col_i, value=col_name)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = hdr_align
        ws.column_dimensions[get_column_letter(col_i)].width = col_w

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}1"

    alt_fill   = PatternFill(
        start_color="EEF4FB", end_color="EEF4FB", fill_type="solid"
    )
    data_align = Alignment(vertical="center", wrap_text=False)

    # Iterate ALL leads — no slicing, no limit
    for row_i, lead in enumerate(leads, 2):
        row_vals = [
            lead.company_name,
            lead.phone,
            lead.mobile,
            lead.email,
            lead.website,
            lead.address,
            lead.category,
            lead.city,
            lead.source,
            "Yes" if (lead.phone or lead.mobile) else "No",
            "Yes" if lead.email else "No",
            lead.quality_score(),
        ]
        for col_i, val in enumerate(row_vals, 1):
            cell = ws.cell(row=row_i, column=col_i, value=val)
            cell.alignment = data_align
            if row_i % 2 == 0:
                cell.fill = alt_fill

    # Summary sheet
    ws2 = wb.create_sheet("Summary")
    ws2.column_dimensions["A"].width = 32
    ws2.column_dimensions["B"].width = 15

    def _counts(attr: str) -> list[tuple[str, int]]:
        d: dict[str, int] = {}
        for l in leads:
            k = getattr(l, attr, "")
            d[k] = d.get(k, 0) + 1
        return sorted(d.items(), key=lambda x: -x[1])

    sections: list[tuple[str, object]] = [
        ("Total Leads",         len(leads)),
        ("With Phone / Mobile", sum(1 for l in leads if l.phone or l.mobile)),
        ("With Email",          sum(1 for l in leads if l.email)),
        ("With Website",        sum(1 for l in leads if l.website)),
        ("Phone + Email",       sum(1 for l in leads if (l.phone or l.mobile) and l.email)),
        ("", ""),
        ("── By City ──", ""),
    ]
    for k, v in _counts("city"):
        sections.append((f"  {k}", v))
    sections.append(("── By Category ──", ""))
    for k, v in _counts("category"):
        sections.append((f"  {k}", v))
    sections.append(("── By Source ──", ""))
    for k, v in _counts("source"):
        sections.append((f"  {k}", v))

    bold = Font(bold=True)
    for r_i, (label, value) in enumerate(sections, 1):
        ws2.cell(row=r_i, column=1, value=label).font = (
            bold if "──" in str(label) else Font()
        )
        ws2.cell(row=r_i, column=2, value=value)

    wb.save(filepath)
    logger.info(
        f"Excel → {filepath} | {len(leads)} rows "
        f"(phone={sum(1 for l in leads if l.phone)}, "
        f"email={sum(1 for l in leads if l.email)})"
    )
    return len(leads)


# ══════════════════════════════════════════════════════════════════════════════
# § 8  SYNC ENTRY POINT  (Celery-safe wrapper)
# ══════════════════════════════════════════════════════════════════════════════

def run_lead_scrape_sync(
    job_id:         str,
    categories:     Optional[list[str]] = None,
    cities:         Optional[list[str]] = None,
    sources:        Optional[list[str]] = None,    # HIGH-1 FIX: now accepted
    max_leads:      int = 500,                     # HIGH-1 FIX: now accepted
    search_queries: Optional[list[str]] = None,    # HIGH-1 FIX: now accepted
    progress_cb:    Optional[Callable[[int], None]] = None,
    user_id:        str = "",
) -> dict:
    """
    Synchronous wrapper — call from Celery task.
    Creates a fresh event loop (safe inside a Celery worker thread).

    HIGH-1 FIX: search_queries, sources, max_leads now accepted and wired
                to LeadScrapingPipeline instead of being silently dropped.
    HIGH-5 FIX: no RuntimeError on zero leads — returns gracefully with
                total_leads=0 so Celery marks job as success, not retrying.
    HIGH-7 FIX: single LeadStore.flush() saves all leads at once. No more
                partial saves or broken batch logic.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        pipeline = LeadScrapingPipeline(
            categories=categories,
            cities=cities,
            sources=sources,
            max_leads=max_leads,
            search_queries=search_queries,
            progress_cb=progress_cb or (lambda _: None),
            job_id=job_id,
            user_id=user_id,
        )
        leads = loop.run_until_complete(pipeline.run())
    finally:
        loop.close()

    # HIGH-5 FIX: warn but never raise on zero leads
    if not leads:
        logger.warning(
            f"[run_lead_scrape_sync] job={job_id}: "
            "zero leads scraped from all configured sources"
        )

    # HIGH-7 FIX: one flush saves everything correctly via LeadStore
    if leads and job_id:
        try:
            from app.services.scraper.lead_store import LeadStore
            store = LeadStore(job_id=job_id, user_id=user_id)
            store.add(leads)
            store.flush()
        except Exception as exc:
            # Non-fatal — Excel is the source of truth
            logger.error(f"[run_lead_scrape_sync] DB persist failed: {exc}")

    # Excel export
    tmp_dir    = tempfile.mkdtemp()
    excel_path = os.path.join(tmp_dir, f"b2b_leads_{job_id}.xlsx")
    rows_written = export_to_excel(leads, excel_path)

    by_cat:  dict[str, int] = {}
    by_city: dict[str, int] = {}
    by_src:  dict[str, int] = {}
    for l in leads:
        by_cat[l.category]  = by_cat.get(l.category, 0)  + 1
        by_city[l.city]     = by_city.get(l.city, 0)     + 1
        by_src[l.source]    = by_src.get(l.source, 0)    + 1

    return {
        "total_leads":  len(leads),
        "rows_written": rows_written,
        "with_phone":   sum(1 for l in leads if l.phone or l.mobile),
        "with_email":   sum(1 for l in leads if l.email),
        "with_website": sum(1 for l in leads if l.website),
        "by_category":  by_cat,
        "by_city":      by_city,
        "by_source":    by_src,
        "excel_path":   excel_path,
        "job_id":       job_id,
    }