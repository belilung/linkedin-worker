"""Adversarial integration + stress tests — Iteration 3."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from linkedin_worker.cli import (
    _build_people_search_url,
    _has_buyer_intent_post,
    _is_genuine_gdc_candidate,
    _is_russian_profile,
    evaluate_fit,
)
from linkedin_worker.config import ICPConfig, load_config
from linkedin_worker.scraper.models import (
    ConnectCandidate,
    FitRating,
    OutreachCandidate,
    ProfileData,
    normalize_linkedin_url,
)
from linkedin_worker.tracking.store import TrackingStore


# --- URL normalization against real LinkedIn URL shapes ---


class TestLinkedinUrlShapesInTheWild:
    @pytest.mark.parametrize("raw,expected", [
        ("https://www.linkedin.com/in/sarah/", "https://www.linkedin.com/in/sarah"),
        ("https://www.linkedin.com/in/sarah", "https://www.linkedin.com/in/sarah"),
        ("https://www.linkedin.com/in/sarah?trk=x&something=y",
         "https://www.linkedin.com/in/sarah"),
        ("https://www.linkedin.com/in/Sarah", "https://www.linkedin.com/in/sarah"),
        ("http://www.linkedin.com/in/sarah", "https://www.linkedin.com/in/sarah"),
        ("/in/sarah", "https://www.linkedin.com/in/sarah"),
        ("", ""),
    ])
    def test_shapes(self, raw: str, expected: str) -> None:
        assert normalize_linkedin_url(raw) == expected


# --- Tracking store concurrency & edge state ---


class TestStoreAdversarial:
    def test_double_record_connect_with_different_status_updates(
        self, tmp_path: Path,
    ) -> None:
        """Second record_connect_outreach call must replace the first thanks to
        INSERT OR REPLACE — ensure we don't end up with duplicate rows."""
        store = TrackingStore(tmp_path / "db.sqlite")
        store.initialize()
        c1 = ConnectCandidate(
            profile_url="https://www.linkedin.com/in/x",
            name="X",
            comment_posted=False,
            connect_sent=False,
        )
        c2 = ConnectCandidate(
            profile_url="https://www.linkedin.com/in/x",
            name="X",
            comment_posted=True,
            connect_sent=True,
        )
        store.record_connect_outreach(c1, "c")
        store.record_connect_outreach(c2, "c")
        stats = store.get_connect_stats()
        assert stats["total_processed"] == 1
        assert stats["comments_posted"] == 1
        assert stats["connects_sent"] == 1
        store.close()

    def test_was_already_messaged_ignores_dry_run(self, tmp_path: Path) -> None:
        """A dry-run generation must not mark a profile as messaged."""
        store = TrackingStore(tmp_path / "db.sqlite")
        store.initialize()
        p = ProfileData(name="A", profile_url="https://www.linkedin.com/in/a")
        dry = OutreachCandidate(
            profile=p,
            fit_rating=FitRating.STRONG,
            fit_reason="r",
            generated_message="hi",
            message_sent=False,
            sent_at=None,
        )
        store.record_outreach(dry, "c")
        assert not store.was_already_messaged(p.profile_url)
        # Now send for real
        dry.message_sent = True
        dry.sent_at = datetime.utcnow()
        store.record_outreach(dry, "c")
        assert store.was_already_messaged(p.profile_url)
        store.close()


# --- Config resilience ---


class TestConfigResilience:
    def test_malformed_yaml_surfaces_error(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        f = tmp_path / "broken.yaml"
        f.write_text(":::: not yaml :::", encoding="utf-8")
        with pytest.raises(Exception):
            load_config(str(f))

    def test_partial_config_loads(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        f = tmp_path / "c.yaml"
        f.write_text(
            "campaign:\n  name: partial\n",
            encoding="utf-8",
        )
        cfg = load_config(str(f))
        # Non-specified sections default
        assert cfg.campaign.name == "partial"
        assert cfg.session.batch_size == 10  # default


# --- ICP filter stress ---


class TestIcpStress:
    def test_empty_headline_and_title(self) -> None:
        icp = ICPConfig()
        p = ProfileData(name="X", profile_url="x", headline="", experience=[])
        rating, _ = evaluate_fit(p, icp)
        assert rating is FitRating.MAYBE

    def test_strong_title_substring_match(self) -> None:
        """'Co-Founder' must match 'Founder'."""
        icp = ICPConfig()
        p = ProfileData(name="X", profile_url="x", headline="Co-Founder at Acme")
        rating, _ = evaluate_fit(p, icp)
        assert rating is FitRating.STRONG


# --- GDC filter adversarial ---


class TestGdcFilterAdversarial:
    def test_gdc_booth_matches(self) -> None:
        assert _is_genuine_gdc_candidate(
            "A", "CEO at Foo",
            "come find us at our GDC booth, we'll have demos",
            ["gdc"],
        )

    def test_gdc_year_variant(self) -> None:
        assert _is_genuine_gdc_candidate(
            "A", "Engineer",
            "Super excited for GDC 2026",
            ["gdc"],
        )

    def test_empty_post_no_author_mention(self) -> None:
        assert not _is_genuine_gdc_candidate("A", "Engineer", "", ["gdc"])


# --- Buyer intent adversarial ---


class TestBuyerIntentAdversarial:
    def test_skip_keyword_takes_priority(self) -> None:
        """Even if 10 intent keywords match, a single skip blocks."""
        assert not _has_buyer_intent_post(
            "student hiring outsourcing freelance contract artist",
            buyer_intent_keywords=["hiring", "outsourcing", "contract"],
            buyer_skip_keywords=["student"],
        )


# --- Russian filter adversarial ---


class TestRussianFilterAdversarial:
    def test_mixed_latin_cyrillic_still_flagged(self) -> None:
        assert _is_russian_profile("Max Петров", "Berlin", ["russia"])

    def test_location_partial_match(self) -> None:
        assert _is_russian_profile(
            "John Smith", "Saint Petersburg, Russia",
            ["russia", "belarus", "saint petersburg"],
        )

    def test_non_cyrillic_non_russian_location(self) -> None:
        assert not _is_russian_profile(
            "John", "Berlin, Germany", ["russia"],
        )


# --- People search URL builder ---


class TestUrlBuilderAdversarial:
    def test_url_is_valid_http(self) -> None:
        url = _build_people_search_url("foo bar", "123", "7")
        assert url.startswith("https://www.linkedin.com/search/results/people/?")

    def test_plus_sign_in_keyword(self) -> None:
        url = _build_people_search_url("C++ dev", "", "")
        # + must be percent-encoded in URL path, not parsed as space
        assert "C%2B%2B" in url
