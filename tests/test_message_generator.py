"""Unit tests for MessageGenerator (DM generator)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from linkedin_worker.config import AppConfig, CampaignConfig, VoiceConfig
from linkedin_worker.messaging.generator import MessageGenerator, _generate_text
from linkedin_worker.scraper.models import ProfileData


def _make_config(system_prompt: str = "") -> AppConfig:
    cfg = AppConfig()
    cfg.campaign = CampaignConfig(
        name="test",
        search_url="",
        context="GDC outreach",
        system_prompt=system_prompt,
    )
    cfg.voice = VoiceConfig(tone="casual", sample_message="hey it's me")
    return cfg


def _profile() -> ProfileData:
    return ProfileData(
        name="Sarah Jones",
        profile_url="https://www.linkedin.com/in/sarah",
        headline="Founder at GameCo",
        about="Building indie games",
        current_company="GameCo",
        experience=[
            {"title": "Founder", "company": "GameCo"},
            {"title": "Engineer", "company": "OldCo"},
        ],
    )


@pytest.mark.asyncio
class TestGenerateOpener:
    async def test_calls_backend_with_user_and_system_prompts(self) -> None:
        gen = MessageGenerator(_make_config())
        with patch(
            "linkedin_worker.messaging.generator._generate_text",
            return_value="Hey Sarah, saw GameCo is cool. Grabbing coffee at GDC?",
        ) as m:
            msg = await gen.generate_opener(_profile())
        assert msg.startswith("Hey Sarah")
        user_prompt, system = m.call_args.args
        assert "Sarah Jones" in user_prompt
        assert "GameCo" in user_prompt
        # Experience summary present
        assert "Founder at GameCo" in user_prompt
        # Default system prompt (GDC) picked when campaign has none
        assert "GDC" in system

    async def test_campaign_system_prompt_takes_precedence(self) -> None:
        gen = MessageGenerator(_make_config(system_prompt="CUSTOM_SYSTEM"))
        with patch(
            "linkedin_worker.messaging.generator._generate_text",
            return_value="hi",
        ) as m:
            await gen.generate_opener(_profile())
        _, system = m.call_args.args
        assert system == "CUSTOM_SYSTEM"

    async def test_strips_wrapping_double_quotes(self) -> None:
        gen = MessageGenerator(_make_config())
        with patch(
            "linkedin_worker.messaging.generator._generate_text",
            return_value='"Hey Sarah, cool work."',
        ):
            msg = await gen.generate_opener(_profile())
        assert msg == "Hey Sarah, cool work."

    async def test_strips_em_dashes(self) -> None:
        gen = MessageGenerator(_make_config())
        with patch(
            "linkedin_worker.messaging.generator._generate_text",
            return_value="Hey Sarah — cool work",
        ):
            msg = await gen.generate_opener(_profile())
        assert "—" not in msg


class TestGenerateTextRouting:
    def test_missing_api_key_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("USE_CLAUDE_CLI", raising=False)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            _generate_text("user", "sys")

    def test_use_claude_cli_routes_to_subprocess(self, monkeypatch) -> None:
        monkeypatch.setenv("USE_CLAUDE_CLI", "1")
        with patch(
            "linkedin_worker.messaging.generator._call_claude_cli",
            return_value="cli-result",
        ) as cli_mock, patch(
            "linkedin_worker.messaging.generator._call_anthropic_api",
            return_value="api-result",
        ) as api_mock:
            result = _generate_text("user", "sys")
        assert result == "cli-result"
        assert cli_mock.call_count == 1
        assert api_mock.call_count == 0

    def test_default_routes_to_api(self, monkeypatch) -> None:
        monkeypatch.delenv("USE_CLAUDE_CLI", raising=False)
        with patch(
            "linkedin_worker.messaging.generator._call_anthropic_api",
            return_value="api-result",
        ) as api_mock:
            result = _generate_text("user", "sys")
        assert result == "api-result"
        assert api_mock.call_count == 1

    def test_api_response_extraction(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        class FakeContent:
            def __init__(self, text): self.text = text

        class FakeResp:
            content = [FakeContent("  hey hi  ")]

        class FakeClient:
            def __init__(self, api_key): pass
            class messages:
                @staticmethod
                def create(**kwargs): return FakeResp()

        with patch("linkedin_worker.messaging.generator.anthropic.Anthropic", FakeClient):
            from linkedin_worker.messaging.generator import _call_anthropic_api
            out = _call_anthropic_api("u", "s")
        assert out == "hey hi"
