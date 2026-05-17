"""Unit tests for scraper models."""

from __future__ import annotations

import pytest

from linkedin_worker.scraper.models import (
    ConnectCandidate,
    ConnectionEntry,
    FitRating,
    OutreachCandidate,
    ProfileData,
    SearchResult,
    normalize_linkedin_url,
)


class TestNormalizeLinkedinUrl:
    def test_strips_query_string(self) -> None:
        assert (
            normalize_linkedin_url("https://www.linkedin.com/in/foo?trk=abc")
            == "https://www.linkedin.com/in/foo"
        )

    def test_strips_trailing_slash(self) -> None:
        assert (
            normalize_linkedin_url("https://www.linkedin.com/in/foo/")
            == "https://www.linkedin.com/in/foo"
        )

    def test_lowercases(self) -> None:
        assert (
            normalize_linkedin_url("https://www.linkedin.com/in/Foo-Bar")
            == "https://www.linkedin.com/in/foo-bar"
        )

    def test_adds_scheme_when_missing(self) -> None:
        result = normalize_linkedin_url("/in/foo")
        assert result.startswith("https://www.linkedin.com")
        assert "/in/foo" in result

    def test_upgrades_http_to_https(self) -> None:
        assert (
            normalize_linkedin_url("http://www.linkedin.com/in/foo")
            == "https://www.linkedin.com/in/foo"
        )

    def test_handles_uppercase_http_scheme(self) -> None:
        """Mixed-case schemes shouldn't be treated as relative paths."""
        result = normalize_linkedin_url("HTTP://www.linkedin.com/in/foo")
        assert result == "https://www.linkedin.com/in/foo"

    def test_empty_url_returns_empty(self) -> None:
        """Empty input shouldn't morph into a linkedin.com root URL."""
        assert normalize_linkedin_url("") == ""

    def test_idempotent(self) -> None:
        url = "https://www.linkedin.com/in/sarah"
        assert normalize_linkedin_url(normalize_linkedin_url(url)) == url


class TestProfileData:
    def test_current_title_from_experience(self) -> None:
        p = ProfileData(
            name="Jane",
            profile_url="https://www.linkedin.com/in/jane",
            experience=[{"title": "Founder", "company": "Acme"}],
        )
        assert p.current_title == "Founder"

    def test_current_title_falls_back_to_headline_at_separator(self) -> None:
        p = ProfileData(
            name="Jane",
            profile_url="https://www.linkedin.com/in/jane",
            headline="CEO at Acme",
        )
        assert p.current_title == "CEO"

    def test_current_title_pipe_separator(self) -> None:
        p = ProfileData(
            name="Jane",
            profile_url="https://www.linkedin.com/in/jane",
            headline="CTO | Acme",
        )
        assert p.current_title == "CTO"

    def test_current_title_empty_when_no_headline(self) -> None:
        p = ProfileData(name="Jane", profile_url="x")
        assert p.current_title == ""


class TestOutreachCandidate:
    def test_default_values(self) -> None:
        profile = ProfileData(name="Jane", profile_url="x")
        c = OutreachCandidate(
            profile=profile,
            fit_rating=FitRating.STRONG,
            fit_reason="reason",
        )
        assert c.generated_message == ""
        assert c.message_sent is False
        assert c.sent_at is None

    def test_fit_rating_enum_values(self) -> None:
        assert FitRating.STRONG.value == "strong"
        assert FitRating.MAYBE.value == "maybe"
        assert FitRating.SKIP.value == "skip"


class TestConnectCandidate:
    def test_defaults(self) -> None:
        c = ConnectCandidate(profile_url="x", name="Jane")
        assert c.comment_posted is False
        assert c.connect_sent is False
        assert c.source == ""


class TestConnectionEntry:
    def test_defaults(self) -> None:
        e = ConnectionEntry(name="Jane", profile_url="x")
        assert e.headline == ""


class TestSearchResult:
    def test_defaults(self) -> None:
        r = SearchResult(name="Jane", profile_url="x")
        assert r.headline == ""
        assert r.connection_degree == ""
