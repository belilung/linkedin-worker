"""Unit tests for config loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from linkedin_worker.config import (
    AppConfig,
    CampaignConfig,
    ConnectCampaignConfig,
    ICPConfig,
    SessionConfig,
    VoiceConfig,
    load_config,
)


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


class TestDefaults:
    def test_campaign_defaults(self) -> None:
        c = CampaignConfig()
        assert c.name == "default"
        assert c.search_url == ""

    def test_icp_has_sensible_defaults(self) -> None:
        c = ICPConfig()
        assert "Founder" in c.strong_titles
        assert "Intern" in c.skip_titles

    def test_session_defaults_are_safe(self) -> None:
        s = SessionConfig()
        assert s.min_delay_seconds >= 30
        assert s.max_delay_seconds >= s.min_delay_seconds
        assert s.max_connects_per_day <= 30  # LinkedIn safety
        assert s.max_comments_per_day <= 40


class TestLoadConfigFromYaml:
    def test_missing_file_returns_defaults(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cfg = load_config("nonexistent.yaml")
        assert isinstance(cfg, AppConfig)
        assert cfg.campaign.name == "default"

    def test_loads_campaign_section(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        yaml_file = tmp_path / "config.yaml"
        _write_yaml(yaml_file, {
            "campaign": {
                "name": "gdc-2026",
                "search_url": "https://www.linkedin.com/search/",
                "context": "GDC outreach",
            }
        })
        cfg = load_config(str(yaml_file))
        assert cfg.campaign.name == "gdc-2026"
        assert cfg.campaign.context == "GDC outreach"

    def test_loads_session_section(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        yaml_file = tmp_path / "config.yaml"
        _write_yaml(yaml_file, {
            "session": {"batch_size": 25, "headless": False}
        })
        cfg = load_config(str(yaml_file))
        assert cfg.session.batch_size == 25
        assert cfg.session.headless is False

    def test_loads_connect_campaign_full(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        yaml_file = tmp_path / "config.yaml"
        _write_yaml(yaml_file, {
            "connect_campaign": {
                "keywords": ["GDC", "unity"],
                "campaign_mode": "buyer_intent",
                "buyer_intent_keywords": ["hiring", "outsourcing"],
                "buyer_skip_keywords": ["student"],
            }
        })
        cfg = load_config(str(yaml_file))
        assert cfg.connect_campaign.keywords == ["GDC", "unity"]
        assert cfg.connect_campaign.campaign_mode == "buyer_intent"
        assert "hiring" in cfg.connect_campaign.buyer_intent_keywords

    def test_unknown_yaml_keys_do_not_crash(self, tmp_path: Path, monkeypatch) -> None:
        """Extra fields in YAML shouldn't crash load. Forward-compat."""
        monkeypatch.chdir(tmp_path)
        yaml_file = tmp_path / "config.yaml"
        _write_yaml(yaml_file, {
            "campaign": {
                "name": "x",
                "search_url": "y",
                "context": "z",
                "some_future_field": "should_be_ignored",
            }
        })
        # Should not raise
        cfg = load_config(str(yaml_file))
        assert cfg.campaign.name == "x"

    def test_env_var_overrides_api_key(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        cfg = load_config("nonexistent.yaml")
        assert cfg.anthropic_api_key == "test-key-123"

    def test_data_dir_created(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        load_config("nonexistent.yaml")
        assert (tmp_path / "data").exists()
        assert (tmp_path / "data" / "cookies").exists()
        assert (tmp_path / "data" / "screenshots").exists()

    def test_empty_yaml_safe(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("", encoding="utf-8")
        cfg = load_config(str(yaml_file))
        assert isinstance(cfg, AppConfig)


class TestRealProjectConfigs:
    """Smoke-load the real YAMLs shipped in repo root."""

    @pytest.mark.parametrize("name", [
        "config.yaml",
        "config-buyer-intent.yaml",
        "config-gamedev-outsource.yaml",
    ])
    def test_real_config_loads(self, name: str, tmp_path: Path, monkeypatch) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        src = repo_root / name
        if not src.exists():
            pytest.skip(f"{name} not present")
        # copy to a tmp dir so data/ doesn't pollute repo
        dst = tmp_path / name
        dst.write_text(src.read_text(), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        cfg = load_config(str(dst))
        assert isinstance(cfg, AppConfig)
