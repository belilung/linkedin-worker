"""End-to-end smoke tests for the Click CLI (no browser, no network)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from linkedin_worker import cli as cli_mod
from linkedin_worker.scraper.models import (
    ConnectCandidate,
    FitRating,
    OutreachCandidate,
    ProfileData,
)
from linkedin_worker.tracking.store import TrackingStore


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "data" / "tracking.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = TrackingStore(db_path)
    store.initialize()
    store.record_outreach(
        OutreachCandidate(
            profile=ProfileData(name="Jane", profile_url="https://www.linkedin.com/in/jane"),
            fit_rating=FitRating.STRONG,
            fit_reason="founder",
            generated_message="hey",
            message_sent=True,
            sent_at=datetime.utcnow(),
        ),
        campaign="test",
    )
    store.record_connect_outreach(
        ConnectCandidate(
            profile_url="https://www.linkedin.com/in/max",
            name="Max",
            comment_posted=True,
            is_gdc_post=True,
        ),
        campaign="test",
    )
    store.close()
    return db_path


def _write_config(tmp_path: Path, extra: dict | None = None) -> Path:
    cfg_path = tmp_path / "config.yaml"
    data = {
        "campaign": {"name": "t", "search_url": "https://x/search"},
        "session": {"headless": True, "batch_size": 1},
    }
    if extra:
        data.update(extra)
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return cfg_path


class TestHelp:
    def test_top_level_help(self, runner: CliRunner) -> None:
        res = runner.invoke(cli_mod.main, ["--help"])
        assert res.exit_code == 0
        assert "login" in res.output
        assert "run" in res.output
        assert "export" in res.output
        assert "status" in res.output

    @pytest.mark.parametrize("sub", ["login", "run", "connect", "dm-recent", "status", "export"])
    def test_subcommand_help(self, runner: CliRunner, sub: str) -> None:
        res = runner.invoke(cli_mod.main, [sub, "--help"])
        assert res.exit_code == 0, f"{sub} --help failed: {res.output}"


class TestStatusCommand:
    def test_status_on_seeded_db(
        self, runner: CliRunner, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_db(tmp_path)
        cfg = _write_config(tmp_path)
        res = runner.invoke(cli_mod.main, ["status", "--config", str(cfg)])
        assert res.exit_code == 0, res.output
        # stats table should contain something with our seeded numbers
        assert "1" in res.output  # at least one message/comment

    def test_status_no_db(self, runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cfg = _write_config(tmp_path)
        res = runner.invoke(cli_mod.main, ["status", "--config", str(cfg)])
        assert res.exit_code == 0, res.output


class TestExportCommand:
    def test_export_to_csv(self, runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_db(tmp_path)
        cfg = _write_config(tmp_path)
        out = tmp_path / "out.csv"
        res = runner.invoke(
            cli_mod.main,
            ["export", "--config", str(cfg), "--output", str(out)],
        )
        assert res.exit_code == 0, res.output
        assert out.exists()
        content = out.read_text()
        assert "profile_url" in content
        assert "jane" in content.lower()


class TestRunWithoutLogin:
    def test_run_no_search_url_errors_gracefully(
        self, runner: CliRunner, tmp_path: Path, monkeypatch
    ) -> None:
        """Calling run with no search_url must hit early-return, never touch browser."""
        monkeypatch.chdir(tmp_path)
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            yaml.safe_dump({"campaign": {"name": "empty"}}),
            encoding="utf-8",
        )

        # Guard: if browser is ever started, fail loudly.
        browser_started = []
        from linkedin_worker import cli as cli_module

        def _raise(*_a, **_kw):
            browser_started.append(True)
            raise AssertionError("Browser should not start when search_url missing")

        monkeypatch.setattr(cli_module.LinkedInSession, "start", _raise)

        res = runner.invoke(
            cli_module.main,
            ["run", "--config", str(cfg_path), "--dry-run"],
        )
        assert res.exit_code == 0, res.output
        assert not browser_started, "Pipeline leaked into browser startup"
