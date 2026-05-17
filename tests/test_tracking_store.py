"""Unit tests for tracking SQLite store."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from linkedin_worker.scraper.models import (
    ConnectCandidate,
    ConnectionEntry,
    FitRating,
    OutreachCandidate,
    ProfileData,
)
from linkedin_worker.tracking.store import TrackingStore


@pytest.fixture
def store(tmp_path: Path) -> TrackingStore:
    s = TrackingStore(tmp_path / "tracking.db")
    s.initialize()
    yield s
    s.close()


def _profile(name: str = "Jane", url: str = "https://www.linkedin.com/in/jane") -> ProfileData:
    return ProfileData(name=name, profile_url=url, headline="CEO at Acme")


def _candidate(sent: bool = True, url: str = "https://www.linkedin.com/in/jane") -> OutreachCandidate:
    return OutreachCandidate(
        profile=_profile(url=url),
        fit_rating=FitRating.STRONG,
        fit_reason="great",
        generated_message="hey",
        message_sent=sent,
        sent_at=datetime.utcnow() if sent else None,
    )


class TestInitialize:
    def test_creates_db_file(self, tmp_path: Path) -> None:
        s = TrackingStore(tmp_path / "nested" / "tracking.db")
        s.initialize()
        assert (tmp_path / "nested" / "tracking.db").exists()
        s.close()

    def test_operations_before_init_raise(self, tmp_path: Path) -> None:
        s = TrackingStore(tmp_path / "x.db")
        with pytest.raises(RuntimeError, match="initialize"):
            s.was_already_messaged("x")


class TestOutreachRecording:
    def test_record_and_detect_sent(self, store: TrackingStore) -> None:
        store.record_outreach(_candidate(sent=True), campaign="c1")
        assert store.was_already_messaged("https://www.linkedin.com/in/jane")

    def test_dry_run_not_marked_sent(self, store: TrackingStore) -> None:
        store.record_outreach(_candidate(sent=False), campaign="c1")
        assert not store.was_already_messaged("https://www.linkedin.com/in/jane")

    def test_unknown_url_not_messaged(self, store: TrackingStore) -> None:
        assert not store.was_already_messaged("https://www.linkedin.com/in/nobody")

    def test_idempotent_insert(self, store: TrackingStore) -> None:
        """INSERT OR REPLACE should not duplicate rows."""
        store.record_outreach(_candidate(), campaign="c1")
        store.record_outreach(_candidate(), campaign="c1")
        stats = store.get_session_stats()
        assert stats["total"] == 1


class TestSessionStats:
    def test_empty_stats(self, store: TrackingStore) -> None:
        stats = store.get_session_stats()
        assert stats == {"total": 0, "today": 0, "this_week": 0, "dry_run": 0, "errors": 0}

    def test_counts_dry_run_separately(self, store: TrackingStore) -> None:
        store.record_outreach(_candidate(sent=False, url="https://www.linkedin.com/in/a"), "c")
        store.record_outreach(_candidate(sent=True, url="https://www.linkedin.com/in/b"), "c")
        stats = store.get_session_stats()
        assert stats["total"] == 1
        assert stats["dry_run"] == 1

    def test_counts_errors(self, store: TrackingStore) -> None:
        store.record_error("https://www.linkedin.com/in/x", "timeout")
        store.record_error("https://www.linkedin.com/in/y", "blocked")
        stats = store.get_session_stats()
        assert stats["errors"] == 2

    def test_today_count_for_sent_today(self, store: TrackingStore) -> None:
        store.record_outreach(_candidate(sent=True), "c")
        stats = store.get_session_stats()
        assert stats["today"] == 1


class TestConnectionsCache:
    def test_cache_miss_returns_none(self, store: TrackingStore) -> None:
        assert store.get_cached_connections() is None

    def test_cache_hit_returns_urls(self, store: TrackingStore) -> None:
        conns = [
            ConnectionEntry(name="Alice", profile_url="https://www.linkedin.com/in/a"),
            ConnectionEntry(name="Bob", profile_url="https://www.linkedin.com/in/b"),
        ]
        store.cache_connections(conns)
        cached = store.get_cached_connections(max_age_hours=24)
        assert cached == {
            "https://www.linkedin.com/in/a",
            "https://www.linkedin.com/in/b",
        }

    def test_cache_expiry(self, store: TrackingStore) -> None:
        """Expired cache must return None so fresh scrape triggers."""
        conns = [ConnectionEntry(name="A", profile_url="u")]
        store.cache_connections(conns)
        # Simulate stale cache
        stale = (datetime.utcnow() - timedelta(hours=48)).isoformat()
        store._ensure_conn().execute(
            "UPDATE connections_cache SET cached_at = ?", (stale,)
        )
        store._ensure_conn().commit()
        assert store.get_cached_connections(max_age_hours=24) is None

    def test_cache_replaces_old(self, store: TrackingStore) -> None:
        first = [ConnectionEntry(name="Old", profile_url="u1")]
        second = [ConnectionEntry(name="New", profile_url="u2")]
        store.cache_connections(first)
        store.cache_connections(second)
        cached = store.get_cached_connections()
        assert cached == {"u2"}


class TestConnectOutreach:
    def test_was_already_processed(self, store: TrackingStore) -> None:
        c = ConnectCandidate(
            profile_url="https://www.linkedin.com/in/x",
            name="X",
            source="content_search",
        )
        assert not store.was_already_connect_processed(c.profile_url)
        store.record_connect_outreach(c, campaign="c1")
        assert store.was_already_connect_processed(c.profile_url)

    def test_post_dedup(self, store: TrackingStore) -> None:
        c = ConnectCandidate(
            profile_url="https://www.linkedin.com/in/x",
            name="X",
            post_url="https://www.linkedin.com/posts/abc",
            comment_posted=True,
        )
        store.record_connect_outreach(c, campaign="c1")
        assert store.was_post_already_commented("https://www.linkedin.com/posts/abc")
        assert not store.was_post_already_commented("https://www.linkedin.com/posts/other")

    def test_empty_post_url_not_commented(self, store: TrackingStore) -> None:
        assert not store.was_post_already_commented("")

    def test_connect_stats(self, store: TrackingStore) -> None:
        store.record_connect_outreach(
            ConnectCandidate(profile_url="a", name="A", comment_posted=True, is_gdc_post=True),
            "c",
        )
        store.record_connect_outreach(
            ConnectCandidate(profile_url="b", name="B", connect_sent=True),
            "c",
        )
        stats = store.get_connect_stats()
        assert stats["total_processed"] == 2
        assert stats["comments_posted"] == 1
        assert stats["connects_sent"] == 1
        assert stats["gdc_posts"] == 1


class TestExport:
    def test_export_csv(self, store: TrackingStore, tmp_path: Path) -> None:
        store.record_outreach(_candidate(), "c1")
        out = tmp_path / "export.csv"
        store.export_csv(str(out))
        assert out.exists()
        with open(out) as f:
            rows = list(csv.reader(f))
        assert len(rows) == 2  # header + 1 row
        assert "profile_url" in rows[0]

    def test_export_empty(self, store: TrackingStore, tmp_path: Path) -> None:
        out = tmp_path / "export.csv"
        store.export_csv(str(out))
        with open(out) as f:
            rows = list(csv.reader(f))
        assert len(rows) == 1  # only header
