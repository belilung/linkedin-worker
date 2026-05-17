"""Unit tests for prompt builders."""

from __future__ import annotations

from linkedin_worker.messaging.comment_prompts import (
    build_comment_prompt_art_outsource,
    build_comment_prompt_contextual,
    build_comment_prompt_gdc,
)
from linkedin_worker.messaging.prompts import SYSTEM_PROMPT, build_user_prompt


class TestBuildUserPrompt:
    def test_includes_all_provided_fields(self) -> None:
        out = build_user_prompt(
            name="Jane",
            headline="CEO at Acme",
            about="Building games",
            current_company="Acme",
            current_title="CEO",
            experience_summary="CEO at Acme; Founder at Beta",
            tone="casual",
            sample_message="hey jane hi",
            campaign_context="GDC",
        )
        assert "Jane" in out
        assert "CEO at Acme" in out
        assert "Building games" in out
        assert "Tone: casual" in out
        assert "hey jane hi" in out

    def test_about_truncated_at_500(self) -> None:
        long = "x" * 2000
        out = build_user_prompt(
            name="Jane",
            headline="",
            about=long,
            current_company="",
            current_title="",
            experience_summary="",
            tone="casual",
            sample_message="",
            campaign_context="",
        )
        # About line should contain only 500 chars of x's
        about_line = [l for l in out.splitlines() if l.startswith("About:")][0]
        assert about_line == f"About: {'x' * 500}"

    def test_optional_fields_skipped_when_empty(self) -> None:
        out = build_user_prompt(
            name="Jane",
            headline="x",
            about="",
            current_company="",
            current_title="",
            experience_summary="",
            tone="casual",
            sample_message="",
            campaign_context="",
        )
        assert "Current Title:" not in out
        assert "Company:" not in out
        assert "About:" not in out
        assert "Recent Experience:" not in out
        assert "Style reference" not in out


class TestSystemPrompts:
    def test_default_system_prompt_not_empty(self) -> None:
        assert SYSTEM_PROMPT.strip()
        assert "GDC" in SYSTEM_PROMPT
        # Ensure em-dash rule still there
        assert "em dash" in SYSTEM_PROMPT.lower()


class TestCommentPromptGdc:
    def test_includes_post_and_author(self) -> None:
        out = build_comment_prompt_gdc("Heading to GDC 2026!", "Sarah")
        assert "Sarah" in out
        assert "Heading to GDC 2026!" in out

    def test_truncates_long_posts(self) -> None:
        long_post = "a" * 2000
        out = build_comment_prompt_gdc(long_post, "Sarah")
        assert "a" * 800 in out
        assert "a" * 1000 not in out


class TestCommentPromptContextual:
    def test_includes_headline_when_given(self) -> None:
        out = build_comment_prompt_contextual(
            "post body", "Sarah", author_headline="CEO at Foo"
        )
        assert "CEO at Foo" in out

    def test_omits_headline_when_empty(self) -> None:
        out = build_comment_prompt_contextual("post body", "Sarah")
        assert "Headline:" not in out


class TestCommentPromptArtOutsource:
    def test_contains_instruction(self) -> None:
        out = build_comment_prompt_art_outsource("Looking for art outsource", "Max")
        assert "Imaginus Studio" in out
        assert "Looking for art outsource" in out
