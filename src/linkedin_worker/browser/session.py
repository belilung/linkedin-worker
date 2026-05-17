"""Playwright browser session management with cookie persistence."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from linkedin_worker.config import AppConfig
from linkedin_worker.utils.logging import log

COOKIES_FILE = "linkedin_cookies.json"


class LinkedInSession:
    """Manages Playwright browser lifecycle and LinkedIn session cookies."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.cookies_path = config.data_dir / "cookies" / COOKIES_FILE
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self, headless: bool | None = None) -> Page:
        """Launch browser and return a page with loaded cookies."""
        if headless is None:
            headless = self.config.session.headless

        # Ensure chromium deps are available
        import os
        deps_dir = os.path.expanduser("~/.local/lib/chromium-deps")
        if os.path.isdir(deps_dir):
            ld = os.environ.get("LD_LIBRARY_PATH", "")
            if deps_dir not in ld:
                os.environ["LD_LIBRARY_PATH"] = f"{deps_dir}:{ld}" if ld else deps_dir

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )

        # Comprehensive stealth: mask webdriver, plugins, languages, chrome runtime
        await self._context.add_init_script("""
            // Remove webdriver flag
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

            // Fake plugins array (real Chrome has these)
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
                    {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                    {name: 'Native Client', filename: 'internal-nacl-plugin'},
                ],
            });

            // Fake languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });

            // Fix chrome.runtime (automation leaves it undefined)
            if (!window.chrome) window.chrome = {};
            if (!window.chrome.runtime) window.chrome.runtime = {};

            // Remove Playwright-specific markers
            delete window.__playwright;
            delete window.__pw_manual;
        """)

        # Load saved cookies
        await self._load_cookies()

        self._page = await self._context.new_page()
        return self._page

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Session not started. Call start() first.")
        return self._page

    async def _load_cookies(self) -> None:
        """Load cookies from disk if they exist."""
        if self.cookies_path.exists():
            with open(self.cookies_path) as f:
                cookies = json.load(f)
            # Normalize cookies for Playwright compatibility
            SAME_SITE_MAP = {"no_restriction": "None", "lax": "Lax", "strict": "Strict"}
            cleaned = []
            for c in cookies:
                pw = {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/")}
                if "expirationDate" in c and c["expirationDate"]:
                    pw["expires"] = c["expirationDate"]
                ss = c.get("sameSite")
                if isinstance(ss, str):
                    pw["sameSite"] = SAME_SITE_MAP.get(ss.lower(), "Lax")
                else:
                    pw["sameSite"] = "Lax"
                if c.get("secure"):
                    pw["secure"] = True
                if c.get("httpOnly"):
                    pw["httpOnly"] = True
                cleaned.append(pw)
            await self._context.add_cookies(cleaned)
            log.info(f"Loaded {len(cleaned)} cookies from {self.cookies_path}")
        else:
            log.info("No saved cookies found.")

    async def save_cookies(self) -> None:
        """Save current browser cookies to disk."""
        if self._context is None:
            return
        cookies = await self._context.cookies()
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cookies_path, "w") as f:
            json.dump(cookies, f, indent=2)
        log.info(f"Saved {len(cookies)} cookies to {self.cookies_path}")

    async def is_logged_in(self, navigate: bool = True) -> bool:
        """Check if we're logged in to LinkedIn.

        Args:
            navigate: If True, navigate to /feed/ first. If False, check current page.
        """
        page = self.page

        if navigate:
            try:
                await page.goto(
                    "https://www.linkedin.com/feed/",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            except Exception:
                # If timeout, page may still have loaded partially
                log.warning("Navigation timeout, checking current state...")
            await page.wait_for_timeout(3000)

        url = page.url
        if "/login" in url or "/checkpoint" in url or "authwall" in url:
            # LinkedIn sometimes redirects through login for cookie validation
            # Wait a bit longer for the redirect chain to complete
            log.info("Login redirect detected, waiting for redirect chain...")
            await page.wait_for_timeout(8000)
            url = page.url
            if "/login" in url or "/checkpoint" in url or "authwall" in url:
                log.warning("Not logged in - redirected to login page.")
                return False

        # If we're on any linkedin.com page that's not login, check for nav/feed
        # Try multiple selectors - LinkedIn changes these frequently
        selectors = [
            'nav.global-nav',
            '[data-test-global-nav]',
            'div.feed-identity-module',
            'div.scaffold-layout',
            'header.global-nav',
            'img.global-nav__me-photo',
            'div.search-global-typeahead',
            '#global-nav',
            'li.global-nav__primary-item',
        ]

        for selector in selectors:
            try:
                el = await page.query_selector(selector)
                if el:
                    log.info(f"Successfully verified LinkedIn login (matched: {selector}).")
                    return True
            except Exception:
                continue

        # Fallback: if URL contains /feed or /mynetwork, we're probably logged in
        if any(path in url for path in ["/feed", "/mynetwork", "/messaging", "/in/"]):
            log.info(f"Verified login via URL: {url}")
            return True

        log.warning(f"Could not verify login state. Current URL: {url}")
        return False

    async def close(self) -> None:
        """Clean up browser resources."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
