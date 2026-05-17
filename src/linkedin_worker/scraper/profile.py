"""Profile scraper using the ProfilePage page object."""

from __future__ import annotations

from playwright.async_api import Page

from linkedin_worker.browser.linkedin_pages import ProfilePage
from linkedin_worker.browser.rate_limiter import RateLimiter
from linkedin_worker.scraper.models import ProfileData


async def scrape_profile(
    page: Page,
    rate_limiter: RateLimiter,
    profile_url: str,
) -> ProfileData:
    """Scrape a full LinkedIn profile."""
    profile_page = ProfilePage(page, rate_limiter)
    return await profile_page.scrape(profile_url)
