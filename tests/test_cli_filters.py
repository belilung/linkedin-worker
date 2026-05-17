"""Unit tests for CLI helper filter functions."""

from __future__ import annotations

import pytest

from linkedin_worker.cli import (
    _build_people_search_url,
    _has_buyer_intent_post,
    _is_genuine_art_outsource_candidate,
    _is_genuine_gdc_candidate,
    _is_russian_profile,
    evaluate_fit,
)
from linkedin_worker.config import ICPConfig
from linkedin_worker.scraper.models import FitRating, ProfileData


# --- evaluate_fit ---


class TestEvaluateFit:
    def test_strong_title(self) -> None:
        icp = ICPConfig()
        p = ProfileData(name="X", profile_url="x", headline="Founder at Acme")
        rating, _ = evaluate_fit(p, icp)
        assert rating is FitRating.STRONG

    def test_skip_title_beats_strong(self) -> None:
        """An Intern/Student should always skip even if another signal fires."""
        icp = ICPConfig()
        p = ProfileData(name="X", profile_url="x", headline="Intern Founder")
        rating, _ = evaluate_fit(p, icp)
        assert rating is FitRating.SKIP

    def test_skip_signal_beats_all(self) -> None:
        icp = ICPConfig()
        p = ProfileData(
            name="X", profile_url="x",
            headline="Open to work: Founder",
        )
        rating, reason = evaluate_fit(p, icp)
        assert rating is FitRating.SKIP
        assert "Open to work" in reason

    def test_maybe_title(self) -> None:
        icp = ICPConfig()
        p = ProfileData(name="X", profile_url="x", headline="Consultant")
        rating, _ = evaluate_fit(p, icp)
        assert rating is FitRating.MAYBE

    def test_default_maybe_when_no_signal(self) -> None:
        icp = ICPConfig()
        p = ProfileData(name="X", profile_url="x", headline="Tech Lead")
        rating, _ = evaluate_fit(p, icp)
        assert rating is FitRating.MAYBE

    def test_case_insensitive(self) -> None:
        icp = ICPConfig()
        p = ProfileData(name="X", profile_url="x", headline="FOUNDER AT ACME")
        rating, _ = evaluate_fit(p, icp)
        assert rating is FitRating.STRONG


# --- buyer intent ---


class TestBuyerIntent:
    def test_has_signal(self) -> None:
        assert _has_buyer_intent_post(
            "We are hiring a 3D artist",
            buyer_intent_keywords=["hiring", "outsourcing"],
            buyer_skip_keywords=[],
        )

    def test_skip_keyword_blocks_match(self) -> None:
        assert not _has_buyer_intent_post(
            "Hiring a student intern",
            buyer_intent_keywords=["hiring"],
            buyer_skip_keywords=["student"],
        )

    def test_empty_post(self) -> None:
        assert not _has_buyer_intent_post("", ["hiring"], [])

    def test_none_post(self) -> None:
        assert not _has_buyer_intent_post(None, ["hiring"], [])

    def test_no_keywords_means_false(self) -> None:
        assert not _has_buyer_intent_post("hiring artist", [], [])


# --- art outsourcing ---


class TestArtOutsourceFilter:
    def test_matches_relevance_keyword(self) -> None:
        assert _is_genuine_art_outsource_candidate(
            "Looking for 3D art production", ["3d art", "modeling"]
        )

    def test_no_match(self) -> None:
        assert not _is_genuine_art_outsource_candidate(
            "This is about marketing", ["3d art"]
        )

    def test_empty_keywords(self) -> None:
        assert not _is_genuine_art_outsource_candidate("about 3d art", [])

    def test_none_post_safe(self) -> None:
        assert not _is_genuine_art_outsource_candidate(None, ["foo"])


# --- Russian profile detector ---


class TestRussianFilter:
    def test_cyrillic_in_name(self) -> None:
        assert _is_russian_profile("Иван Иванов", "London", [])

    def test_location_signal(self) -> None:
        assert _is_russian_profile(
            "John Smith", "Moscow, Russia", ["russia", "belarus"],
        )

    def test_clean_english_profile_passes(self) -> None:
        assert not _is_russian_profile(
            "John Smith", "London, UK", ["russia", "belarus"],
        )

    def test_empty_location(self) -> None:
        assert not _is_russian_profile("John", "", ["russia"])

    def test_none_location(self) -> None:
        assert not _is_russian_profile("John", None, ["russia"])


# --- GDC genuine filter ---


class TestGdcGenuineFilter:
    def test_author_headline_match(self) -> None:
        assert _is_genuine_gdc_candidate(
            "Sarah", "Speaker at GDC 2026", "Some random post",
            ["gdc"],
        )

    def test_post_with_personal_signal(self) -> None:
        assert _is_genuine_gdc_candidate(
            "Sarah", "Engineer at Co",
            "Heading to GDC this year, excited to meet folks",
            ["gdc"],
        )

    def test_no_gdc_mention_anywhere(self) -> None:
        assert not _is_genuine_gdc_candidate(
            "Sarah", "Engineer", "just another post", ["gdc"],
        )

    def test_passing_tag_mention_no_personal_signal(self) -> None:
        """GDC only in tagged people — don't count as genuine."""
        assert not _is_genuine_gdc_candidate(
            "Sarah", "Engineer",
            "Thanks @gdc organizers for the invite, see some of you",
            ["gdc"],
        )

    def test_false_positive_data_center(self) -> None:
        assert not _is_genuine_gdc_candidate(
            "Sarah", "CEO at STT GDC",
            "Our new data center expansion",
            ["gdc"],
        )

    def test_gdc_india_false_positive(self) -> None:
        """GDC India is a different org; filter out."""
        assert not _is_genuine_gdc_candidate(
            "Sarah", "Works at GDC India",
            "Great day at GDC India, data center tour.",
            ["gdc"],
        )


# --- People search URL builder ---


class TestPeopleSearchUrl:
    def test_no_filters(self) -> None:
        url = _build_people_search_url("game artist", "", "")
        assert "keywords=game%20artist" in url
        assert "geoUrn" not in url
        assert "industryCode" not in url

    def test_with_geo(self) -> None:
        url = _build_people_search_url("x", "103644278", "")
        assert "geoUrn" in url
        assert "103644278" in url

    def test_with_industry(self) -> None:
        url = _build_people_search_url("x", "", "5")
        assert "industryCode" in url
        assert "%225%22" in url

    def test_special_chars_escaped(self) -> None:
        url = _build_people_search_url("3D & VFX", "", "")
        assert "%26" in url  # & encoded
