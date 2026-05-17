"""Message generation via Anthropic API (default) or Claude CLI (fallback).

Set USE_CLAUDE_CLI=1 to use Claude Code CLI instead of the API.
"""

from __future__ import annotations

import os
import subprocess

import anthropic

from linkedin_worker.config import AppConfig
from linkedin_worker.messaging.prompts import SYSTEM_PROMPT, build_user_prompt
from linkedin_worker.scraper.models import ProfileData
from linkedin_worker.utils.logging import log

# Default model for Anthropic API
DEFAULT_MODEL = "claude-sonnet-4-20250514"


class MessageGenerator:
    """Generates personalized LinkedIn DMs using Anthropic API or Claude CLI."""

    def __init__(self, config: AppConfig):
        self.config = config

    async def generate_opener(self, profile: ProfileData) -> str:
        """Generate a personalized first-touch message for a profile."""
        experience_summary = ""
        if profile.experience:
            lines = []
            for exp in profile.experience[:3]:
                title = exp.get("title", "")
                company = exp.get("company", "")
                if title and company:
                    lines.append(f"{title} at {company}")
                elif title:
                    lines.append(title)
            experience_summary = "; ".join(lines)

        user_prompt = build_user_prompt(
            name=profile.name,
            headline=profile.headline,
            about=profile.about,
            current_company=profile.current_company,
            current_title=profile.current_title,
            experience_summary=experience_summary,
            tone=self.config.voice.tone,
            sample_message=self.config.voice.sample_message,
            campaign_context=self.config.campaign.context,
        )

        log.debug(f"Generating message for {profile.name}...")

        system = self.config.campaign.system_prompt or SYSTEM_PROMPT
        message = _generate_text(user_prompt, system)

        # Strip any quotes the model might wrap around the message
        if message.startswith('"') and message.endswith('"'):
            message = message[1:-1]

        # Replace em dashes with commas (AI tell)
        message = message.replace(" — ", ", ").replace("—", ",")

        return message


def _generate_text(user_prompt: str, system_prompt: str) -> str:
    """Route to API or CLI based on USE_CLAUDE_CLI env var."""
    if os.environ.get("USE_CLAUDE_CLI", "").strip() == "1":
        return _call_claude_cli(user_prompt, system_prompt)
    return _call_anthropic_api(user_prompt, system_prompt)


# ---------------------------------------------------------------------------
# Backend 1: Anthropic API (default) — works anywhere with ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------

def _call_anthropic_api(user_prompt: str, system_prompt: str) -> str:
    """Call Anthropic API directly via SDK."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. "
            "Get your key at https://console.anthropic.com/settings/keys"
        )

    client = anthropic.Anthropic(api_key=api_key)
    log.debug("Calling Anthropic API...")

    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=256,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if not response.content:
        raise RuntimeError("Anthropic API returned empty content")
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Backend 2: Claude CLI — requires Claude Code installed
# Set USE_CLAUDE_CLI=1 to use this instead of the API
# ---------------------------------------------------------------------------

def _call_claude_cli(
    user_prompt: str,
    system_prompt: str,
    model: str = "sonnet",
    timeout_seconds: int = 120,
) -> str:
    """Call claude CLI in non-interactive print mode."""
    cmd = [
        "claude",
        "-p", user_prompt,
        "--system-prompt", system_prompt,
        "--model", model,
        "--output-format", "text",
        "--no-session-persistence",
        "--tools", "",
    ]

    log.debug("Calling claude CLI...")

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("ANTHROPIC_API_KEY", None)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Claude CLI error (code {result.returncode}): {error_msg}")

    return result.stdout.strip()
