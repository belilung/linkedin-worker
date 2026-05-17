"""DM sending via Playwright."""

from __future__ import annotations

from playwright.async_api import Page

from linkedin_worker.browser.linkedin_pages import MessagingOverlay
from linkedin_worker.browser.rate_limiter import RateLimiter
from linkedin_worker.utils.logging import log


class MessageSender:
    """Sends LinkedIn DMs using the messaging overlay."""

    def __init__(self, rate_limiter: RateLimiter):
        self.rate_limiter = rate_limiter

    async def send_message(
        self, page: Page, profile_url: str, message: str,
        expected_name: str = "",
    ) -> bool:
        """Open a conversation and send a message to the given profile.

        Args:
            page: Playwright page
            profile_url: LinkedIn profile URL
            message: Message text to send
            expected_name: Full name of recipient (for safety verification)
        """
        overlay = MessagingOverlay(page, self.rate_limiter)

        first_name = expected_name.split()[0] if expected_name else ""

        log.info(f"Opening message compose for {profile_url}...")
        opened = await overlay.open_conversation(profile_url, expected_name=expected_name)
        if not opened:
            log.warning(f"Could not open message compose for {profile_url}")
            return False

        await self.rate_limiter.wait_short()

        success = await overlay.type_and_send(message, expected_first_name=first_name)
        if success:
            log.info(f"Message sent to {profile_url}")
        else:
            log.warning(f"Failed to send message to {profile_url}")

        return success
