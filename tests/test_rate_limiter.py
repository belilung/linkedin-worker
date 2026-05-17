"""Unit tests for rate limiter."""

from __future__ import annotations

import asyncio

import pytest

from linkedin_worker.browser.rate_limiter import RateLimiter


class TestDailyCaps:
    def test_can_connect_under_cap(self) -> None:
        rl = RateLimiter()
        assert rl.can_connect()
        rl.record_connect()
        assert rl.can_connect()

    def test_cap_blocks_when_reached(self) -> None:
        rl = RateLimiter()
        rl.max_connects_per_day = 2
        rl.record_connect()
        rl.record_connect()
        assert not rl.can_connect()

    def test_comment_cap_independent(self) -> None:
        rl = RateLimiter()
        rl.max_connects_per_day = 1
        rl.record_connect()
        # Comments unaffected
        assert rl.can_comment()


class TestWait:
    async def test_wait_short_sleeps(self, monkeypatch) -> None:
        rl = RateLimiter()
        calls = []

        async def fake_sleep(d):
            calls.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)
        await rl.wait_short()
        assert len(calls) == 1
        assert 2.0 <= calls[0] <= 6.0

    async def test_wait_respects_configured_range(self, monkeypatch) -> None:
        rl = RateLimiter(min_delay=5.0, max_delay=10.0)
        captured = []

        async def fake_sleep(d):
            captured.append(d)

        # Force no extended pause and no session break
        import random
        monkeypatch.setattr(random, "random", lambda: 0.99)
        monkeypatch.setattr(random, "uniform", lambda a, b: (a + b) / 2)
        monkeypatch.setattr("asyncio.sleep", fake_sleep)
        await rl.wait()
        assert captured[0] == 7.5
        assert rl.action_count == 1

    async def test_dwell_sleeps_between_5_and_15(self, monkeypatch) -> None:
        rl = RateLimiter()
        durations = []

        async def fake_sleep(d):
            durations.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)
        await rl.dwell()
        assert 5.0 <= durations[0] <= 15.0


class TestTypeDelay:
    async def test_type_delay_in_human_range(self) -> None:
        rl = RateLimiter()
        for _ in range(20):
            d = await rl.type_delay()
            assert 50 <= d <= 150
