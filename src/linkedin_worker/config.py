"""Configuration loading from YAML + environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TypeVar

import yaml
from dotenv import load_dotenv

T = TypeVar("T")


def _filter_known(cls: type[T], data: dict) -> dict:
    """Drop keys not declared on the dataclass to stay forward-compatible."""
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in known}


@dataclass
class CampaignConfig:
    name: str = "default"
    search_url: str = ""
    context: str = ""
    system_prompt: str = ""
    require_profile_keyword: str = ""


@dataclass
class ICPConfig:
    strong_titles: list[str] = field(default_factory=lambda: [
        "Owner", "Founder", "CEO", "President", "Partner", "Director",
    ])
    maybe_titles: list[str] = field(default_factory=lambda: [
        "Consultant", "Advisor", "Manager", "Head of", "Freelance",
    ])
    skip_titles: list[str] = field(default_factory=lambda: [
        "Intern", "Student", "Associate", "Assistant", "Junior",
    ])
    skip_signals: list[str] = field(default_factory=lambda: [
        "Open to work", "Seeking opportunities", "Looking for",
    ])


@dataclass
class VoiceConfig:
    tone: str = "casual"
    sample_message: str = ""


@dataclass
class SessionConfig:
    batch_size: int = 10
    min_delay_seconds: int = 45
    max_delay_seconds: int = 120
    screenshot_on_error: bool = True
    headless: bool = True
    connections_cache_hours: int = 24
    max_search_pages: int = 10
    max_connects_per_day: int = 20
    max_comments_per_day: int = 25


@dataclass
class ConnectCampaignConfig:
    keywords: list[str] = field(default_factory=lambda: ["GDC"])
    people_search_keywords: list[str] = field(default_factory=lambda: [
        "GDC",
    ])
    use_content_search: bool = True
    use_people_search: bool = True
    max_content_search_pages: int = 5
    max_people_search_pages: int = 5
    gdc_keywords: list[str] = field(default_factory=lambda: [
        "gdc", "game developers conference",
    ])
    # "gdc" | "art_outsource" | "buyer_intent"
    campaign_mode: str = "gdc"
    # Keywords used to decide relevance in art_outsource mode
    relevance_keywords: list[str] = field(default_factory=list)
    # LinkedIn geoUrn for geo-filtered search (e.g. "103644278" = US)
    geo_urn: str = ""
    # LinkedIn industry code for people search filter (e.g. "5" = Computer Games)
    industry_code: str = ""
    # buyer_intent mode: post MUST contain at least one of these
    buyer_intent_keywords: list[str] = field(default_factory=list)
    # buyer_intent mode: post containing ANY of these → skip
    buyer_skip_keywords: list[str] = field(default_factory=list)
    # buyer_intent mode: profile location strings indicating Russian origin → skip
    russian_location_signals: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    campaign: CampaignConfig = field(default_factory=CampaignConfig)
    icp: ICPConfig = field(default_factory=ICPConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    connect_campaign: ConnectCampaignConfig = field(default_factory=ConnectCampaignConfig)
    anthropic_api_key: str = ""
    data_dir: Path = field(default_factory=lambda: Path("data"))


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load configuration from YAML file and environment variables."""
    load_dotenv()

    config = AppConfig()

    # Load YAML if it exists
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        if "campaign" in raw:
            config.campaign = CampaignConfig(**_filter_known(CampaignConfig, raw["campaign"]))
        if "icp" in raw:
            config.icp = ICPConfig(**_filter_known(ICPConfig, raw["icp"]))
        if "voice" in raw:
            config.voice = VoiceConfig(**_filter_known(VoiceConfig, raw["voice"]))
        if "session" in raw:
            config.session = SessionConfig(**_filter_known(SessionConfig, raw["session"]))
        if "connect_campaign" in raw:
            config.connect_campaign = ConnectCampaignConfig(
                **_filter_known(ConnectCampaignConfig, raw["connect_campaign"])
            )

    # Environment variables override
    config.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")

    # Ensure data directories exist
    config.data_dir.mkdir(parents=True, exist_ok=True)
    (config.data_dir / "cookies").mkdir(exist_ok=True)
    (config.data_dir / "screenshots").mkdir(exist_ok=True)

    return config
