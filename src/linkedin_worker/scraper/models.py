"""Data models for scraped LinkedIn data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


@dataclass
class SearchResult:
    """A person found in LinkedIn search results."""
    name: str
    profile_url: str
    headline: str = ""
    connection_degree: str = ""


@dataclass
class ConnectionEntry:
    """A 1st-degree connection from the user's network."""
    name: str
    profile_url: str
    headline: str = ""


@dataclass
class ProfileData:
    """Full profile data scraped from a LinkedIn profile page."""
    name: str
    profile_url: str
    headline: str = ""
    location: str = ""
    about: str = ""
    current_company: str = ""
    experience: list[dict] = field(default_factory=list)

    @property
    def current_title(self) -> str:
        """Extract current title from experience or headline."""
        if self.experience:
            return self.experience[0].get("title", "")
        return self.headline.split(" at ")[0].split(" | ")[0].strip()


class FitRating(Enum):
    STRONG = "strong"
    MAYBE = "maybe"
    SKIP = "skip"


@dataclass
class OutreachCandidate:
    """A candidate ready for outreach with all data assembled."""
    profile: ProfileData
    fit_rating: FitRating
    fit_reason: str
    generated_message: str = ""
    message_sent: bool = False
    sent_at: datetime | None = None


@dataclass
class PostData:
    """A post scraped from a LinkedIn profile's activity feed."""
    post_url: str
    author_name: str
    author_profile_url: str
    text: str
    is_gdc_related: bool = False
    timestamp_text: str = ""


@dataclass
class ContentSearchResult:
    """A post found via LinkedIn content search."""
    post_url: str
    post_text: str
    author_name: str
    author_profile_url: str
    author_headline: str = ""


@dataclass
class ConnectCandidate:
    """A candidate for the connect+comment outreach pipeline."""
    profile_url: str
    name: str
    headline: str = ""
    post_url: str = ""
    post_text: str = ""
    is_gdc_post: bool = False
    comment_text: str = ""
    comment_posted: bool = False
    connect_sent: bool = False
    source: str = ""  # "content_search" or "people_search"


def normalize_linkedin_url(url: str) -> str:
    """Normalize a LinkedIn profile URL for consistent comparison."""
    if not url:
        return ""
    url = url.split("?")[0].rstrip("/")
    lowered = url.lower()
    if lowered.startswith("http://"):
        url = "https://" + url[len("http://"):]
    elif lowered.startswith("https://"):
        pass
    else:
        url = f"https://www.linkedin.com{url}"
    return url.lower()
