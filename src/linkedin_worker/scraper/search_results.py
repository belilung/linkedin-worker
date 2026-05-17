"""Search results scraper using the SearchResultsPage page object."""

from __future__ import annotations

from playwright.async_api import Page

from linkedin_worker.browser.linkedin_pages import SearchResultsPage
from linkedin_worker.browser.rate_limiter import RateLimiter
from linkedin_worker.scraper.models import SearchResult


async def scrape_search_results(
    page: Page,
    rate_limiter: RateLimiter,
    search_url: str,
    max_pages: int = 10,
) -> list[SearchResult]:
    """Scrape LinkedIn search results across multiple pages."""
    search_page = SearchResultsPage(page, rate_limiter)
    return await search_page.get_all_results(search_url, max_pages=max_pages)
