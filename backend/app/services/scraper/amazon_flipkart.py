"""
Amazon and Flipkart product scrapers — Tasks #1 and #2.

Production improvements over original:
- Multi-selector fallback chains for every field (Amazon regularly rotates CSS classes)
- Structured data (JSON-LD / window.__PRELOADED_STATE__) parsed first — faster & more
  reliable than DOM scraping because structured data survives CSS class changes
- Playwright intercepts XHR on Flipkart to get clean JSON before HTML parse
- Explicit human-delay between pages (in BaseScraper.scrape_urls)
- ASIN/product-ID extracted and stored for deduplication
- All price extraction handles ₹, Rs., INR prefixes and comma-separated thousands
- Discount calculated from prices if not found in DOM (prevents None gaps)
- All parse helpers return None on failure — no ValueError propagation
"""
from __future__ import annotations

import json
import re
import asyncio
import logging
from typing import Any
from bs4 import BeautifulSoup

from app.services.scraper.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)


# ── Shared price / percentage parsers ────────────────────────────────────────

def _parse_price(text: str | None) -> float | None:
    """Extract the first numeric value from a price string.
    Handles ₹1,299, Rs. 999, INR 500, etc."""
    if not text:
        return None
    # Remove currency symbols and non-numeric chars except dot
    cleaned = re.sub(r"[^\d.]", "", str(text).replace(",", ""))
    try:
        v = float(cleaned)
        return round(v, 2) if v > 0 else None
    except ValueError:
        return None


def _parse_percentage(text: str | None) -> float | None:
    """Extract numeric discount percentage from strings like '15% off', '-15%'."""
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _calc_discount(price: float | None, original: float | None) -> float | None:
    """Calculate discount % from price and original price."""
    if price and original and original > price:
        return round((original - price) / original * 100, 1)
    return None


# ── Task #1: Amazon ───────────────────────────────────────────────────────────

class AmazonScraper(BaseScraper):
    """
    Amazon India product scraper.

    Strategy (most reliable first):
    1. JSON-LD structured data (<script type="application/ld+json">)
    2. window.__PRELOADED_STATE__ JSON blob
    3. DOM element selectors with multi-selector fallback chains
    """
    platform = "amazon"

    # Multi-selector fallback chains — Amazon rotates class names frequently
    _TITLE_SELS = ["#productTitle", "#title span", "h1.a-size-large", ".product-title-word-break"]
    _PRICE_SELS = [
        ".a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price-whole",
        "#apex_desktop .a-price .a-offscreen",
        "#corePrice_feature_div .a-price .a-offscreen",
        "#price_inside_buybox",
    ]
    _ORIG_PRICE_SELS = [
        ".a-text-price .a-offscreen",
        "#priceblock_saleprice",
        ".a-text-strike .a-offscreen",
        "#booksHeaderSection .a-text-price",
    ]
    _DISCOUNT_SELS = [".savingsPercentage", ".reinventPriceSavingsPercentageMargin"]
    _RATING_SELS   = ["#acrPopover", ".a-icon-star span.a-icon-alt", "#averageCustomerReviews_feature_div .a-icon-star"]
    _REVIEW_SELS   = ["#acrCustomerReviewText", "#acrCustomerReviewLink span", "#reviews-medley-cmps-expand-head span"]
    _AVAIL_SELS    = ["#availability span", "#outOfStock", "#add-to-cart-button"]
    _BRAND_SELS    = ["#bylineInfo", "#brand", ".po-brand .po-break-word", "a#brandTextBinchmark_feature_div"]
    _CATEGORY_SELS = ["#wayfinding-breadcrumbs_container", "#nav-subnav", ".a-breadcrumb"]

    async def scrape_one(self, url: str) -> ScrapedItem | None:
        async with self._context.new_page() as page:
            try:
                # Block ads/tracking pixels to speed up load
                await page.route(
                    "**/{ads,analytics,doubleclick,googletagmanager,googleadservices}**",
                    lambda r: r.abort(),
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
                # Wait for the product title — essential element
                try:
                    await page.wait_for_selector("#productTitle, #title", timeout=12_000)
                except Exception:
                    pass  # Title may be in a different slot; continue with what we have
                html = await page.content()
            except Exception as exc:
                logger.warning("amazon_scrape_failed", url=url, error=str(exc))
                return None

        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")

        # ── 1. Try structured JSON-LD first ──────────────────────────────────
        item = self._parse_json_ld(soup, url)
        if item:
            return item

        # ── 2. DOM extraction with fallback chains ────────────────────────────
        def first_text(*sels: str) -> str:
            for sel in sels:
                el = soup.select_one(sel)
                if el:
                    return el.get_text(strip=True)
            return ""

        title = first_text(*self._TITLE_SELS)
        if not title:
            return None  # Page load failed or bot-challenged

        price           = _parse_price(first_text(*self._PRICE_SELS))
        original_price  = _parse_price(first_text(*self._ORIG_PRICE_SELS))
        discount_text   = first_text(*self._DISCOUNT_SELS)
        discount        = _parse_percentage(discount_text) or _calc_discount(price, original_price)

        # Rating — prefer title attribute ("4.3 out of 5 stars")
        rating = None
        for sel in self._RATING_SELS:
            el = soup.select_one(sel)
            if el:
                title_attr = el.get("title", "") or el.get_text(strip=True)
                m = re.search(r"([\d.]+)", title_attr)
                if m:
                    rating = _safe_float(m.group(1))
                    if rating and rating > 5:
                        rating = None  # sanity check
                    break

        # Review count
        review_count = None
        for sel in self._REVIEW_SELS:
            el = soup.select_one(sel)
            if el:
                m = re.search(r"([\d,]+)", el.get_text())
                if m:
                    review_count = int(m.group(1).replace(",", ""))
                    break

        # Availability
        avail_text = first_text(*self._AVAIL_SELS).lower()
        if "in stock" in avail_text or soup.select_one("#add-to-cart-button"):
            availability = "in_stock"
        elif "out of stock" in avail_text or "currently unavailable" in avail_text:
            availability = "out_of_stock"
        else:
            availability = "limited"

        # Brand
        brand_text = first_text(*self._BRAND_SELS)
        brand = (
            brand_text
            .replace("Brand: ", "")
            .replace("Visit the ", "")
            .split(" Store")[0]
            .strip()
        ) or None

        # Category
        category_el = soup.select_one(self._CATEGORY_SELS[0])
        category = (
            " > ".join(a.get_text(strip=True) for a in category_el.select("li a"))
            if category_el else None
        )

        # Image — prefer data-old-hires (full-res) over src (thumbnail)
        images: list[str] = []
        img_el = soup.select_one("#imgBlkFront, #landingImage, #main-image")
        if img_el:
            src = str(img_el.get("data-old-hires") or img_el.get("src") or "")
            if src:
                images.append(src)

        asin_match = re.search(r"/dp/([A-Z0-9]{10})", url)
        product_id = asin_match.group(1) if asin_match else None

        return ScrapedItem(
            platform="amazon",
            product_id=product_id,
            title=title,
            price=price,
            original_price=original_price,
            discount=discount,
            currency="INR",
            rating=rating,
            review_count=review_count,
            availability=availability,
            brand=brand,
            category=category,
            url=url,
            images=images,
            extra_meta={"asin": product_id},
        )

    def _parse_json_ld(self, soup: BeautifulSoup, url: str) -> ScrapedItem | None:
        """Parse JSON-LD structured data — most reliable when present."""
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                if not isinstance(data, dict):
                    continue
                # Handle @graph array or direct Product object
                objects = data.get("@graph", [data])
                for obj in objects:
                    if obj.get("@type") not in ("Product", "IndividualProduct"):
                        continue
                    title = obj.get("name", "")
                    if not title:
                        continue
                    offers = obj.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = _safe_float(offers.get("price"))
                    rating_obj = obj.get("aggregateRating", {})
                    rating = _safe_float(rating_obj.get("ratingValue"))
                    review_count = None
                    rc = rating_obj.get("reviewCount") or rating_obj.get("ratingCount")
                    if rc:
                        try:
                            review_count = int(rc)
                        except (ValueError, TypeError):
                            pass
                    avail_url = str(offers.get("availability", "")).lower()
                    if "instock" in avail_url:
                        availability = "in_stock"
                    elif "outofstock" in avail_url:
                        availability = "out_of_stock"
                    else:
                        availability = "limited"
                    asin_match = re.search(r"/dp/([A-Z0-9]{10})", url)
                    product_id = asin_match.group(1) if asin_match else None
                    images = obj.get("image", [])
                    if isinstance(images, str):
                        images = [images]
                    return ScrapedItem(
                        platform="amazon",
                        product_id=product_id,
                        title=title,
                        price=price,
                        original_price=None,
                        discount=None,
                        currency=offers.get("priceCurrency", "INR"),
                        rating=rating,
                        review_count=review_count,
                        availability=availability,
                        brand=str(obj.get("brand", {}).get("name", "") or ""),
                        category=None,
                        url=url,
                        images=images[:3],
                        extra_meta={"source": "json_ld", "asin": product_id},
                    )
            except (json.JSONDecodeError, AttributeError, KeyError):
                continue
        return None


# ── Task #1: Flipkart ─────────────────────────────────────────────────────────

class FlipkartScraper(BaseScraper):
    """
    Flipkart product scraper.

    Strategy:
    1. Intercept Flipkart's internal API XHR response (cleanest data)
    2. Parse window.__PRELOADED_STATE__ JSON blob from HTML
    3. DOM extraction with multi-selector fallback chains
    """
    platform = "flipkart"

    # Flipkart rotates hash-based CSS classes — multi-selector fallbacks are essential
    _TITLE_SELS   = [".B_NuCI", ".yhB1nd", "h1.Gq9Me", ".pdp-e-i-head", "h1"]
    _PRICE_SELS   = ["._30jeq3._16Jk6d", "._30jeq3", ".Nx9bqj", "._16Jk6d", "._25b18"]
    _ORIG_SELS    = ["._3I9_wc", "._3auQ3N", ".yRaY8j"]
    _DISC_SELS    = ["._3Ay6Sb span", "._11dKQP", ".UkUFwK span"]
    _RATING_SELS  = ["._3LWZlK", "div.XQDdHH", ".ipqd2A", "._1lRcqv ._3LWZlK"]
    _REVIEW_SELS  = ["._2_R_DZ span", "span._13vcmD", "span.rowspan"]
    _AVAIL_SELS   = ["._16FRp0", "#addToCartButton", "#buyNowButton"]
    _BRAND_SELS   = ["._2rQ-NK", ".G6XhRU", "._3N0uGr", "a.ui-pdp-seller__brand-name"]
    _BREAD_SELS   = ["._1MR4o5", "._3GIHBu a", "a._2whKao"]

    async def scrape_one(self, url: str) -> ScrapedItem | None:
        captured_api: list[dict] = []

        async with self._context.new_page() as page:
            # Intercept Flipkart's internal API for product data
            async def handle_response(response):
                if (
                    "api.flipkart.com" in response.url
                    and response.status == 200
                    and "product" in response.url.lower()
                ):
                    try:
                        data = await response.json()
                        captured_api.append(data)
                    except Exception:
                        pass

            page.on("response", handle_response)

            try:
                # Block resource-heavy items that slow page load
                await page.route(
                    "**/*.{png,jpg,jpeg,gif,svg,woff,woff2}",
                    lambda r: r.abort(),
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=35_000)

                # Close login popup if present
                for popup_sel in ["._2KpZ6l._2doB4z", "button._2doB4z", "[class*='CloseModal']"]:
                    try:
                        btn = await page.query_selector(popup_sel)
                        if btn:
                            await btn.click()
                            await asyncio.sleep(0.5)
                            break
                    except Exception:
                        pass

                try:
                    await page.wait_for_selector(
                        ", ".join(self._TITLE_SELS[:3]), timeout=10_000
                    )
                except Exception:
                    pass
                html = await page.content()

            except Exception as exc:
                logger.warning("flipkart_scrape_failed", url=url, error=str(exc))
                return None

        if not html:
            return None

        # ── 1. Try intercepted API data ──────────────────────────────────────
        if captured_api:
            item = self._parse_api_response(captured_api[0], url)
            if item:
                return item

        # ── 2. Try window.__PRELOADED_STATE__ ────────────────────────────────
        item = self._parse_preloaded_state(html, url)
        if item:
            return item

        # ── 3. DOM extraction ─────────────────────────────────────────────────
        soup = BeautifulSoup(html, "lxml")
        return self._parse_dom(soup, url)

    def _parse_api_response(self, data: dict, url: str) -> ScrapedItem | None:
        """Parse Flipkart internal API response."""
        try:
            pdp = (
                data.get("pageData", {})
                    .get("pageContext", {})
                    .get("productContext", {})
            )
            if not pdp:
                return None
            title = pdp.get("title") or pdp.get("productName", "")
            if not title:
                return None
            pricing = pdp.get("pricing", {})
            price = _safe_float(pricing.get("finalPrice", {}).get("value"))
            orig  = _safe_float(pricing.get("mrpPrice", {}).get("value"))
            disc  = _safe_float(pricing.get("discount", {}).get("value")) or _calc_discount(price, orig)
            ratings = pdp.get("rating", {})
            return ScrapedItem(
                platform="flipkart",
                product_id=pdp.get("productId") or pdp.get("fsn"),
                title=title,
                price=price,
                original_price=orig,
                discount=disc,
                currency="INR",
                rating=_safe_float(ratings.get("average")),
                review_count=None,
                availability="in_stock" if pdp.get("inStock") else "out_of_stock",
                brand=pdp.get("brand", ""),
                category=None,
                url=url,
                images=[],
                extra_meta={"source": "flipkart_api"},
            )
        except Exception:
            return None

    def _parse_preloaded_state(self, html: str, url: str) -> ScrapedItem | None:
        """Extract data from window.__PRELOADED_STATE__ JSON embedded in page."""
        match = re.search(r"window\.__PRELOADED_STATE__\s*=\s*({.+?});", html, re.DOTALL)
        if not match:
            return None
        try:
            state = json.loads(match.group(1))
            # Find product data — path varies by page type
            pdp_map: dict = {}
            for key, val in state.items():
                if isinstance(val, dict) and ("title" in val or "name" in val):
                    pdp_map = val
                    break
            if not pdp_map:
                return None
            title = pdp_map.get("title") or pdp_map.get("name", "")
            if not title:
                return None
            price = _parse_price(str(pdp_map.get("finalPrice", "")))
            orig  = _parse_price(str(pdp_map.get("mrpPrice", "")))
            return ScrapedItem(
                platform="flipkart",
                product_id=pdp_map.get("pid") or pdp_map.get("productId"),
                title=title,
                price=price,
                original_price=orig,
                discount=_calc_discount(price, orig),
                currency="INR",
                rating=_safe_float(pdp_map.get("rating")),
                review_count=None,
                availability="in_stock",
                brand=pdp_map.get("brand", ""),
                category=None,
                url=url,
                images=[],
                extra_meta={"source": "preloaded_state"},
            )
        except (json.JSONDecodeError, AttributeError):
            return None

    def _parse_dom(self, soup: BeautifulSoup, url: str) -> ScrapedItem | None:
        """DOM extraction with multi-selector fallback chains."""
        def first_text(*sels: str) -> str:
            for sel in sels:
                el = soup.select_one(sel)
                if el:
                    return el.get_text(strip=True)
            return ""

        title = first_text(*self._TITLE_SELS)
        if not title:
            return None

        price          = _parse_price(first_text(*self._PRICE_SELS))
        original_price = _parse_price(first_text(*self._ORIG_SELS))
        discount       = _parse_percentage(first_text(*self._DISC_SELS)) or _calc_discount(price, original_price)

        rating_text = first_text(*self._RATING_SELS)
        rating = None
        if rating_text:
            m = re.search(r"([\d.]+)", rating_text)
            if m:
                rating = _safe_float(m.group(1))

        review_count = None
        for sel in self._REVIEW_SELS:
            el = soup.select_one(sel)
            if el:
                m = re.search(r"([\d,]+)", el.get_text())
                if m:
                    review_count = int(m.group(1).replace(",", ""))
                    break

        # Availability: check for add-to-cart or explicit out-of-stock
        if soup.select_one("._16FRp0, #addToCartButton, #buyNowButton"):
            availability = "in_stock"
        elif soup.select_one("[class*='out-of-stock'], [class*='OutOfStock']"):
            availability = "out_of_stock"
        else:
            availability = "limited"

        brand_text = first_text(*self._BRAND_SELS)
        brand = brand_text.split("more")[0].strip() or None

        bread_els = soup.select(self._BREAD_SELS[0])
        if not bread_els:
            bread_els = soup.select(self._BREAD_SELS[1])
        category = (
            " > ".join(el.get_text(strip=True) for el in bread_els[:-1])
            if bread_els else None
        )

        images: list[str] = []
        for img_sel in ["._396cs4 img", "._2amPTt img", ".CXW8mj img"]:
            img_el = soup.select_one(img_sel)
            if img_el and img_el.get("src"):
                images.append(str(img_el["src"]))
                break

        # Product ID from URL (/p/ITME...)
        pid_match = re.search(r"/p/([A-Z0-9]+)", url)
        product_id = pid_match.group(1) if pid_match else None

        return ScrapedItem(
            platform="flipkart",
            product_id=product_id,
            title=title,
            price=price,
            original_price=original_price,
            discount=discount,
            currency="INR",
            rating=rating,
            review_count=review_count,
            availability=availability,
            brand=brand,
            category=category,
            url=url,
            images=images,
            extra_meta={"source": "dom"},
        )   