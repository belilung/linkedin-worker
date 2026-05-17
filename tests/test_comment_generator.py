"""Unit tests for CommentGenerator and _clean_comment."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from linkedin_worker.messaging.comment_generator import CommentGenerator, _clean_comment


class TestCleanComment:
    def test_passes_normal_comment(self) -> None:
        assert _clean_comment("Nice build, we're doing the same.") == "Nice build, we're doing the same."

    def test_trims_whitespace(self) -> None:
        assert _clean_comment("  hello  ") == "hello"

    def test_skip_literal_returns_empty(self) -> None:
        assert _clean_comment("SKIP") == ""
        assert _clean_comment("  skip ") == ""

    def test_strips_wrapping_double_quotes(self) -> None:
        assert _clean_comment('"hello world"') == "hello world"

    def test_removes_em_dashes(self) -> None:
        assert "—" not in _clean_comment("Nice — great post")
        assert _clean_comment("Nice — great post") == "Nice, great post"

    def test_removes_double_dash(self) -> None:
        assert _clean_comment("Nice -- cool") == "Nice, cool"

    def test_ai_refusal_returns_empty(self) -> None:
        refusals = [
            "I can't write that kind of comment.",
            "I'm sorry, but I cannot generate this content.",
            "As an AI language model, I must decline.",
            "This violates my policy guidelines.",
        ]
        for text in refusals:
            assert _clean_comment(text) == "", f"Refusal not caught: {text!r}"

    def test_preserves_legitimate_dashes_inside_words(self) -> None:
        """Hyphen inside a word (e.g. peer-to-peer) must be preserved."""
        out = _clean_comment("Love your peer-to-peer approach.")
        assert "peer-to-peer" in out


@pytest.mark.asyncio
class TestCommentGenerator:
    async def test_generate_gdc_comment_calls_backend(self) -> None:
        gen = CommentGenerator()
        with patch(
            "linkedin_worker.messaging.comment_generator._generate_text",
            return_value="Also heading to GDC, lets grab coffee.",
        ) as m:
            out = await gen.generate_gdc_comment("Heading to GDC!", "Sarah")
        assert out == "Also heading to GDC, lets grab coffee."
        assert m.call_count == 1
        # First positional arg is user prompt and it must mention author
        user_prompt = m.call_args.args[0]
        assert "Sarah" in user_prompt

    async def test_generate_contextual_strips_em_dash(self) -> None:
        gen = CommentGenerator()
        with patch(
            "linkedin_worker.messaging.comment_generator._generate_text",
            return_value="Cool — we do similar.",
        ):
            out = await gen.generate_contextual_comment("post", "Max", "CTO at X")
        assert "—" not in out

    async def test_generate_skip_returns_empty(self) -> None:
        gen = CommentGenerator()
        with patch(
            "linkedin_worker.messaging.comment_generator._generate_text",
            return_value="SKIP",
        ):
            out = await gen.generate_gdc_comment("unrelated", "A")
        assert out == ""

    async def test_ai_refusal_blocked_from_reaching_linkedin(self) -> None:
        """Critical: AI refusals must NEVER be posted as comments."""
        gen = CommentGenerator()
        with patch(
            "linkedin_worker.messaging.comment_generator._generate_text",
            return_value="I cannot create content that violates my policy.",
        ):
            out = await gen.generate_art_outsource_comment("post", "Max")
        assert out == ""
