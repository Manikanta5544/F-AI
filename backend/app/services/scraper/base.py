"""
Base scraper infrastructure — Tasks #1, #2, #3.

All platform scrapers inherit BaseScraper which provides:
  - Playwright browser lifecycle (async context manager)
  - Anti-bot hygiene: random user-agents, delays, webdriver masking
  - Retry logic with tenacity (3 attempts, exponential backoff)
  - Cache-before-fetch: Redis SHA-256 keyed cache (1h TTL)
"""
from __future__ import annotations

import abc
import asyncio
import hashlib
import random
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.redis import cache_get, cache_set

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

_ACCEPT_LANGUAGE = "en-IN,en-GB;q=0.9,en;q=0.8,hi;q=0.7"


class ScrapedItem(dict):
    """Dict subclass for scraped product data — typed accessors via .get()."""


class BaseScraper(abc.ABC):
    platform: str
    cache_ttl: int = 3600  # 1 hour cache per URL

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "BaseScraper":
        from playwright.async_api import async_playwright  # type: ignore[import]

        self._pw = await async_playwright().start()
        launch_opts: dict[str, Any] = {
            "headless": settings.PLAYWRIGHT_HEADLESS,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        }
        if settings.SCRAPER_PROXY_URL:
            launch_opts["proxy"] = {"server": settings.SCRAPER_PROXY_URL}

        self._browser = await self._pw.chromium.launch(**launch_opts)
        self._context = await self._browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1366, "height": 768},
            extra_http_headers={
                "Accept-Language": _ACCEPT_LANGUAGE,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        # Mask Playwright's webdriver fingerprint
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _get_page(self):
        assert self._context is not None, "Scraper must be used as async context manager"
        return await self._context.new_page()

    async def _human_delay(self) -> None:
        """Random delay mimicking human reading speed."""
        delay = random.uniform(settings.SCRAPER_MIN_DELAY_S, settings.SCRAPER_MAX_DELAY_S)
        await asyncio.sleep(delay)

    def _url_cache_key(self, url: str) -> str:
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        return f"scrape:{self.platform}:{digest}"

    async def scrape_urls(self, urls: list[str]) -> list[ScrapedItem]:
        """Scrape a list of URLs sequentially with human delays between requests."""
        results = []
        for url in urls:
            item = await self._scrape_with_cache(url)
            if item:
                results.append(item)
            await self._human_delay()
        return results

    async def _scrape_with_cache(self, url: str) -> ScrapedItem | None:
        cache_key = self._url_cache_key(url)
        cached = await cache_get(cache_key)
        if cached:
            return ScrapedItem(cached)
        item = await self._scrape_one_with_retry(url)
        if item:
            await cache_set(cache_key, dict(item), ttl_seconds=self.cache_ttl)
        return item

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
    )
    async def _scrape_one_with_retry(self, url: str) -> ScrapedItem | None:
        return await self.scrape_one(url)

    @abc.abstractmethod
    async def scrape_one(self, url: str) -> ScrapedItem | None:
        """Scrape a single URL. Override per platform."""