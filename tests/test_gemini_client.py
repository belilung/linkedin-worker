"""Unit tests for Gemini fallback client."""

from __future__ import annotations

import io
import json
from unittest.mock import patch, MagicMock

import pytest

from linkedin_worker.messaging import gemini_client


class TestCallGemini:
    def test_missing_api_key_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            gemini_client.call_gemini("u", "s")

    def test_successful_call_returns_text(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        body = {
            "candidates": [
                {"content": {"parts": [{"text": "hello from gemini"}]}}
            ]
        }
        fake_resp = MagicMock()
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)
        fake_resp.read = MagicMock(return_value=json.dumps(body).encode("utf-8"))

        with patch("urllib.request.urlopen", return_value=fake_resp):
            result = gemini_client.call_gemini("u", "s")
        assert result == "hello from gemini"

    def test_rate_limited_raises_runtimeerror(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        import urllib.error

        err = urllib.error.HTTPError(
            url="u", code=429, msg="too many", hdrs=None,
            fp=io.BytesIO(b"rate limit"),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(RuntimeError, match="rate limited"):
                gemini_client.call_gemini("u", "s")

    def test_http_error_raises_with_status(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        import urllib.error

        err = urllib.error.HTTPError(
            url="u", code=500, msg="server", hdrs=None,
            fp=io.BytesIO(b"boom"),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(RuntimeError, match="500"):
                gemini_client.call_gemini("u", "s")
