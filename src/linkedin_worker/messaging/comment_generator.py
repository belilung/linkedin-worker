"""Comment generation via Claude CLI (claude command)."""

from __future__ import annotations

from linkedin_worker.messaging.comment_prompts import (
    COMMENT_SYSTEM_PROMPT_ART_OUTSOURCE,
    COMMENT_SYSTEM_PROMPT_CONTEXTUAL,
    COMMENT_SYSTEM_PROMPT_GDC,
    build_comment_prompt_art_outsource,
    build_comment_prompt_contextual,
    build_comment_prompt_gdc,
)
from linkedin_worker.messaging.generator import _generate_text
from linkedin_worker.utils.logging import log

# Patterns that indicate Claude refused to write a comment.
# These must never reach LinkedIn as actual comments. We only use unambiguous
# first-person refusal phrases; bare substrings like "policy" or "ethical"
# create false positives on legitimate business comments.
_AI_REFUSAL_PATTERNS = [
    "i can't",
    "i cannot",
    "i won't",
    "i will not",
    "i'm unable",
    "i am unable",
    "as an ai",
    "language model",
    "i'm sorry, but i",
    "i'm sorry, i",
    "i apologize, but",
    "guidelines prevent",
    "against my guidelines",
    "violates my",
    "cannot generate",
    "cannot create",
    "cannot write",
    "unable to generate",
    "unable to create",
    "unable to write",
    "not appropriate for me",
]


class CommentGenerator:
    """Generates LinkedIn comments using Claude CLI."""

    async def generate_gdc_comment(
        self, post_text: str, author_name: str,
    ) -> str:
        """Generate a comment for a GDC-related post."""
        user_prompt = build_comment_prompt_gdc(post_text, author_name)
        log.debug(f"Generating GDC comment for {author_name}...")
        comment = _generate_text(user_prompt, COMMENT_SYSTEM_PROMPT_GDC)
        return _clean_comment(comment)

    async def generate_contextual_comment(
        self, post_text: str, author_name: str, author_headline: str = "",
    ) -> str:
        """Generate a contextual comment for any post."""
        user_prompt = build_comment_prompt_contextual(
            post_text, author_name, author_headline,
        )
        log.debug(f"Generating contextual comment for {author_name}...")
        comment = _generate_text(user_prompt, COMMENT_SYSTEM_PROMPT_CONTEXTUAL)
        return _clean_comment(comment)

    async def generate_art_outsource_comment(
        self, post_text: str, author_name: str, author_headline: str = "",
    ) -> str:
        """Generate a comment for a game art outsourcing post."""
        user_prompt = build_comment_prompt_art_outsource(
            post_text, author_name, author_headline,
        )
        log.debug(f"Generating art outsource comment for {author_name}...")
        comment = _generate_text(user_prompt, COMMENT_SYSTEM_PROMPT_ART_OUTSOURCE)
        return _clean_comment(comment)


def _clean_comment(comment: str) -> str:
    """Clean up generated comment text. Returns empty string for SKIP signals."""
    stripped = comment.strip()
    # Claude returns "SKIP" when the post isn't relevant
    if stripped.upper() == "SKIP":
        return ""
    # Detect AI refusals — these must never go out as actual comments
    lower = stripped.lower()
    if any(pattern in lower for pattern in _AI_REFUSAL_PATTERNS):
        log.warning("AI refusal detected in generated comment, skipping.")
        return ""
    if stripped.startswith('"') and stripped.endswith('"'):
        stripped = stripped[1:-1]
    # Remove em dashes regardless of what the prompt said
    stripped = stripped.replace(" -- ", ", ").replace(" - ", ", ")
    stripped = stripped.replace(" — ", ", ").replace("—", ",")
    return stripped
