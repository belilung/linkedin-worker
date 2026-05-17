"""CLI entry point and pipeline orchestration."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table

from linkedin_worker.browser.linkedin_pages import (
    ActivityPage,
    CommentComposer,
    ConnectionsPage,
    ContentSearchPage,
    ProfilePage,
    SearchResultsPage,
)
from linkedin_worker.browser.rate_limiter import RateLimiter
from linkedin_worker.browser.session import LinkedInSession
from linkedin_worker.config import AppConfig, ICPConfig, load_config
from linkedin_worker.messaging.comment_generator import CommentGenerator
from linkedin_worker.messaging.generator import MessageGenerator
from linkedin_worker.messaging.sender import MessageSender
from linkedin_worker.scraper.connections import scrape_connections
from linkedin_worker.scraper.models import (
    ConnectCandidate,
    FitRating,
    OutreachCandidate,
    ProfileData,
    normalize_linkedin_url,
)
from linkedin_worker.scraper.profile import scrape_profile
from linkedin_worker.scraper.search_results import scrape_search_results
from linkedin_worker.tracking.store import TrackingStore
from linkedin_worker.utils.logging import log

console = Console()


# --- ICP Filtering ---


def evaluate_fit(profile: ProfileData, icp: ICPConfig) -> tuple[FitRating, str]:
    """Evaluate a profile against ICP criteria. Returns (rating, reason)."""
    title = profile.current_title.lower()
    headline = profile.headline.lower()
    combined = f"{title} {headline}"

    # Check skip signals first
    for signal in icp.skip_signals:
        if signal.lower() in combined:
            return FitRating.SKIP, f"Skip signal: '{signal}'"

    # Check skip titles
    for skip in icp.skip_titles:
        if skip.lower() in combined:
            return FitRating.SKIP, f"Skip title: '{skip}'"

    # Check strong fit titles
    for strong in icp.strong_titles:
        if strong.lower() in combined:
            return FitRating.STRONG, f"Strong title: '{strong}'"

    # Check maybe titles
    for maybe in icp.maybe_titles:
        if maybe.lower() in combined:
            return FitRating.MAYBE, f"Maybe title: '{maybe}'"

    # Default: worth a shot if we have no signal
    return FitRating.MAYBE, "No strong signal, defaulting to maybe"


# --- Pipeline ---


async def _run_pipeline(
    config: AppConfig, headless: bool, dry_run: bool, batch_size: int | None
) -> None:
    """Execute the full outreach pipeline."""
    if not config.campaign.search_url:
        log.error("No search_url configured. Set it in config.yaml.")
        return

    if batch_size is not None:
        config.session.batch_size = batch_size

    # Initialize tracking store
    store = TrackingStore(config.data_dir / "tracking.db")
    store.initialize()

    # Start browser session
    session = LinkedInSession(config)
    page = await session.start(headless=headless)

    if not await session.is_logged_in():
        log.error("Not logged in. Run 'linkedin-worker login' first.")
        await session.close()
        return

    rate_limiter = RateLimiter(
        config.session.min_delay_seconds,
        config.session.max_delay_seconds,
    )

    try:
        # Check if search URL already filters by 1st-degree connections
        search_url = config.campaign.search_url
        is_prefiltered = "network=" in search_url and "%22F%22" in search_url

        if is_prefiltered:
            log.info("Search URL already filters by 1st-degree connections, "
                     "skipping connections scrape.")
        else:
            # 1. Get user's connections (cached or fresh scrape)
            connections_set = store.get_cached_connections(
                max_age_hours=config.session.connections_cache_hours,
            )
            if connections_set is None:
                log.info("Scraping connections list (this may take a few minutes)...")
                connections = await scrape_connections(page, rate_limiter)
                connections_set = {
                    normalize_linkedin_url(c.profile_url) for c in connections
                }
                store.cache_connections(connections)
                log.info(f"Cached {len(connections_set)} connections.")
            else:
                log.info(f"Using cached connections ({len(connections_set)} entries).")

        # 2. Scrape search results
        log.info("Scraping search results...")
        search_results = await scrape_search_results(
            page, rate_limiter,
            search_url,
            max_pages=config.session.max_search_pages,
        )
        log.info(f"Found {len(search_results)} people in search results.")

        # 3. Cross-reference (skip if already pre-filtered)
        if is_prefiltered:
            candidates = search_results
            log.info(f"All {len(candidates)} results are 1st-degree connections.")
        else:
            candidates = [
                r for r in search_results
                if normalize_linkedin_url(r.profile_url) in connections_set
            ]
            log.info(f"{len(candidates)} are 1st-degree connections (messageable).")

        # 4. Filter already-messaged
        new_candidates = [
            c for c in candidates
            if not store.was_already_messaged(normalize_linkedin_url(c.profile_url))
        ]
        log.info(f"{len(new_candidates)} haven't been messaged yet.")

        # 5. Process batch
        generator = MessageGenerator(config)
        sender = MessageSender(rate_limiter)
        sent_count = 0
        skipped_count = 0

        for candidate in new_candidates[: config.session.batch_size]:
            try:
                # Scrape full profile
                log.info(f"Scraping profile: {candidate.name}")
                profile = await scrape_profile(page, rate_limiter, candidate.profile_url)
                await rate_limiter.wait()

                # Verify profile keyword (e.g. GDC) if configured
                profile_keyword = config.campaign.require_profile_keyword
                if profile_keyword:
                    haystack = " ".join([
                        candidate.name, candidate.headline,
                        profile.name, profile.headline,
                        profile.about,
                    ]).lower()
                    if profile_keyword.lower() not in haystack:
                        log.info(f"  Skipping {profile.name}: no '{profile_keyword}' mention found on profile")
                        skipped_count += 1
                        continue

                # Evaluate ICP fit
                rating, reason = evaluate_fit(profile, config.icp)
                if rating == FitRating.SKIP:
                    log.info(f"  Skipping {profile.name}: {reason}")
                    skipped_count += 1
                    continue

                # Generate message
                log.info(f"  Generating message for {profile.name} ({rating.value})...")
                message = await generator.generate_opener(profile)
                log.info(f"  Message: {message}")

                # Send or log
                if dry_run:
                    log.info(f"  [DRY RUN] Would send to {profile.name}")
                    outreach = OutreachCandidate(
                        profile=profile,
                        fit_rating=rating,
                        fit_reason=reason,
                        generated_message=message,
                        message_sent=False,
                    )
                    store.record_outreach(outreach, config.campaign.name)
                else:
                    success = await sender.send_message(
                        page, candidate.profile_url, message,
                        expected_name=profile.name,
                    )
                    outreach = OutreachCandidate(
                        profile=profile,
                        fit_rating=rating,
                        fit_reason=reason,
                        generated_message=message,
                        message_sent=success,
                        sent_at=datetime.utcnow() if success else None,
                    )
                    store.record_outreach(outreach, config.campaign.name)

                    if success:
                        sent_count += 1
                        log.info(f"  Sent to {profile.name}")
                    else:
                        log.warning(f"  Failed to send to {profile.name}")

                await rate_limiter.wait()

            except Exception as e:
                log.error(f"  Error processing {candidate.name}: {e}")
                if config.session.screenshot_on_error:
                    try:
                        ts = int(time.time())
                        path = config.data_dir / "screenshots" / f"error_{ts}.png"
                        await page.screenshot(path=str(path))
                    except Exception:
                        pass
                store.record_error(candidate.profile_url, str(e))
                continue

        # 6. Session summary
        stats = store.get_session_stats()
        console.print()
        console.print("[bold]Session Summary[/bold]")
        console.print(f"  Messages sent this session: {sent_count}")
        console.print(f"  Skipped (ICP filter): {skipped_count}")
        console.print(f"  Total sent all-time: {stats['total']}")
        console.print(f"  Sent today: {stats['today']}")
        console.print(f"  Errors: {stats['errors']}")

    finally:
        await session.save_cookies()
        await session.close()
        store.close()


# --- GDC relevance filtering ---

# False-positive GDC terms (data centers, orgs, etc.)
_GDC_FALSE_POSITIVES = {
    "stt gdc", "global distributors collective", "gdc policy",
    "geophysics and drilling", "gdc philippines", "gdc india",
    "gdc chennai", "gdc mumbai",
}

# Phrases that indicate the AUTHOR personally attends GDC
_GDC_PERSONAL_SIGNALS = [
    "heading to gdc", "going to gdc", "see you at gdc",
    "i'll be at gdc", "i will be at gdc", "i'm at gdc",
    "excited for gdc", "preparing for gdc", "ready for gdc",
    "my gdc", "our gdc schedule", "join us at gdc", "join me at gdc",
    "attending gdc", "speaking at gdc", "presenting at gdc",
    "exhibiting at gdc", "demoing at gdc", "showcasing at gdc",
    "gdc schedule", "gdc booth", "gdc talk", "gdc panel",
    "come find us at gdc", "meet me at gdc", "meet us at gdc",
    "can't wait for gdc", "counting down to gdc", "gdc prep",
    "gdc bound", "gdc ready", "gdc 2026", "gdc 2025",
    "at gdc this year", "be at gdc", "come to gdc",
    "gdc san francisco", "gdc sf",
]


def _is_genuine_art_outsource_candidate(
    post_text: str, relevance_keywords: list[str],
) -> bool:
    """Return True if the post is about game art outsourcing or production."""
    text_lower = (post_text or "").lower()
    return any(kw.lower() in text_lower for kw in relevance_keywords)


def _build_people_search_url(keyword: str, geo_urn: str, industry_code: str) -> str:
    """Build a LinkedIn people search URL with optional geo and industry filters."""
    from urllib.parse import quote
    url = f"https://www.linkedin.com/search/results/people/?keywords={quote(keyword)}"
    if geo_urn:
        url += f"&geoUrn=%5B%22{geo_urn}%22%5D"
    if industry_code:
        url += f"&industryCode=%5B%22{industry_code}%22%5D"
    return url


def _has_buyer_intent_post(
    post_text: str,
    buyer_intent_keywords: list[str],
    buyer_skip_keywords: list[str],
) -> bool:
    """Return True if the post shows genuine buyer intent for art outsourcing."""
    text = (post_text or "").lower()
    if any(sig in text for sig in buyer_skip_keywords):
        return False
    return any(sig in text for sig in buyer_intent_keywords)


def _is_russian_profile(
    name: str, location: str, russian_location_signals: list[str],
) -> bool:
    """Return True if profile appears to be Russian/Belarusian."""
    if any('\u0400' <= c <= '\u04ff' for c in name):
        return True
    loc_lower = (location or "").lower()
    return any(sig in loc_lower for sig in russian_location_signals)


def _is_genuine_gdc_candidate(
    name: str, headline: str, post_text: str, gdc_keywords: list[str],
) -> bool:
    """Check if a candidate genuinely attends GDC (not just a mention in tags).

    Returns True only when:
    - The author's name or headline contains a GDC keyword, OR
    - The post text contains a personal signal of GDC attendance.

    Returns False for:
    - GDC mentioned only in tagged people's names
    - False-positive GDC terms (data centers, orgs)
    - No GDC mention at all
    """
    name_lower = (name or "").lower()
    headline_lower = (headline or "").lower()
    text_lower = (post_text or "").lower()

    # 1. Check if GDC keyword is NOT present at all
    has_any_gdc = any(g.lower() in text_lower for g in gdc_keywords)
    author_has_gdc = any(
        g.lower() in name_lower or g.lower() in headline_lower
        for g in gdc_keywords
    )

    if not has_any_gdc and not author_has_gdc:
        return False

    # 2. Author name/headline mentions GDC → strong signal
    if author_has_gdc:
        # But filter out false-positive orgs
        combined = f"{name_lower} {headline_lower}"
        if any(fp in combined for fp in _GDC_FALSE_POSITIVES):
            return False
        return True

    # 3. Post text: check for false-positive GDC terms first
    if any(fp in text_lower for fp in _GDC_FALSE_POSITIVES):
        return False

    # 4. Post text: look for personal attendance signals
    if any(signal in text_lower for signal in _GDC_PERSONAL_SIGNALS):
        return True

    # 5. No personal signal found → GDC is just mentioned in passing/tags
    return False


async def _connect_pipeline(
    config: AppConfig, headless: bool, dry_run: bool,
    batch_size: int | None, keywords: str | None,
    skip_connect: bool = False,
) -> None:
    """Execute the connect+comment outreach pipeline.

    Principle: when you open a page, do ALL work on it before navigating away.
    Flow per candidate from content search:
      1. We already have the post text from search results
      2. Generate comment
      3. Navigate to the post → post comment (stay on page)
      4. Navigate to author profile → click Connect
      5. Done, next candidate
    Flow per candidate from people search:
      1. Navigate to profile → scrape it, check for GDC in about/headline
      2. Click Connect (we're already on the profile page)
      3. Go to activity → find post → comment on it (stay on activity page)
      4. Done, next candidate
    """
    cc = config.connect_campaign

    if batch_size is not None:
        config.session.batch_size = batch_size

    content_keywords = cc.keywords
    people_keywords = cc.people_search_keywords
    if keywords:
        content_keywords = [keywords]
        people_keywords = [keywords]

    store = TrackingStore(config.data_dir / "tracking.db")
    store.initialize()

    session = LinkedInSession(config)
    page = await session.start(headless=headless)

    if not await session.is_logged_in():
        log.error("Not logged in. Run 'linkedin-worker login' first.")
        await session.close()
        return

    rate_limiter = RateLimiter(
        config.session.min_delay_seconds,
        config.session.max_delay_seconds,
    )
    rate_limiter.max_connects_per_day = config.session.max_connects_per_day
    rate_limiter.max_comments_per_day = config.session.max_comments_per_day

    try:
        # --- Phase 1: Discover candidates (search only, no profile visits) ---
        candidates: list[ConnectCandidate] = []
        seen_urls: set[str] = set()

        # Content search: find posts mentioning GDC → gives us post + author
        if cc.use_content_search:
            content_page = ContentSearchPage(page, rate_limiter)
            for kw in content_keywords:
                log.info(f"Content search: '{kw}'")
                results = await content_page.get_all_results(
                    kw,
                    max_pages=cc.max_content_search_pages,
                    geo_urn=cc.geo_urn,
                )
                for r in results:
                    url = normalize_linkedin_url(r.author_profile_url)
                    if url in seen_urls or store.was_already_connect_processed(url):
                        continue
                    if r.post_url and store.was_post_already_commented(r.post_url):
                        continue
                    seen_urls.add(url)
                    if cc.campaign_mode == "art_outsource":
                        is_relevant = _is_genuine_art_outsource_candidate(
                            r.post_text, cc.relevance_keywords,
                        )
                    else:
                        is_relevant = _is_genuine_gdc_candidate(
                            r.author_name, r.author_headline, r.post_text,
                            cc.gdc_keywords,
                        )
                    if not is_relevant:
                        continue
                    candidates.append(ConnectCandidate(
                        profile_url=url,
                        name=r.author_name,
                        headline=r.author_headline,
                        post_url=r.post_url,
                        post_text=r.post_text,
                        is_gdc_post=is_relevant,
                        source="content_search",
                    ))
                await rate_limiter.wait()

        # People search: find profiles with GDC in headline
        if cc.use_people_search:
            from urllib.parse import quote
            search_pg = SearchResultsPage(page, rate_limiter)
            for kw in people_keywords:
                if cc.campaign_mode == "buyer_intent":
                    search_url = _build_people_search_url(kw, cc.geo_urn, cc.industry_code)
                else:
                    search_url = (
                        f"https://www.linkedin.com/search/results/people/"
                        f"?keywords={quote(kw)}"
                    )
                log.info(f"People search: '{kw}'")
                results = await search_pg.get_all_results(
                    search_url, max_pages=cc.max_people_search_pages,
                )
                for r in results:
                    url = normalize_linkedin_url(r.profile_url)
                    if url in seen_urls or store.was_already_connect_processed(url):
                        continue
                    seen_urls.add(url)
                    candidates.append(ConnectCandidate(
                        profile_url=url,
                        name=r.name,
                        headline=r.headline,
                        source="people_search",
                    ))
                await rate_limiter.wait()

        log.info(f"Found {len(candidates)} new candidates total.")

        # --- Phase 2: Process each candidate (page-by-page) ---
        comment_gen = CommentGenerator()
        profile_page = ProfilePage(page, rate_limiter)
        activity_page = ActivityPage(page, rate_limiter)
        comment_composer = CommentComposer(page, rate_limiter)

        processed = 0
        comments_posted = 0
        connects_sent = 0
        skipped_count = 0

        for candidate in candidates[: config.session.batch_size]:
            try:
                log.info(f"\n--- Processing: {candidate.name} ({candidate.source}) ---")

                if candidate.source == "content_search":
                    # We already have the post from search.
                    # Step 1: Generate comment based on campaign mode
                    if cc.campaign_mode == "art_outsource":
                        log.info(f"  Art outsource post. Generating comment...")
                        comment = await comment_gen.generate_art_outsource_comment(
                            candidate.post_text, candidate.name, candidate.headline,
                        )
                    elif candidate.is_gdc_post:
                        log.info(f"  GDC post found. Generating GDC comment...")
                        comment = await comment_gen.generate_gdc_comment(
                            candidate.post_text, candidate.name,
                        )
                    else:
                        log.info(f"  Skipping {candidate.name}: not a genuine GDC candidate")
                        skipped_count += 1
                        continue
                    if not comment:
                        log.info(f"  Claude returned SKIP — post not genuinely GDC-related.")
                        skipped_count += 1
                        continue
                    candidate.comment_text = comment
                    log.info(f"  Comment: {comment}")

                    # Step 2: Go to the post → comment on it
                    if candidate.post_url and not dry_run:
                        success = await comment_composer.post_comment(
                            candidate.post_url, comment,
                        )
                        candidate.comment_posted = success
                        if success:
                            comments_posted += 1
                        await rate_limiter.wait()
                    elif comment and dry_run:
                        log.info(f"  [DRY RUN] Would post comment.")

                    # Step 3: Go to profile → Connect (single navigation)
                    if not skip_connect:
                        log.info(f"  Opening profile for Connect...")
                        await page.goto(
                            candidate.profile_url,
                            wait_until="domcontentloaded", timeout=60000,
                        )
                        await page.wait_for_timeout(3000)

                        if not dry_run:
                            ok = await profile_page.click_connect_no_note()
                            candidate.connect_sent = ok
                            if ok:
                                connects_sent += 1
                            await rate_limiter.wait()
                        else:
                            log.info(f"  [DRY RUN] Would send Connect request.")
                    else:
                        log.info(f"  Skipping Connect (--no-connect).")

                else:
                    # People search candidate — no post yet.
                    # Step 1: Go to profile → scrape
                    log.info(f"  Opening profile...")
                    profile = await profile_page.scrape(candidate.profile_url)
                    await page.wait_for_timeout(1000)

                    if cc.campaign_mode == "buyer_intent":
                        # --- Buyer intent flow ---

                        # Check for Russian profile
                        if _is_russian_profile(
                            profile.name, profile.location, cc.russian_location_signals,
                        ):
                            log.info(
                                f"  SKIP (Russian profile): {profile.name} @ {profile.location}"
                            )
                            skipped_count += 1
                            store.record_connect_outreach(candidate, config.campaign.name)
                            continue

                        # Step 2: Check recent activity for buyer intent post
                        log.info(f"  Checking recent activity for buyer intent...")
                        posts = await activity_page.get_recent_posts(candidate.profile_url)
                        await rate_limiter.wait()

                        buyer_post = None
                        for p in posts:
                            if _has_buyer_intent_post(
                                p.text, cc.buyer_intent_keywords, cc.buyer_skip_keywords,
                            ):
                                buyer_post = p
                                break

                        if not buyer_post:
                            log.info(f"  SKIP (no buyer intent post): {profile.name}")
                            skipped_count += 1
                            store.record_connect_outreach(candidate, config.campaign.name)
                            continue

                        log.info(f"  BUYER INTENT FOUND: {buyer_post.post_url}")
                        candidate.post_text = buyer_post.text
                        candidate.post_url = buyer_post.post_url

                        # Step 3: Generate comment
                        comment = await comment_gen.generate_art_outsource_comment(
                            candidate.post_text, profile.name, profile.headline,
                        )
                        if not comment:
                            log.info(f"  Claude returned SKIP.")
                            skipped_count += 1
                            store.record_connect_outreach(candidate, config.campaign.name)
                            continue
                        candidate.comment_text = comment
                        log.info(f"  Comment: {comment}")

                        # Step 4: Post comment on the buyer intent post
                        if candidate.post_url and not dry_run:
                            success = await comment_composer.post_comment(
                                candidate.post_url, comment,
                            )
                            candidate.comment_posted = success
                            if success:
                                comments_posted += 1
                            await rate_limiter.wait()
                        elif dry_run:
                            log.info(f"  [DRY RUN] Would post comment.")

                        # Step 5: Navigate to profile → Connect
                        if not skip_connect:
                            log.info(f"  Navigating to profile for Connect...")
                            await page.goto(
                                candidate.profile_url,
                                wait_until="domcontentloaded", timeout=60000,
                            )
                            await page.wait_for_timeout(3000)
                            if not dry_run:
                                ok = await profile_page.click_connect_no_note()
                                candidate.connect_sent = ok
                                if ok:
                                    connects_sent += 1
                                await rate_limiter.wait()
                            else:
                                log.info(f"  [DRY RUN] Would send Connect request.")
                        else:
                            log.info(f"  Skipping Connect (--no-connect).")

                    else:
                        # --- Original GDC people search flow ---

                        # Check if GDC is mentioned in profile
                        haystack = f"{profile.headline} {profile.about}".lower()
                        has_gdc = any(g.lower() in haystack for g in cc.gdc_keywords)
                        if has_gdc:
                            log.info(f"  GDC mentioned in profile.")
                            candidate.is_gdc_post = True

                        # Connect right here on the profile page
                        if not skip_connect:
                            if not dry_run:
                                ok = await profile_page.click_connect_no_note()
                                candidate.connect_sent = ok
                                if ok:
                                    connects_sent += 1
                                await rate_limiter.wait()
                            else:
                                log.info(f"  [DRY RUN] Would send Connect request.")
                        else:
                            log.info(f"  Skipping Connect (--no-connect).")

                        # Step 2: Go to activity → find a post → comment
                        log.info(f"  Checking activity for posts...")
                        posts = await activity_page.get_recent_posts(
                            candidate.profile_url, gdc_keywords=cc.gdc_keywords,
                        )

                        if posts:
                            # Prefer GDC post, else take the latest
                            gdc_posts = [p for p in posts if p.is_gdc_related]
                            target = gdc_posts[0] if gdc_posts else posts[0]
                            candidate.post_url = target.post_url
                            candidate.post_text = target.text
                            candidate.is_gdc_post = target.is_gdc_related

                            if target.is_gdc_related:
                                log.info(f"  Found GDC post. Generating GDC comment...")
                                comment = await comment_gen.generate_gdc_comment(
                                    target.text, candidate.name,
                                )
                            else:
                                log.info(f"  No GDC post. Generating contextual comment...")
                                comment = await comment_gen.generate_contextual_comment(
                                    target.text, candidate.name, candidate.headline,
                                )
                            if not comment:
                                log.info(f"  Claude returned SKIP — skipping comment.")
                            else:
                                candidate.comment_text = comment
                                log.info(f"  Comment: {comment}")

                            # Comment right here on the activity page
                            if comment and not dry_run:
                                if target.post_url:
                                    success = await comment_composer.post_comment(
                                        target.post_url, comment,
                                    )
                                else:
                                    # No direct URL — comment on first visible post
                                    success = await comment_composer.comment_on_activity_post(
                                        0, comment,
                                    )
                                candidate.comment_posted = success
                                if success:
                                    comments_posted += 1
                                await rate_limiter.wait()
                            elif comment and dry_run:
                                log.info(f"  [DRY RUN] Would post comment.")
                        else:
                            log.info(f"  No posts found. Skipping comment.")

                # Record result
                store.record_connect_outreach(candidate, config.campaign.name)
                processed += 1

            except Exception as e:
                log.error(f"  Error processing {candidate.name}: {e}")
                if config.session.screenshot_on_error:
                    try:
                        ts = int(time.time())
                        path = config.data_dir / "screenshots" / f"connect_error_{ts}.png"
                        await page.screenshot(path=str(path))
                    except Exception:
                        pass
                store.record_error(candidate.profile_url, str(e))
                continue

        # --- Session summary ---
        stats = store.get_connect_stats()
        console.print()
        console.print("[bold]Connect Pipeline Summary[/bold]")
        console.print(f"  Processed this session: {processed}")
        console.print(f"  Comments posted: {comments_posted}")
        console.print(f"  Skipped (not GDC): {skipped_count}")
        console.print(f"  Connect requests sent: {connects_sent}")
        console.print(f"  Total all-time: {stats['total_processed']}")
        console.print(f"  GDC posts found: {stats['gdc_posts']}")
        if dry_run:
            console.print("  [yellow](Dry run — no actions were taken)[/yellow]")

    finally:
        await session.save_cookies()
        await session.close()
        store.close()


async def _dm_recent_connections_pipeline(
    config: AppConfig, headless: bool, dry_run: bool, max_age_days: int,
) -> None:
    """DM recently-added connections (people who accepted our connect requests)."""
    store = TrackingStore(config.data_dir / "tracking.db")
    store.initialize()

    session = LinkedInSession(config)
    page = await session.start(headless=headless)

    if not await session.is_logged_in():
        log.error("Not logged in. Run 'linkedin-worker login' first.")
        await session.close()
        return

    rate_limiter = RateLimiter(
        config.session.min_delay_seconds,
        config.session.max_delay_seconds,
    )

    try:
        # 1. Get recently-added connections
        log.info(f"Loading connections added in last {max_age_days} days...")
        conn_page = ConnectionsPage(page, rate_limiter)
        recent = await conn_page.get_recently_added(max_age_days=max_age_days)
        log.info(f"Found {len(recent)} recent connections.")

        # 2. Filter already-messaged
        new_candidates = [
            c for c in recent
            if not store.was_already_messaged(normalize_linkedin_url(c.profile_url))
        ]
        log.info(f"{len(new_candidates)} haven't been messaged yet.")

        if not new_candidates:
            log.info("No new connections to message. Done.")
            return

        # 3. Process each — only DM those heading to GDC
        gdc_keywords = config.connect_campaign.gdc_keywords or ["gdc", "game developers conference"]
        generator = MessageGenerator(config)
        sender = MessageSender(rate_limiter)
        profile_pg = ProfilePage(page, rate_limiter)
        activity_pg = ActivityPage(page, rate_limiter)
        sent_count = 0
        skipped_count = 0

        for candidate in new_candidates:
            try:
                log.info(f"\n--- DM: {candidate.name} ---")

                # Scrape profile
                profile = await profile_pg.scrape(candidate.profile_url)
                await rate_limiter.wait()

                # Check if GDC is mentioned in profile/headline/about
                haystack = " ".join([
                    candidate.name, candidate.headline or "",
                    profile.name, profile.headline,
                    profile.about,
                ]).lower()
                has_gdc_profile = any(kw.lower() in haystack for kw in gdc_keywords)

                # Also check recent activity for GDC mentions
                has_gdc_activity = False
                if not has_gdc_profile:
                    log.info(f"  No GDC in profile, checking recent activity...")
                    posts = await activity_pg.get_recent_posts(
                        candidate.profile_url, gdc_keywords=gdc_keywords,
                    )
                    has_gdc_activity = any(p.is_gdc_related for p in posts)
                    await rate_limiter.wait()

                if not has_gdc_profile and not has_gdc_activity:
                    log.info(f"  Skipping {profile.name}: no GDC signal in profile or activity.")
                    skipped_count += 1
                    continue

                log.info(f"  GDC signal found! Generating message...")

                # Generate message
                message = await generator.generate_opener(profile)
                log.info(f"  Message: {message}")

                # Evaluate ICP fit (soft — we already connected with them)
                rating, reason = evaluate_fit(profile, config.icp)

                if dry_run:
                    log.info(f"  [DRY RUN] Would send to {profile.name}")
                    outreach = OutreachCandidate(
                        profile=profile,
                        fit_rating=rating,
                        fit_reason=reason,
                        generated_message=message,
                        message_sent=False,
                    )
                    store.record_outreach(outreach, config.campaign.name)
                else:
                    success = await sender.send_message(
                        page, candidate.profile_url, message,
                        expected_name=profile.name,
                    )
                    outreach = OutreachCandidate(
                        profile=profile,
                        fit_rating=rating,
                        fit_reason=reason,
                        generated_message=message,
                        message_sent=success,
                        sent_at=datetime.utcnow() if success else None,
                    )
                    store.record_outreach(outreach, config.campaign.name)

                    if success:
                        sent_count += 1
                        log.info(f"  Sent to {profile.name}")
                    else:
                        log.warning(f"  Failed to send to {profile.name}")

                await rate_limiter.wait()

            except Exception as e:
                log.error(f"  Error processing {candidate.name}: {e}")
                if config.session.screenshot_on_error:
                    try:
                        ts = int(time.time())
                        path = config.data_dir / "screenshots" / f"dm_error_{ts}.png"
                        await page.screenshot(path=str(path))
                    except Exception:
                        pass
                store.record_error(candidate.profile_url, str(e))
                continue

        # Summary
        console.print()
        console.print("[bold]DM Recent Connections Summary[/bold]")
        console.print(f"  Candidates found: {len(new_candidates)}")
        console.print(f"  Messages sent: {sent_count}")
        console.print(f"  Skipped: {skipped_count}")
        if dry_run:
            console.print("  [yellow](Dry run — no messages were sent)[/yellow]")

    finally:
        await session.save_cookies()
        await session.close()
        store.close()


async def _login_flow(config: AppConfig) -> None:
    """Interactive login flow: opens headed browser for manual login."""
    session = LinkedInSession(config)
    page = await session.start(headless=False)

    await page.goto("https://www.linkedin.com/login")

    console.print(
        "\n[bold yellow]Please log in to LinkedIn in the browser window.[/bold yellow]"
    )
    console.print("Press Enter here once you're logged in and see your feed...")

    # Wait for user to press Enter in the terminal
    await asyncio.get_event_loop().run_in_executor(None, input)

    # Save cookies FIRST (browser still has the session)
    await session.save_cookies()

    # Then verify login by navigating to feed
    if await session.is_logged_in(navigate=True):
        console.print("[bold green]Login successful! Cookies saved.[/bold green]")
    else:
        # Cookies are still saved — they might work even if verification failed
        console.print(
            "[bold yellow]Could not verify login via selectors, "
            "but cookies were saved. Try running:[/bold yellow]"
        )
        console.print("  linkedin-worker run --dry-run --no-headless")

    await session.close()


# --- Click CLI ---


@click.group()
def main():
    """LinkedIn Worker - Automated LinkedIn outreach via Playwright + Claude."""
    pass


@main.command()
@click.option("--config", "config_path", default="config.yaml", help="Path to config file")
def login(config_path: str):
    """Open browser for manual LinkedIn login, save cookies."""
    config = load_config(config_path)
    asyncio.run(_login_flow(config))


@main.command()
@click.option("--config", "config_path", default="config.yaml", help="Path to config file")
@click.option("--headless/--no-headless", default=None, help="Run browser headlessly")
@click.option("--dry-run", is_flag=True, help="Scrape and generate but don't send")
@click.option("--batch-size", type=int, default=None, help="Override batch size from config")
@click.option("--max-pages", type=int, default=None, help="Override max search pages")
def run(config_path: str, headless: bool | None, dry_run: bool, batch_size: int | None, max_pages: int | None):
    """Execute the full outreach pipeline."""
    config = load_config(config_path)
    if headless is not None:
        config.session.headless = headless
    if max_pages is not None:
        config.session.max_search_pages = max_pages
    asyncio.run(_run_pipeline(config, config.session.headless, dry_run, batch_size))


@main.command()
@click.option("--config", "config_path", default="config.yaml", help="Path to config file")
@click.option("--headless/--no-headless", default=None, help="Run browser headlessly")
@click.option("--dry-run", is_flag=True, help="Scrape and generate but don't comment or connect")
@click.option("--batch-size", type=int, default=None, help="Override batch size from config")
@click.option("--keywords", type=str, default=None, help="Override search keywords")
@click.option("--no-connect", is_flag=True, help="Skip sending Connect requests (comments only)")
def connect(config_path: str, headless: bool | None, dry_run: bool, batch_size: int | None, keywords: str | None, no_connect: bool):
    """Find GDC-related people, comment on posts, send Connect requests."""
    config = load_config(config_path)
    if headless is not None:
        config.session.headless = headless
    asyncio.run(_connect_pipeline(config, config.session.headless, dry_run, batch_size, keywords, skip_connect=no_connect))


@main.command("dm-recent")
@click.option("--config", "config_path", default="config.yaml", help="Path to config file")
@click.option("--headless/--no-headless", default=None, help="Run browser headlessly")
@click.option("--dry-run", is_flag=True, help="Generate messages but don't send")
@click.option("--days", type=int, default=14, help="Max age in days for recent connections")
def dm_recent(config_path: str, headless: bool | None, dry_run: bool, days: int):
    """DM recently-added connections with personalized GDC messages."""
    config = load_config(config_path)
    if headless is not None:
        config.session.headless = headless
    asyncio.run(_dm_recent_connections_pipeline(config, config.session.headless, dry_run, days))


@main.command()
@click.option("--config", "config_path", default="config.yaml", help="Path to config file")
def status(config_path: str):
    """Show tracking statistics."""
    config = load_config(config_path)
    store = TrackingStore(config.data_dir / "tracking.db")
    store.initialize()

    stats = store.get_session_stats()

    table = Table(title="LinkedIn Worker Stats")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Messages sent today", str(stats["today"]))
    table.add_row("Messages sent this week", str(stats["this_week"]))
    table.add_row("Total messages sent", str(stats["total"]))
    table.add_row("Dry-run (generated only)", str(stats["dry_run"]))
    table.add_row("Errors", str(stats["errors"]))

    # Connect outreach stats
    connect_stats = store.get_connect_stats()
    if connect_stats["total_processed"] > 0:
        table.add_section()
        table.add_row("Connect: total processed", str(connect_stats["total_processed"]))
        table.add_row("Connect: comments posted", str(connect_stats["comments_posted"]))
        table.add_row("Connect: requests sent", str(connect_stats["connects_sent"]))
        table.add_row("Connect: GDC posts found", str(connect_stats["gdc_posts"]))

    console.print(table)
    store.close()


@main.command()
@click.option("--config", "config_path", default="config.yaml", help="Path to config file")
@click.option("--output", default="outreach_export.csv", help="Output CSV path")
def export(config_path: str, output: str):
    """Export outreach tracking data to CSV."""
    config = load_config(config_path)
    store = TrackingStore(config.data_dir / "tracking.db")
    store.initialize()
    store.export_csv(output)
    store.close()
    console.print(f"[bold green]Exported to {output}[/bold green]")
