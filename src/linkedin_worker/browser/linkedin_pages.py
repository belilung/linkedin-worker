"""Page Object Models for LinkedIn pages.

Uses JavaScript-based extraction since LinkedIn obfuscates CSS class names.
"""

from __future__ import annotations

import random

from playwright.async_api import Page

from linkedin_worker.browser.rate_limiter import RateLimiter
from linkedin_worker.scraper.models import (
    ConnectionEntry,
    ContentSearchResult,
    PostData,
    ProfileData,
    SearchResult,
)
from linkedin_worker.utils.logging import log


def _parse_connected_date(text: str):
    """Parse LinkedIn 'Connected on ...' or 'Connected X days ago' text to datetime."""
    import re
    from datetime import datetime, timedelta

    if not text:
        return None

    text = text.strip()

    # "Connected on Feb 15, 2026" or "Connected on February 15, 2026"
    m = re.search(r'Connected on\s+(.+)', text)
    if m:
        date_str = m.group(1).strip()
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

    # "Connected 3 days ago"
    m = re.search(r'Connected\s+(\d+)\s+day', text)
    if m:
        return datetime.utcnow() - timedelta(days=int(m.group(1)))

    # "Connected 2 weeks ago"
    m = re.search(r'Connected\s+(\d+)\s+week', text)
    if m:
        return datetime.utcnow() - timedelta(weeks=int(m.group(1)))

    # "Connected 1 month ago"
    m = re.search(r'Connected\s+(\d+)\s+month', text)
    if m:
        return datetime.utcnow() - timedelta(days=int(m.group(1)) * 30)

    # "Connected today" or "Connected yesterday"
    if 'today' in text.lower():
        return datetime.utcnow()
    if 'yesterday' in text.lower():
        return datetime.utcnow() - timedelta(days=1)

    return None


# --- JS extraction scripts ---

_EXTRACT_SEARCH_RESULTS = """() => {
    // LinkedIn wraps search results in div[role="list"] > child divs
    const listContainer = document.querySelector('div[role="list"]');
    if (!listContainer) return [];

    const results = [];
    const seen = new Set();

    for (const child of listContainer.children) {
        const links = child.querySelectorAll('a[href*="/in/"]');
        if (links.length === 0) continue;

        // Get unique profile URL from the first link
        let profileUrl = '';
        for (const link of links) {
            const href = link.href.split('?')[0].replace(/\\/$/, '');
            if (href.includes('/in/')) {
                profileUrl = href;
                break;
            }
        }
        if (!profileUrl || seen.has(profileUrl)) continue;
        seen.add(profileUrl);

        // Extract text lines from the card
        const lines = child.innerText.split('\\n')
            .map(l => l.trim())
            .filter(l => l && l !== '•');

        // First meaningful line is typically the name (may include emoji/badges)
        let name = '';
        let headline = '';
        let degree = '';

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];

            // Connection degree
            if (/^\\d+(st|nd|rd)$/.test(line) || line === '1st' || line === '2nd' || line === '3rd') {
                degree = line;
                continue;
            }

            // Skip action buttons and metadata
            if (['Message', 'Connect', 'Follow', 'Pending'].includes(line)) continue;
            if (line.includes('mutual connection')) continue;
            if (line.includes('follower')) continue;

            // First non-skipped line is the name
            if (!name) {
                // Clean up degree marker that may be inline: "Name • 1st"
                const parts = line.split(/\\s*•\\s*/);
                name = parts[0].trim();
                if (parts[1] && /\\d+(st|nd|rd)/.test(parts[1])) {
                    degree = parts[1].trim();
                }
                continue;
            }

            // Second non-skipped line is the headline
            if (!headline) {
                headline = line;
                break;
            }
        }

        if (name && profileUrl) {
            results.push({
                name: name,
                profileUrl: profileUrl,
                headline: headline || '',
                degree: degree || '',
            });
        }
    }
    return results;
}"""


_EXTRACT_CONNECTIONS = """() => {
    const main = document.querySelector('main');
    if (!main) return [];

    const results = [];
    const seen = new Set();

    // Find all profile links and walk up to their card containers
    const allLinks = main.querySelectorAll('a[href*="/in/"]');

    for (const link of allLinks) {
        const href = link.href.split('?')[0].replace(/\\/$/, '');
        if (!href.includes('/in/') || seen.has(href)) continue;

        // Walk up to find the card: a container with both a profile link and "Message" button
        let card = link;
        for (let i = 0; i < 8; i++) {
            card = card.parentElement;
            if (!card || card === main) { card = null; break; }
            const text = card.innerText || '';
            if (text.includes('Message') && card.querySelector('a[href*="/in/"]')) {
                // Make sure it's not too big (not the whole page)
                if (card.querySelectorAll('a[href*="/in/"]').length <= 3) break;
            }
        }
        if (!card) continue;

        seen.add(href);

        const lines = card.innerText.split('\\n')
            .map(l => l.trim())
            .filter(l => l && l !== 'Message' && !l.startsWith('Connected on') && l !== '…');

        const name = lines[0] || '';
        const headline = lines[1] || '';

        if (name) {
            results.push({
                name: name,
                profileUrl: href,
                headline: headline,
            });
        }
    }
    return results;
}"""


_EXTRACT_PROFILE = """() => {
    const getText = (sel) => {
        const el = document.querySelector(sel);
        return el ? el.innerText.trim() : '';
    };

    // Name - try h1 first
    let name = getText('h1');

    // Headline - usually the div right after h1
    let headline = '';
    const h1 = document.querySelector('h1');
    if (h1) {
        // Walk siblings/parent to find headline
        let next = h1.parentElement?.nextElementSibling;
        if (next) headline = next.innerText?.trim() || '';
    }

    // Location
    let location = '';
    // Look for a span with location info (usually contains city, state/country)
    const spans = document.querySelectorAll('main span');
    for (const span of spans) {
        const text = span.innerText?.trim() || '';
        if (text && (text.includes(',') || text.includes('Area')) &&
            !text.includes('connection') && !text.includes('follower') &&
            text.length < 100 && text.length > 3) {
            // Likely a location
            const parent = span.closest('section, div');
            if (parent && parent.querySelector('h1')) {
                location = text;
                break;
            }
        }
    }

    // About section
    let about = '';
    const aboutSection = document.querySelector('#about');
    if (aboutSection) {
        // The actual text is in a sibling/next container
        let container = aboutSection.closest('section') || aboutSection.parentElement;
        if (container) {
            // Remove the "About" header text
            const fullText = container.innerText?.trim() || '';
            about = fullText.replace(/^About\\s*/, '').trim();
        }
    }

    // Experience section
    const experience = [];
    const expSection = document.querySelector('#experience');
    if (expSection) {
        let container = expSection.closest('section') || expSection.parentElement?.parentElement;
        if (container) {
            const items = container.querySelectorAll('li');
            for (const item of Array.from(items).slice(0, 5)) {
                const spans = item.querySelectorAll('span[aria-hidden="true"]');
                const texts = Array.from(spans).map(s => s.innerText.trim()).filter(t => t);
                if (texts.length >= 1) {
                    experience.push({
                        title: texts[0] || '',
                        company: texts[1] || '',
                    });
                }
            }
        }
    }

    return {
        name: name,
        headline: headline,
        location: location,
        about: about.substring(0, 1000),
        experience: experience,
        currentCompany: experience.length > 0 ? (experience[0].company || '') : '',
    };
}"""


_EXTRACT_RECENT_CONNECTIONS = """() => {
    const main = document.querySelector('main');
    if (!main) return [];

    const results = [];
    const seen = new Set();

    const allLinks = main.querySelectorAll('a[href*="/in/"]');

    for (const link of allLinks) {
        const href = link.href.split('?')[0].replace(/\\/$/, '');
        if (!href.includes('/in/') || seen.has(href)) continue;

        // Walk up to find the card container
        let card = link;
        for (let i = 0; i < 8; i++) {
            card = card.parentElement;
            if (!card || card === main) { card = null; break; }
            const text = card.innerText || '';
            if (text.includes('Message') && card.querySelector('a[href*="/in/"]')) {
                if (card.querySelectorAll('a[href*="/in/"]').length <= 3) break;
            }
        }
        if (!card) continue;

        seen.add(href);

        const fullText = card.innerText || '';
        const lines = fullText.split('\\n').map(l => l.trim()).filter(l => l);

        // Extract "Connected on" or "Connected X ago" date text
        let connectedDate = '';
        for (const line of lines) {
            if (line.startsWith('Connected')) {
                connectedDate = line;
                break;
            }
        }

        const cleanLines = lines.filter(l =>
            l && l !== 'Message' && !l.startsWith('Connected') && l !== '…'
        );

        const name = cleanLines[0] || '';
        const headline = cleanLines[1] || '';

        if (name) {
            results.push({
                name: name,
                profileUrl: href,
                headline: headline,
                connectedDate: connectedDate,
            });
        }
    }
    return results;
}"""


_COUNT_CONNECTIONS_ON_PAGE = """() => {
    const main = document.querySelector('main');
    if (!main) return 0;
    const links = main.querySelectorAll('a[href*="/in/"]');
    const seen = new Set();
    for (const l of links) {
        const href = l.href.split('?')[0].replace(/\\/$/, '');
        if (href.includes('/in/')) seen.add(href);
    }
    return seen.size;
}"""


_EXTRACT_CONTENT_SEARCH_RESULTS = """() => {
    const results = [];
    const seen = new Set();
    const main = document.querySelector('main') || document.body;
    const updates = main.querySelectorAll('div.feed-shared-update-v2');

    for (const upd of updates) {
        // Author profile URL
        const profileLink = upd.querySelector('a[href*="/in/"]');
        if (!profileLink) continue;
        const profileUrl = profileLink.href.split('?')[0].replace(/\\/$/, '');
        if (seen.has(profileUrl)) continue;
        seen.add(profileUrl);

        // Author name and headline from aria-hidden spans
        const spans = Array.from(upd.querySelectorAll('span[aria-hidden="true"]'))
            .map(s => s.innerText.trim())
            .filter(t => t && t.length < 200);
        const authorName = spans[0] || '';
        // spans[1] is usually "• 2nd" or "• Following", so headline is spans[2]
        const authorHeadline = spans.length > 2 ? spans[2] : '';

        // Post text from .break-words
        const textEl = upd.querySelector('.break-words');
        const postText = textEl ? textEl.innerText.trim() : '';

        // Post URL from data-urn
        const urn = upd.getAttribute('data-urn') || '';
        let postUrl = '';
        if (urn) {
            postUrl = 'https://www.linkedin.com/feed/update/' + urn + '/';
        }

        if (authorName && (postText || profileUrl)) {
            results.push({
                postUrl: postUrl,
                postText: postText.substring(0, 1000),
                authorName: authorName,
                authorProfileUrl: profileUrl,
                authorHeadline: authorHeadline,
            });
        }
    }
    return results;
}"""


_EXTRACT_ACTIVITY_POSTS = """() => {
    const results = [];
    const main = document.querySelector('main') || document.body;

    // Activity page lists posts as feed items
    const items = main.querySelectorAll(
        'div.feed-shared-update-v2, div[data-urn], article'
    );

    // Fallback: just grab all substantial text blocks
    const containers = items.length > 0
        ? items
        : main.querySelectorAll('div.occludable-update');

    for (const item of Array.from(containers).slice(0, 10)) {
        const fullText = item.innerText || '';
        if (fullText.length < 20) continue;

        // Find post permalink
        let postUrl = '';
        const postLinks = item.querySelectorAll(
            'a[href*="/feed/update/"], a[href*="/posts/"]'
        );
        if (postLinks.length > 0) {
            postUrl = postLinks[0].href.split('?')[0];
        }

        // Find timestamp text
        let timestamp = '';
        const timeEl = item.querySelector('time, span.feed-shared-actor__sub-description');
        if (timeEl) timestamp = timeEl.innerText?.trim() || '';

        // Extract main post text (skip UI elements)
        const lines = fullText.split('\\n')
            .map(l => l.trim())
            .filter(l => l && l.length > 5
                && !['Like', 'Comment', 'Repost', 'Send', 'Share'].includes(l)
                && !/^\\d+ (like|comment|repost)/.test(l));

        // Combine meaningful lines for the post text
        const postText = lines.slice(0, 20).join(' ').substring(0, 1000);

        results.push({
            postUrl: postUrl,
            text: postText,
            timestamp: timestamp,
        });
    }
    return results;
}"""


class ContentSearchPage:
    """Page object for LinkedIn Content Search results (/search/results/content/)."""

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    async def get_all_results(
        self, keywords: str, max_pages: int = 5, geo_urn: str = "",
    ) -> list[ContentSearchResult]:
        """Search for content posts and extract authors + post text."""
        from urllib.parse import quote
        results: list[ContentSearchResult] = []
        seen_urls: set[str] = set()

        geo_suffix = f'&geoUrn=%5B%22{geo_urn}%22%5D' if geo_urn else ""

        for page_num in range(1, max_pages + 1):
            url = (
                f"https://www.linkedin.com/search/results/content/"
                f"?keywords={quote(keywords)}&page={page_num}{geo_suffix}"
            )
            log.info(f"Content search page {page_num} for '{keywords}'...")

            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self.page.wait_for_timeout(4000)

            # Scroll to trigger lazy loading
            for _ in range(3):
                await self.page.evaluate(
                    "window.scrollBy(0, window.innerHeight)"
                )
                await self.page.wait_for_timeout(1500)

            raw = await self.page.evaluate(_EXTRACT_CONTENT_SEARCH_RESULTS)
            new_results = []
            for item in raw:
                profile_url = item.get("authorProfileUrl", "")
                if not profile_url or profile_url in seen_urls:
                    continue
                seen_urls.add(profile_url)
                new_results.append(ContentSearchResult(
                    post_url=item.get("postUrl", ""),
                    post_text=item.get("postText", ""),
                    author_name=item.get("authorName", ""),
                    author_profile_url=profile_url,
                    author_headline=item.get("authorHeadline", ""),
                ))

            if not new_results:
                log.info(f"No new content results on page {page_num}, stopping.")
                break

            results.extend(new_results)
            log.info(f"  Found {len(new_results)} content results on page {page_num}.")
            await self.rate_limiter.wait()

        return results


class ActivityPage:
    """Page object for a user's recent activity (/in/username/recent-activity/all/)."""

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    async def get_recent_posts(
        self, profile_url: str, gdc_keywords: list[str] | None = None,
    ) -> list[PostData]:
        """Navigate to user's activity page and extract recent posts."""
        # Build activity URL from profile URL
        clean_url = profile_url.rstrip("/")
        activity_url = f"{clean_url}/recent-activity/all/"

        log.info(f"Scraping activity: {activity_url}")
        await self.page.goto(activity_url, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(3000)

        # Scroll down a bit to load posts
        for _ in range(2):
            await self.page.evaluate("window.scrollBy(0, window.innerHeight)")
            await self.page.wait_for_timeout(1500)

        raw = await self.page.evaluate(_EXTRACT_ACTIVITY_POSTS)

        if gdc_keywords is None:
            gdc_keywords = ["gdc", "game developers conference"]

        # Extract author name from profile URL
        author_name = profile_url.rstrip("/").split("/")[-1].replace("-", " ").title()

        posts = []
        for item in raw:
            text = item.get("text", "")
            is_gdc = any(kw.lower() in text.lower() for kw in gdc_keywords)
            posts.append(PostData(
                post_url=item.get("postUrl", ""),
                author_name=author_name,
                author_profile_url=profile_url,
                text=text,
                is_gdc_related=is_gdc,
                timestamp_text=item.get("timestamp", ""),
            ))

        log.info(f"  Found {len(posts)} posts, "
                 f"{sum(1 for p in posts if p.is_gdc_related)} GDC-related.")
        return posts


class CommentComposer:
    """Page object for posting a comment on a LinkedIn post."""

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    async def post_comment(self, post_url: str, comment_text: str) -> bool:
        """Navigate to a post and leave a comment.

        If post_url is empty, assumes the post is already visible on the
        current page (e.g. the activity feed) and tries to comment on the
        first post.
        """
        if post_url:
            log.info(f"Navigating to post: {post_url}")
            await self.page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
            await self.page.wait_for_timeout(3000)

        # Click the "Comment" button to open the comment box
        comment_opened = await self.page.evaluate("""() => {
            // Find the social action bar Comment button (aria-label exactly "Comment")
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                const label = btn.getAttribute('aria-label') || '';
                const cls = btn.className || '';
                if (label === 'Comment'
                    && cls.includes('social-actions-button')
                    && btn.offsetParent !== null) {
                    btn.scrollIntoView({block: 'center'});
                    btn.click();
                    return true;
                }
            }
            // Fallback: text-based
            for (const btn of buttons) {
                const text = btn.innerText?.trim() || '';
                const label = btn.getAttribute('aria-label') || '';
                if (text === 'Comment' && !label.includes('comments')
                    && btn.offsetParent !== null) {
                    btn.scrollIntoView({block: 'center'});
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")

        if not comment_opened:
            log.warning("Could not find Comment button.")
            return False

        await self.page.wait_for_timeout(2000)

        # Find the comment textbox
        try:
            comment_box = await self.page.wait_for_selector(
                'div[role="textbox"][contenteditable="true"]',
                timeout=8000,
            )
        except Exception:
            log.warning("Comment textbox did not appear.")
            return False

        if not comment_box:
            return False

        # Focus and type
        await comment_box.evaluate("el => { el.scrollIntoView({block: 'center'}); }")
        await self.page.wait_for_timeout(300)
        await comment_box.evaluate("el => el.focus()")
        await self.page.wait_for_timeout(300)

        typing_delay = await self.rate_limiter.type_delay()
        await comment_box.type(comment_text, delay=typing_delay)
        await self.rate_limiter.wait_short()

        # Find and click the submit button for the comment
        # LinkedIn labels this button "Comment" (not "Post" or "Submit")
        # with class containing "comments-comment-box__submit-button"
        posted = await self.page.evaluate("""() => {
            // Primary: find by submit button class
            const submit = document.querySelector(
                'button[class*="comments-comment-box__submit-button"]'
            );
            if (submit && !submit.disabled && submit.offsetParent !== null) {
                submit.click();
                return true;
            }
            // Fallback: find button with text "Comment" inside comment form
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                const text = btn.innerText?.trim() || '';
                const cls = btn.className || '';
                if (text === 'Comment' && cls.includes('artdeco-button--primary')
                    && btn.offsetParent !== null && !btn.disabled) {
                    btn.click();
                    return true;
                }
            }
            // Last fallback: Post/Submit
            for (const btn of buttons) {
                const text = btn.innerText?.trim() || '';
                if ((text === 'Post' || text === 'Submit')
                    && btn.offsetParent !== null && !btn.disabled) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")

        if not posted:
            log.warning("Could not find submit button for comment.")
            return False

        await self.page.wait_for_timeout(2000)
        log.info("Comment posted successfully.")
        return True

    async def comment_on_activity_post(
        self, post_index: int, comment_text: str
    ) -> bool:
        """Comment on the Nth post on the currently loaded activity page.

        This avoids navigating away — useful when we're already on the
        activity page and want to comment on the first visible post.
        """
        # Click the Comment button on the Nth post
        comment_opened = await self.page.evaluate(f"""(targetIndex) => {{
            let idx = 0;
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {{
                const text = btn.innerText?.trim() || '';
                const label = btn.getAttribute('aria-label') || '';
                if ((text === 'Comment' || label.includes('Comment'))
                    && btn.offsetParent !== null
                    && !label.includes('comments')) {{
                    if (idx === targetIndex) {{
                        btn.scrollIntoView({{block: 'center'}});
                        btn.click();
                        return true;
                    }}
                    idx++;
                }}
            }}
            return false;
        }}""", post_index)

        if not comment_opened:
            log.warning(f"Could not find Comment button for post #{post_index}.")
            return False

        await self.page.wait_for_timeout(2000)

        # Find the comment textbox (get the last one, as it's the most recently opened)
        textboxes = await self.page.query_selector_all(
            'div[role="textbox"][contenteditable="true"]'
        )
        if not textboxes:
            log.warning("Comment textbox did not appear.")
            return False
        comment_box = textboxes[-1]

        await comment_box.evaluate("el => { el.scrollIntoView({block: 'center'}); }")
        await self.page.wait_for_timeout(300)
        await comment_box.evaluate("el => el.focus()")
        await self.page.wait_for_timeout(300)

        typing_delay = await self.rate_limiter.type_delay()
        await comment_box.type(comment_text, delay=typing_delay)
        await self.rate_limiter.wait_short()

        # Submit
        posted = await self.page.evaluate("""() => {
            const submit = document.querySelector(
                'button[class*="comments-comment-box__submit-button"]'
            );
            if (submit && !submit.disabled && submit.offsetParent !== null) {
                submit.click();
                return true;
            }
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                const text = btn.innerText?.trim() || '';
                const cls = btn.className || '';
                if (text === 'Comment' && cls.includes('artdeco-button--primary')
                    && btn.offsetParent !== null && !btn.disabled) {
                    btn.click();
                    return true;
                }
            }
            for (const btn of buttons) {
                const text = btn.innerText?.trim() || '';
                if ((text === 'Post' || text === 'Submit')
                    && btn.offsetParent !== null && !btn.disabled) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")

        if not posted:
            log.warning("Could not find submit button for comment.")
            return False

        await self.page.wait_for_timeout(2000)
        log.info(f"Comment posted on post #{post_index}.")
        return True


class SearchResultsPage:
    """Page object for LinkedIn People Search results."""

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    async def get_all_results(
        self, search_url: str, max_pages: int = 10
    ) -> list[SearchResult]:
        """Scrape all search result pages up to max_pages."""
        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for page_num in range(1, max_pages + 1):
            separator = "&" if "?" in search_url else "?"
            url = f"{search_url}{separator}page={page_num}"
            log.info(f"Scraping search page {page_num}...")

            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self.page.wait_for_timeout(4000)

            # Scroll down to trigger lazy loading
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.page.wait_for_timeout(2000)

            page_results = await self._extract_results()
            new_results = [r for r in page_results if r.profile_url not in seen_urls]
            if not new_results:
                log.info(f"No new results on page {page_num}, stopping pagination.")
                break

            for r in new_results:
                seen_urls.add(r.profile_url)
            results.extend(new_results)
            log.info(f"  Found {len(new_results)} results on page {page_num}.")
            await self.rate_limiter.wait()

        return results

    async def _extract_results(self) -> list[SearchResult]:
        """Extract search results from the current page via JS."""
        raw = await self.page.evaluate(_EXTRACT_SEARCH_RESULTS)
        results = []
        for item in raw:
            results.append(SearchResult(
                name=item["name"],
                profile_url=item["profileUrl"],
                headline=item.get("headline", ""),
                connection_degree=item.get("degree", ""),
            ))
        return results


class ConnectionsPage:
    """Page object for LinkedIn Connections list."""

    CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    async def scroll_and_load_all(self) -> list[ConnectionEntry]:
        """Scroll through the entire connections list and extract all entries."""
        await self.page.goto(self.CONNECTIONS_URL, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(4000)

        prev_count = 0
        stale_rounds = 0

        while stale_rounds < 5:
            # Scroll to bottom
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.rate_limiter.wait_short()

            # Try clicking any "Show more" button
            try:
                show_more = await self.page.query_selector(
                    'button:has-text("Show more results"), '
                    'button:has-text("Show more")'
                )
                if show_more and await show_more.is_visible():
                    await show_more.click()
                    await self.rate_limiter.wait_short()
            except Exception:
                pass

            current_count = await self.page.evaluate(_COUNT_CONNECTIONS_ON_PAGE)

            if current_count == prev_count:
                stale_rounds += 1
            else:
                stale_rounds = 0
                prev_count = current_count

            if current_count % 100 == 0 or stale_rounds > 0:
                log.info(f"Connections loaded: {current_count}")

        return await self._extract_connections()

    async def get_recently_added(self, max_age_days: int = 14) -> list[ConnectionEntry]:
        """Load connections sorted by recently added and return those within max_age_days.

        LinkedIn shows "Connected on MMM DD, YYYY" or "Connected X days ago" for each.
        We scroll until we pass the cutoff date, then stop.
        """
        url = f"{self.CONNECTIONS_URL}?sortCriteria=RECENTLY_ADDED"
        for attempt in range(3):
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as e:
                if attempt < 2:
                    log.warning(f"Navigation attempt {attempt+1} failed: {e}. Retrying...")
                    await self.page.wait_for_timeout(5000)
                else:
                    raise
        await self.page.wait_for_timeout(4000)

        import re
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        all_entries: list[ConnectionEntry] = []
        seen_urls: set[str] = set()
        stale_rounds = 0
        prev_count = 0
        found_old = False

        while stale_rounds < 5 and not found_old:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.rate_limiter.wait_short()

            # Click "Show more" if present
            try:
                show_more = await self.page.query_selector(
                    'button:has-text("Show more results"), '
                    'button:has-text("Show more")'
                )
                if show_more and await show_more.is_visible():
                    await show_more.click()
                    await self.rate_limiter.wait_short()
            except Exception:
                pass

            raw = await self.page.evaluate(_EXTRACT_RECENT_CONNECTIONS)
            current_count = len(raw)

            if current_count == prev_count:
                stale_rounds += 1
            else:
                stale_rounds = 0
                prev_count = current_count

            # Process all results so far
            for item in raw:
                purl = item["profileUrl"]
                if not purl or "/in/" not in purl or purl in seen_urls:
                    continue
                seen_urls.add(purl)

                conn_date_str = item.get("connectedDate", "")
                connected_dt = _parse_connected_date(conn_date_str)

                if connected_dt and connected_dt < cutoff:
                    found_old = True
                    log.info(f"Reached connection older than {max_age_days} days, stopping scroll.")
                    break

                all_entries.append(ConnectionEntry(
                    name=item["name"],
                    profile_url=purl,
                    headline=item.get("headline", ""),
                ))

            log.info(f"Recent connections loaded: {len(all_entries)}")

        log.info(f"Found {len(all_entries)} connections added in last {max_age_days} days.")
        return all_entries

    async def _extract_connections(self) -> list[ConnectionEntry]:
        """Extract connection entries via JS."""
        raw = await self.page.evaluate(_EXTRACT_CONNECTIONS)
        entries = []
        for item in raw:
            if item["profileUrl"] and "/in/" in item["profileUrl"]:
                entries.append(ConnectionEntry(
                    name=item["name"],
                    profile_url=item["profileUrl"],
                    headline=item.get("headline", ""),
                ))
        log.info(f"Extracted {len(entries)} connections.")
        return entries


class ProfilePage:
    """Page object for a LinkedIn profile."""

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    async def scrape(self, profile_url: str) -> ProfileData:
        """Navigate to profile and extract structured data via JS."""
        await self.page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(3000)

        raw = await self.page.evaluate(_EXTRACT_PROFILE)

        return ProfileData(
            name=raw.get("name", ""),
            profile_url=profile_url,
            headline=raw.get("headline", ""),
            location=raw.get("location", ""),
            about=raw.get("about", ""),
            current_company=raw.get("currentCompany", ""),
            experience=raw.get("experience", []),
        )

    async def click_connect_no_note(self) -> bool:
        """Click the Connect button on the current profile page and send without a note.

        Handles multiple scenarios:
        1. Direct "Connect" button on profile
        2. "Connect" inside "More..." dropdown
        3. Modal asking "Add a note?" → click "Send without a note"
        """
        connected = False

        # Strategy 1: direct Connect button (aria-label="Invite ... to connect")
        try:
            btn = await self.page.query_selector(
                'button[aria-label*="to connect"], '
                'button[aria-label*="Connect with"]'
            )
            if btn and await btn.is_visible():
                await btn.evaluate(
                    "el => { el.scrollIntoView({block: 'center'}); el.click(); }"
                )
                connected = True
        except Exception:
            pass

        # Strategy 2: button with text "Connect" (primary action)
        if not connected:
            try:
                connected = await self.page.evaluate("""() => {
                    for (const btn of document.querySelectorAll('button')) {
                        if (btn.innerText.trim() === 'Connect'
                            && btn.offsetParent !== null) {
                            btn.scrollIntoView({block: 'center'});
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }""")
            except Exception:
                pass

        # Strategy 3: open "More" dropdown first, then find Connect
        if not connected:
            try:
                more_clicked = await self.page.evaluate("""() => {
                    for (const btn of document.querySelectorAll('button')) {
                        const label = btn.getAttribute('aria-label') || '';
                        const text = btn.innerText.trim();
                        if ((text === 'More' || label.includes('More actions'))
                            && btn.offsetParent !== null) {
                            btn.scrollIntoView({block: 'center'});
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }""")

                if more_clicked:
                    await self.page.wait_for_timeout(1500)
                    # Now find Connect in the dropdown
                    connected = await self.page.evaluate("""() => {
                        // Look in dropdown/popover menus
                        for (const item of document.querySelectorAll(
                            'div[role="listbox"] span, div[role="menu"] span, '
                            + 'div.artdeco-dropdown__content span'
                        )) {
                            if (item.innerText?.trim() === 'Connect'
                                && item.offsetParent !== null) {
                                item.click();
                                return true;
                            }
                        }
                        return false;
                    }""")
            except Exception:
                pass

        if not connected:
            log.warning("Could not find Connect button.")
            return False

        await self.page.wait_for_timeout(2000)

        # Handle the "Add a note?" modal → click "Send without a note"
        try:
            send_no_note = await self.page.evaluate("""() => {
                for (const btn of document.querySelectorAll('button')) {
                    const label = btn.getAttribute('aria-label') || '';
                    const text = btn.innerText?.trim() || '';
                    if ((text === 'Send without a note' || text === 'Send now'
                         || label === 'Send without a note' || label === 'Send now')
                        && btn.offsetParent !== null) {
                        btn.click();
                        return true;
                    }
                }
                // Maybe there's a "Send" button directly
                for (const btn of document.querySelectorAll('button')) {
                    const text = btn.innerText?.trim() || '';
                    if (text === 'Send' && btn.offsetParent !== null
                        && (btn.className || '').includes('artdeco-button--primary')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""")

            if send_no_note:
                await self.page.wait_for_timeout(1500)
                log.info("Connect request sent (without note).")
                return True
            else:
                # No modal appeared — connect may have been sent directly
                log.info("Connect request sent (direct, no modal).")
                return True
        except Exception as e:
            log.warning(f"Error handling connect modal: {e}")
            return False


class MessagingOverlay:
    """Page object for the LinkedIn messaging compose overlay.

    Simple flow: open profile → click Message → type → send → Escape to close → next.
    Safety checks verify recipient name and message name match before sending.
    """

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    async def _close_overlay(self) -> None:
        """Close the messaging overlay by pressing Escape."""
        for _ in range(3):
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(400)

    async def open_conversation(self, profile_url: str, expected_name: str) -> bool:
        """Navigate to profile and open the message compose box."""
        await self.page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(3000)

        # Extract first name from the profile h1
        first_name = await self.page.evaluate("""() => {
            const h1 = document.querySelector('h1');
            if (!h1) return '';
            return h1.innerText.trim().split(/\\s+/)[0] || '';
        }""")

        # SAFETY: verify the profile page matches the expected person
        if first_name and expected_name:
            expected_first = expected_name.split()[0].lower()
            if first_name.lower() != expected_first:
                log.error(
                    f"SAFETY ABORT: profile shows '{first_name}' but expected "
                    f"'{expected_name}'. Wrong profile!"
                )
                return False

        clicked = False

        # Strategy 1: exact aria-label "Message FirstName"
        if first_name:
            try:
                btn = await self.page.query_selector(
                    f'button[aria-label="Message {first_name}"]'
                )
                if btn and await btn.is_visible():
                    await btn.evaluate(
                        "el => { el.scrollIntoView({block: 'center'}); el.click(); }"
                    )
                    clicked = True
            except Exception:
                pass

        # Strategy 2: any button with aria-label starting with "Message "
        if not clicked:
            try:
                btn = await self.page.query_selector('button[aria-label^="Message "]')
                if btn and await btn.is_visible():
                    await btn.evaluate(
                        "el => { el.scrollIntoView({block: 'center'}); el.click(); }"
                    )
                    clicked = True
            except Exception:
                pass

        # Strategy 3: JS — primary action button with "Message" text
        if not clicked:
            try:
                clicked = await self.page.evaluate("""() => {
                    for (const btn of document.querySelectorAll('button')) {
                        if (btn.innerText.trim() === 'Message'
                            && (btn.className || '').includes('artdeco-button--primary')
                            && btn.offsetParent !== null) {
                            btn.scrollIntoView({block: 'center'});
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }""")
            except Exception:
                pass

        if not clicked:
            log.warning(f"No message button found on {profile_url}")
            return False

        await self.page.wait_for_timeout(2000)

        # Wait for compose box
        try:
            await self.page.wait_for_selector(
                'div[role="textbox"][contenteditable="true"], '
                'div.msg-form__contenteditable',
                timeout=8000,
            )
            return True
        except Exception:
            log.warning("Message compose box did not appear.")
            return False

    async def type_and_send(self, message: str, expected_first_name: str) -> bool:
        """Type a message and send it. Close the overlay afterwards."""
        try:
            # SAFETY: message must contain the expected name
            if expected_first_name and expected_first_name.lower() not in message.lower():
                log.error(
                    f"SAFETY ABORT: message does not contain '{expected_first_name}'. "
                    f"Message: '{message[:60]}'"
                )
                await self._close_overlay()
                return False

            # Get the LAST compose box (the most recently opened one)
            composes = await self.page.query_selector_all(
                'div[role="textbox"][contenteditable="true"], '
                'div.msg-form__contenteditable'
            )
            if not composes:
                log.warning("No compose box found.")
                return False
            compose = composes[-1]

            # Focus and type using keyboard (avoids element.type() 30s timeout)
            await compose.evaluate("el => { el.scrollIntoView({block: 'center'}); }")
            await self.page.wait_for_timeout(300)
            await compose.click()
            await self.page.wait_for_timeout(500)

            # Type via page.keyboard in chunks to avoid timeouts
            chunk_size = 50
            for i in range(0, len(message), chunk_size):
                chunk = message[i:i + chunk_size]
                await self.page.keyboard.type(chunk, delay=random.randint(30, 70))
                await self.page.wait_for_timeout(random.randint(200, 500))
            await self.rate_limiter.wait_short()

            # Find and click Send button in the same container as our compose box
            sent = await compose.evaluate("""(el) => {
                let container = el;
                for (let i = 0; i < 15; i++) {
                    container = container.parentElement;
                    if (!container) break;
                    const sendBtn = container.querySelector('button.msg-form__send-button');
                    if (sendBtn) { sendBtn.click(); return true; }
                    for (const b of container.querySelectorAll('button')) {
                        if (b.innerText.trim() === 'Send' && b.offsetParent !== null) {
                            b.click();
                            return true;
                        }
                    }
                }
                return false;
            }""")

            if not sent:
                log.warning("Send button not found.")
                await self._close_overlay()
                return False

            await self.page.wait_for_timeout(2000)

            # Close the overlay with Escape so next contact gets a clean window
            await self._close_overlay()

            log.info("Message sent successfully.")
            return True
        except Exception as e:
            log.error(f"Error sending message: {e}")
            try:
                await self._close_overlay()
            except Exception:
                pass
            return False
