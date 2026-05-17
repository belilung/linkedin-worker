"""Adversarial edge-case tests for messaging layer."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from linkedin_worker.config import AppConfig, CampaignConfig, VoiceConfig
from linkedin_worker.messaging import gemini_client
from linkedin_worker.messaging.comment_generator import _clean_comment
from linkedin_worker.messaging.generator import MessageGenerator
from linkedin_worker.scraper.models import ProfileData


class TestCleanCommentFalsePositiveGuard:
    def test_legit_word_policy_not_falsely_refusal(self) -> None:
        """A comment naturally mentioning 'policy' should NOT be dropped."""
        result = _clean_comment("Our refund policy is simple.")
        assert result == "Our refund policy is simple."

    def test_legit_word_ethical_not_falsely_refusal(self) -> None:
        result = _clean_comment("Love your ethical stance on this.")
        assert result == "Love your ethical stance on this."

    def test_still_blocks_strong_refusals(self) -> None:
        assert _clean_comment("I can't help with that.") == ""
        assert _clean_comment("As an AI, I must decline.") == ""
        assert _clean_comment("I cannot generate that content.") == ""

    def test_empty_comment_is_empty(self) -> None:
        assert _clean_comment("") == ""

    def test_whitespace_only_is_empty(self) -> None:
        assert _clean_comment("   \n\t  ") == ""


@pytest.mark.asyncio
class TestGenerateOpenerNoExperience:
    async def test_profile_without_experience_uses_headline(self) -> None:
        cfg = AppConfig()
        cfg.campaign = CampaignConfig(context="GDC", system_prompt="SYS")
        cfg.voice = VoiceConfig(tone="warm", sample_message="")
        gen = MessageGenerator(cfg)
        profile = ProfileData(
            name="Max",
            profile_url="https://www.linkedin.com/in/max",
            headline="Indie dev | Solo",
        )
        with patch(
            "linkedin_worker.messaging.generator._generate_text",
            return_value="Hi Max.",
        ) as m:
            await gen.generate_opener(profile)
        user_prompt = m.call_args.args[0]
        # experience_summary should be empty; no "Recent Experience" line
        assert "Recent Experience:" not in user_prompt
        # current_title falls back to headline split
        assert "Current Title: Indie dev" in user_prompt


class TestAnthropicApiErrorHandling:
    def test_api_empty_content_list_surfaces_clean_error(self, monkeypatch) -> None:
        """When Anthropic returns empty content, caller should get meaningful error
        rather than an IndexError from [0].text. This pins CURRENT behavior."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        class FakeResp:
            content: list = []

        class FakeClient:
            def __init__(self, api_key): pass
            class messages:
                @staticmethod
                def create(**kwargs): return FakeResp()

        with patch("linkedin_worker.messaging.generator.anthropic.Anthropic", FakeClient):
            from linkedin_worker.messaging.generator import _call_anthropic_api
            with pytest.raises(RuntimeError, match="empty content"):
                _call_anthropic_api("u", "s")


class TestGeminiErrorHandling:
    def test_empty_candidates_raises_runtimeerror(self, monkeypatch) -> None:
        """Gemini returning no candidates shouldn't crash with KeyError."""
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        body = {"candidates": []}
        fake_resp = MagicMock()
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)
        fake_resp.read = MagicMock(return_value=json.dumps(body).encode("utf-8"))

        with patch("urllib.request.urlopen", return_value=fake_resp):
            with pytest.raises(RuntimeError):
                gemini_client.call_gemini("u", "s")


class TestUseClaudeCliFlagVariants:
    def test_zero_routes_to_api(self, monkeypatch) -> None:
        monkeypatch.setenv("USE_CLAUDE_CLI", "0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        with patch(
            "linkedin_worker.messaging.generator._call_anthropic_api",
            return_value="api",
        ) as api_mock, patch(
            "linkedin_worker.messaging.generator._call_claude_cli",
            return_value="cli",
        ) as cli_mock:
            from linkedin_worker.messaging.generator import _generate_text
            out = _generate_text("u", "s")
        assert out == "api"
        assert cli_mock.call_count == 0

    def test_whitespace_routes_to_api(self, monkeypatch) -> None:
        monkeypatch.setenv("USE_CLAUDE_CLI", "  ")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        with patch(
            "linkedin_worker.messaging.generator._call_anthropic_api",
            return_value="api",
        ):
            from linkedin_worker.messaging.generator import _generate_text
            out = _generate_text("u", "s")
        assert out == "api"
