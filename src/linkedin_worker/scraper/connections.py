"""Connections list scraper using the ConnectionsPage page object."""

from __future__ import annotations

from playwright.async_api import Page

from linkedin_worker.browser.linkedin_pages import ConnectionsPage
from linkedin_worker.browser.rate_limiter import RateLimiter
from linkedin_worker.scraper.models import ConnectionEntry


async def scrape_connections(
    page: Page,
    rate_limiter: RateLimiter,
) -> list[ConnectionEntry]:
    """Scrape the user's full connections list via infinite scroll."""
    conn_page = ConnectionsPage(page, rate_limiter)
    return await conn_page.scroll_and_load_all()
