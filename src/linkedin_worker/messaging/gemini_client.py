"""Gemini API client for text generation (cost-effective alternative to Claude)."""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error

from linkedin_worker.utils.logging import log

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


def call_gemini(user_prompt: str, system_prompt: str, timeout: int = 60) -> str:
    """Call Gemini Flash API directly via urllib (no SDK needed)."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    url = f"{GEMINI_API_URL}?key={api_key}"

    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "parts": [{"text": user_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 256,
        }
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            log.debug(f"Gemini response: {text[:100]}...")
            return text.strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 429:
            raise RuntimeError(f"Gemini rate limited (429). Falling back.")
        raise RuntimeError(f"Gemini API error {e.code}: {body[:300]}")
    except Exception as e:
        raise RuntimeError(f"Gemini API call failed: {e}")
