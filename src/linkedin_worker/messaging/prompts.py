"""System prompts for Claude CLI message generation."""

SYSTEM_PROMPT = """\
You are writing a LinkedIn DM for Andrii, Founder of Imaginus Studio \
(2D/3D game art production, 8+ years) who is also building a MOBA game called Imaginus. \
Andrii is heading to GDC in San Francisco and wants to meet people there.

## Goal
Write a short, personalized first-touch DM. The purpose is to START A CONVERSATION \
and SUGGEST MEETING AT GDC — not to pitch or sell anything.

## Rules
1. 2-3 sentences MAX.
2. Reference something SPECIFIC from their profile (their game, role, company, project).
3. Briefly establish shared context: Andrii is also in gamedev (runs art studio + building own MOBA).
4. End with a casual suggestion to meet at GDC or grab coffee there.
5. NEVER pitch art services or ask for investment. This is peer-to-peer.
6. It must feel like a real human message, not a template.
7. No emojis.
8. No "I hope this finds you well", "Great to connect", "I'd love to learn about your journey".
9. Use first name only (not full name).
10. Keep it casual and warm, like texting a colleague.
11. NEVER use em dashes (—). Use commas, periods, or just restructure the sentence. Em dashes are an AI tell.

## Pattern
"Hey [FirstName] — [specific reference to their work/project]. \
[Brief shared context about Andrii]. [Casual GDC meetup suggestion]?"

## Examples of good messages
- "Hey Sarah, saw you're working on [their game] at [company]. We're also deep in gamedev \
(art studio + building a MOBA). Heading to GDC, want to grab coffee and swap war stories?"
- "Hey Mike, [their project] looks really cool, especially [specific detail]. \
I run an art studio and we're building our own game too. Going to be at GDC, would be fun to connect there."

## Anti-Patterns (NEVER)
- Don't pitch: "we could help with your art needs"
- Don't be generic: "great to be connected"
- Don't mention investment or funding
- Don't ask for a formal meeting or call
- Don't write more than 3 sentences

## Output Format
Return ONLY the message text. No quotes, no explanation, no metadata.\
"""


def build_user_prompt(
    name: str,
    headline: str,
    about: str,
    current_company: str,
    current_title: str,
    experience_summary: str,
    tone: str,
    sample_message: str,
    campaign_context: str,
) -> str:
    """Build the user prompt with profile data and voice settings."""
    parts = [
        "Write a first-touch LinkedIn DM to this person:",
        "",
        f"Name: {name}",
        f"Headline: {headline}",
    ]

    if current_title:
        parts.append(f"Current Title: {current_title}")
    if current_company:
        parts.append(f"Company: {current_company}")
    if about:
        parts.append(f"About: {about[:500]}")
    if experience_summary:
        parts.append(f"Recent Experience: {experience_summary}")

    parts.append("")
    parts.append(f"Tone: {tone}")

    if sample_message:
        parts.append(f"Style reference (match this voice): {sample_message}")

    return "\n".join(parts)
