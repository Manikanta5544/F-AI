import asyncio
import random
import logging
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
]


class StealthBingScraper:
    """
    Production-grade Bing scraper using Playwright.

    Fixes:
    - Reuses browser (no relaunch per request)
    - Handles bot detection
    - Adds retry logic
    - UA rotation
    """

    def __init__(self, sem: asyncio.Semaphore):
        self.sem = sem
        self.browser = None
        self.playwright = None

    # ─────────────────────────────────────────────
    # INIT / CLEANUP
    # ─────────────────────────────────────────────
    async def init(self):
        if self.browser:
            return

        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        logger.info("StealthBingScraper browser initialized")

    async def close(self):
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")

    # ─────────────────────────────────────────────
    # MAIN SEARCH
    # ─────────────────────────────────────────────
    async def search(self, query: str, category: str, city: str):
        await self.init()

        async with self.sem:
            for attempt in range(3):  # retry logic
                try:
                    context = await self.browser.new_context(
                        user_agent=random.choice(USER_AGENTS),
                        viewport={"width": 1280, "height": 800},
                    )

                    page = await context.new_page()

                    url = f"https://www.bing.com/search?q={query}"
                    await page.goto(url, timeout=60000)

                    await page.wait_for_timeout(random.randint(1500, 3000))

                    html = await page.content()
                    await context.close()

                    # 🔥 BOT DETECTION CHECK
                    if len(html) < 4000 or "b_algo" not in html:
                        logger.warning(f"Bing blocked or empty page for: {query}")
                        await asyncio.sleep(2 + attempt)
                        continue

                    return self._parse(html, category, city)

                except PlaywrightTimeout:
                    logger.warning(f"Timeout on Bing query: {query} (attempt {attempt})")

                except Exception as e:
                    logger.error(f"Bing scrape error: {e}")

                await asyncio.sleep(2 + attempt)

        return []

    # ─────────────────────────────────────────────
    # PARSER (ROBUST)
    # ─────────────────────────────────────────────
    def _parse(self, html, category, city):
        soup = BeautifulSoup(html, "html.parser")
        leads = []

        # Primary selector
        items = soup.select("li.b_algo")

        # Fallback selector
        if not items:
            items = soup.select("div.b_algo")

        # Last fallback → extract links
        if not items:
            return self._fallback_links(soup, category, city)

        for item in items:
            a = item.select_one("h2 a")
            if not a:
                continue

            title = a.get_text(strip=True)
            url = a.get("href")

            if not url:
                continue

            leads.append({
                "company_name": title,
                "website": url,
                "category": category,
                "city": city,
                "source": "bing_playwright"
            })

        return leads

    # ─────────────────────────────────────────────
    # LAST RESORT FALLBACK
    # ─────────────────────────────────────────────
    def _fallback_links(self, soup, category, city):
        leads = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]

            if not href.startswith("http"):
                continue

            if "bing.com" in href:
                continue

            if href in seen:
                continue

            seen.add(href)

            title = a.get_text(strip=True)
            if len(title) < 4:
                continue

            leads.append({
                "company_name": title,
                "website": href,
                "category": category,
                "city": city,
                "source": "bing_fallback"
            })

            if len(leads) >= 8:
                break

        return leads