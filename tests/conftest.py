"""Shared fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Ensure no real network / external credentials leak into tests.
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("USE_CLAUDE_CLI", None)


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "tracking.db"
