"""Rate limiting with human-like delays and session management.

Based on research of LinkedIn detection methods and safe automation practices:
- Major actions (connect, comment, message): 45-180s between
- Minor actions (scroll, like): 15-45s between
- Dwell time on pages: 5-15s of "reading"
- Session breaks: pause 30-90 min after N actions
- Daily caps: hard limits per action type
"""

from __future__ import annotations

import asyncio
import random
import time

from linkedin_worker.utils.logging import log


class RateLimiter:
    """Enforces human-like delays between browser actions."""

    def __init__(self, min_delay: float = 45.0, max_delay: float = 120.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.action_count = 0
        self.session_start = time.time()

        # Daily caps (reset externally or per-run)
        self.connects_today = 0
        self.comments_today = 0
        self.messages_today = 0
        self.max_connects_per_day = 20
        self.max_comments_per_day = 25
        self.max_messages_per_day = 40

    async def wait(self) -> None:
        """Wait a random duration between major actions (connect, comment, navigate)."""
        delay = random.uniform(self.min_delay, self.max_delay)
        # Occasionally add extra-long pause (10% chance) to break pattern
        if random.random() < 0.10:
            delay += random.uniform(60, 180)
            log.info(f"  (extended pause: {delay:.0f}s)")
        await asyncio.sleep(delay)
        self.action_count += 1

        # Session break every 15-20 actions
        if self.action_count > 0 and self.action_count % random.randint(15, 20) == 0:
            await self.session_break()

    async def wait_short(self) -> None:
        """Shorter delay for minor actions (scrolling, reading)."""
        delay = random.uniform(2.0, 6.0)
        await asyncio.sleep(delay)

    async def dwell(self) -> None:
        """Simulate reading a page — stay on it for a realistic duration."""
        delay = random.uniform(5.0, 15.0)
        await asyncio.sleep(delay)

    async def session_break(self) -> None:
        """Take a longer break to simulate a human stepping away."""
        duration = random.uniform(120, 300)  # 2-5 minutes
        log.info(f"  Session micro-break: {duration:.0f}s ({self.action_count} actions so far)")
        await asyncio.sleep(duration)

    async def type_delay(self) -> int:
        """Return a per-character typing delay in ms to simulate human typing."""
        return random.randint(50, 150)

    def can_connect(self) -> bool:
        """Check if we're under the daily connect cap."""
        return self.connects_today < self.max_connects_per_day

    def can_comment(self) -> bool:
        """Check if we're under the daily comment cap."""
        return self.comments_today < self.max_comments_per_day

    def record_connect(self) -> None:
        self.connects_today += 1

    def record_comment(self) -> None:
        self.comments_today += 1
