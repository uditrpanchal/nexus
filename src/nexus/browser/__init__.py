"""
Headless Browser Access for NEXUS.

Embeds a headless browser (Playwright) to render and parse modern,
JavaScript-heavy SPAs and company reporting portals.

Replaces static HTTP request scraping when pages require JS execution.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional


class HeadlessBrowser:
    """
    Headless browser wrapper using Playwright.

    Usage:
        browser = HeadlessBrowser()
        html = await browser.fetch_rendered("https://example.com")
        await browser.close()
    """

    def __init__(self, headless: bool = True, timeout: int = 30_000):
        self._browser = None
        self._context = None
        self._headless = headless
        self._timeout = timeout
        self._playwright_installed = False

    async def _ensure_installed(self):
        """Lazy-install Playwright if needed."""
        if self._playwright_installed:
            return

        try:
            from playwright.async_api import async_playwright
            self._playwright = async_playwright
            self._playwright_installed = True
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Install with: pip install playwright && playwright install chromium"
            )

    async def start(self):
        """Start the browser."""
        await self._ensure_installed()
        if self._browser:
            return

        pw = await self._playwright.__aenter__()
        self._browser = await pw.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )

    async def close(self):
        """Close the browser and cleanup."""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None

    async def fetch_rendered(
        self,
        url: str,
        wait_until: str = "networkidle",
        wait_for_selector: Optional[str] = None,
        scroll: bool = True,
    ) -> dict[str, Any]:
        """
        Fetch a fully-rendered page with JS execution.

        Returns {url, title, html, text, status_code, duration_ms}
        """
        await self.start()
        if not self._context:
            raise RuntimeError("Browser context not available")

        start = time.time()
        page = await self._context.new_page()

        try:
            resp = await page.goto(
                url,
                wait_until=wait_until,
                timeout=self._timeout,
            )
            status_code = resp.status if resp else 0

            # Wait for specific element if specified
            if wait_for_selector:
                await page.wait_for_selector(
                    wait_for_selector,
                    timeout=self._timeout,
                )

            # Scroll to trigger lazy-loaded content
            if scroll:
                await page.evaluate("""
                    async () => {
                        await new Promise((resolve) => {
                            let totalHeight = 0;
                            const distance = 300;
                            const timer = setInterval(() => {
                                const scrollHeight = document.body.scrollHeight;
                                window.scrollBy(0, distance);
                                totalHeight += distance;
                                if (totalHeight >= scrollHeight || totalHeight > 5000) {
                                    clearInterval(timer);
                                    resolve();
                                }
                            }, 100);
                        });
                    }
                """)
                await asyncio.sleep(0.5)

            title = await page.title()
            html = await page.content()
            text = await page.evaluate("() => document.body.innerText")

            duration_ms = (time.time() - start) * 1000

            return {
                "url": url,
                "title": title,
                "html": html[:100_000],  # Cap at 100KB
                "text": text[:50_000],    # Cap at 50KB
                "status_code": status_code,
                "duration_ms": round(duration_ms),
            }
        finally:
            await page.close()

    async def extract_table(
        self,
        url: str,
        table_selector: str = "table",
    ) -> list[list[str]]:
        """
        Extract table data from a rendered page.

        Returns list of rows, each row is a list of cell text values.
        """
        page_result = await self.fetch_rendered(url, wait_until="domcontentloaded")

        # Use BeautifulSoup on the rendered HTML
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(page_result["html"], "html.parser")
            table = soup.select_one(table_selector)
            if not table:
                return []

            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            return rows
        except ImportError:
            return []

    async def screenshot(
        self,
        url: str,
        output_path: str,
        full_page: bool = True,
    ) -> str:
        """Take a screenshot of a rendered page."""
        await self.start()
        if not self._context:
            raise RuntimeError("Browser context not available")

        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=self._timeout)
            await page.screenshot(path=output_path, full_page=full_page)
            return output_path
        finally:
            await page.close()
