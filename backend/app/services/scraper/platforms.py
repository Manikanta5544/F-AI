"""
Task #3 — Universal extractor: Swiggy, Zomato, Manual brands.

Manual brand registry (5–9 brands): add new brands to BRAND_SELECTORS without
touching any other code — zero-code brand onboarding.

Universal dispatcher: get_scraper(platform) returns the correct scraper.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from app.services.scraper.base import BaseScraper, ScrapedItem
from app.services.scraper.amazon_flipkart import AmazonScraper, FlipkartScraper


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(text).replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


# ── Swiggy ────────────────────────────────────────────────────────────────────
class SwiggyScraper(BaseScraper):
    """Intercepts Swiggy's internal menu XHR to get structured restaurant data."""
    platform = "swiggy"

    async def scrape_one(self, url: str) -> ScrapedItem | None:
        page = await self._get_page()
        captured_data: list[dict] = []

        async def handle_response(response):
            if "menu" in response.url and response.status == 200:
                try:
                    captured_data.append(await response.json())
                except Exception:
                    pass

        page.on("response", handle_response)
        try:
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            html = await page.content()
        except Exception:
            return None
        finally:
            await page.close()

        if captured_data:
            try:
                info = (
                    captured_data[0]
                    .get("data", {})
                    .get("cards", [{}])[0]
                    .get("card", {})
                    .get("card", {})
                    .get("info", {})
                )
                name = info.get("name", "")
                rating = info.get("avgRating")
                return ScrapedItem(
                    platform="swiggy", product_id=info.get("id"),
                    title=name, price=None, original_price=None, discount=None,
                    currency="INR", rating=float(rating) if rating else None,
                    review_count=None, availability="in_stock", brand=name,
                    category="Restaurant", url=url,
                    images=[info.get("cloudinaryImageId", "")],
                    extra_meta={"cuisines": info.get("cuisines", [])},
                )
            except (KeyError, IndexError, TypeError):
                pass

        # Fallback: parse rendered HTML
        soup = BeautifulSoup(html, "lxml")
        title_el = soup.select_one('[class*="RestaurantNameAddress_name"]')
        title = title_el.get_text(strip=True) if title_el else "Unknown"
        return ScrapedItem(
            platform="swiggy", product_id=None, title=title,
            price=None, original_price=None, discount=None, currency="INR",
            rating=None, review_count=None, availability="in_stock",
            brand=title, category="Restaurant", url=url, images=[], extra_meta={},
        )


# ── Zomato ────────────────────────────────────────────────────────────────────
class ZomatoScraper(BaseScraper):
    """Zomato uses hashed CSS class names; falls back to semantic HTML structure."""
    platform = "zomato"

    async def scrape_one(self, url: str) -> ScrapedItem | None:
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_selector('h1[class*="sc-"]', timeout=10_000)
            html = await page.content()
        except Exception:
            return None
        finally:
            await page.close()

        soup = BeautifulSoup(html, "lxml")
        h1_el = soup.find("h1")
        title = h1_el.get_text(strip=True) if h1_el else ""
        rating_el = soup.find("span", string=re.compile(r"^[\d.]+$"))
        rating = float(rating_el.get_text()) if rating_el else None
        cuisine_els = soup.select('[class*="cuisine"]')
        cuisines = [el.get_text(strip=True) for el in cuisine_els[:3]]

        return ScrapedItem(
            platform="zomato", product_id=None, title=title,
            price=None, original_price=None, discount=None, currency="INR",
            rating=rating, review_count=None, availability="in_stock",
            brand=title, category="Restaurant", url=url, images=[],
            extra_meta={"cuisines": cuisines},
        )


# ── Task #2: Manual brand extractor (5–9 brands) ─────────────────────────────
# Add a new brand entry here — no other code changes needed.
BRAND_SELECTORS: dict[str, dict[str, str]] = {
    "nykaa": {
        "title":  ".css-xrzmfa",
        "price":  ".css-1jczs19",
        "rating": ".css-1lmzrv3",
        "image":  'img[class*="product"]',
    },
    "meesho": {
        "title":  "p[class*='ProductTitle']",
        "price":  "h5",
        "rating": "[class*='Rating']",
        "image":  "img[class*='Image']",
    },
    "myntra": {
        "title":  "h1.pdp-title",
        "price":  ".pdp-price strong",
        "rating": ".index-overallRating div",
        "image":  "img.img-responsive",
    },
    "snapdeal": {
        "title":  ".pdp-e-i-head",
        "price":  ".payBlkBig",
        "rating": ".filled-stars",
        "image":  "#product-image",
    },
    "ajio": {
        "title":  ".prod-name",
        "price":  ".prod-sp",
        "rating": "div.rating-block span",
        "image":  "img.rilrtl-products-image",
    },
    "bigbasket": {
        "title":  "h1.pd__title",
        "price":  "span.pd__price",
        "rating": "span.rating__value",
        "image":  "img.pd__image",
    },
    "jiomart": {
        "title":  ".product-name",
        "price":  ".final-price",
        "rating": ".rating-count",
        "image":  ".product-img img",
    },
    "croma": {
        "title":  ".pd-title",
        "price":  ".new-price",
        "rating": ".rating-value",
        "image":  ".product-img",
    },
    "reliance_digital": {
        "title":  "h1.pdp_title",
        "price":  ".real-price",
        "rating": ".rdrating",
        "image":  ".pdp-img img",
    },
}


class ManualBrandScraper(BaseScraper):
    """Generic brand scraper using BRAND_SELECTORS registry."""
    platform = "manual"

    def __init__(self, brand: str) -> None:
        super().__init__()
        self.brand = brand.lower()
        self.selectors = BRAND_SELECTORS.get(self.brand, {})

    async def scrape_one(self, url: str) -> ScrapedItem | None:
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if title_sel := self.selectors.get("title"):
                try:
                    await page.wait_for_selector(title_sel, timeout=8_000)
                except Exception:
                    pass
            html = await page.content()
        except Exception:
            return None
        finally:
            await page.close()

        soup = BeautifulSoup(html, "lxml")

        def get_text(sel: str) -> str:
            el = soup.select_one(sel) if sel else None
            return el.get_text(strip=True) if el else ""

        def get_src(sel: str) -> str:
            el = soup.select_one(sel) if sel else None
            return str(el.get("src", "")) if el else ""

        title = get_text(self.selectors.get("title", "h1"))
        price = _parse_price(get_text(self.selectors.get("price", "")))
        rating_text = get_text(self.selectors.get("rating", ""))
        rating_match = re.search(r"[\d.]+", rating_text)
        rating = float(rating_match.group()) if rating_match else None
        img_src = get_src(self.selectors.get("image", ""))

        return ScrapedItem(
            platform="manual", product_id=None,
            title=title or url, price=price, original_price=None, discount=None,
            currency="INR", rating=rating, review_count=None, availability="in_stock",
            brand=self.brand, category=None, url=url,
            images=[img_src] if img_src else [],
            extra_meta={"brand": self.brand},
        )


# ── Universal dispatcher ──────────────────────────────────────────────────────
def get_scraper(platform: str, brand: str | None = None) -> BaseScraper:
    """
    Return the correct scraper instance for the given platform.
    Raises ValueError for unknown platforms (caught by Pydantic validation upstream).
    """
    match platform:
        case "amazon":
            return AmazonScraper()
        case "flipkart":
            return FlipkartScraper()
        case "swiggy":
            return SwiggyScraper()
        case "zomato":
            return ZomatoScraper()
        case "manual":
            return ManualBrandScraper(brand or "unknown")
        case _:
            raise ValueError(f"Unknown platform: {platform}")