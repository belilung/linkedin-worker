"""SQLite tracking store for outreach dedup, stats, and export."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from linkedin_worker.scraper.models import ConnectionEntry, ConnectCandidate, OutreachCandidate
from linkedin_worker.utils.logging import log

SCHEMA = """
CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_url TEXT NOT NULL,
    name TEXT NOT NULL,
    headline TEXT,
    company TEXT,
    fit_rating TEXT,
    fit_reason TEXT,
    message TEXT,
    message_sent INTEGER DEFAULT 0,
    sent_at TIMESTAMP,
    campaign TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_profile_url
    ON outreach(profile_url);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_url TEXT NOT NULL,
    error TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS connections_cache (
    profile_url TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    headline TEXT,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS connect_outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_url TEXT NOT NULL,
    name TEXT NOT NULL,
    headline TEXT,
    post_url TEXT,
    post_text TEXT,
    is_gdc_post INTEGER DEFAULT 0,
    comment_text TEXT,
    comment_posted INTEGER DEFAULT 0,
    connect_sent INTEGER DEFAULT 0,
    source TEXT,
    campaign TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_connect_outreach_profile_url
    ON connect_outreach(profile_url);
"""


class TrackingStore:
    """SQLite-backed tracking for outreach dedup, stats, and connections caching."""

    def __init__(self, db_path: str | Path = "data/tracking.db"):
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        log.info(f"Tracking DB initialized at {self.db_path}")

    def _ensure_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("Store not initialized. Call initialize() first.")
        return self.conn

    def was_already_messaged(self, profile_url: str) -> bool:
        """Check if this profile was already messaged."""
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT 1 FROM outreach WHERE profile_url = ? AND message_sent = 1",
            (profile_url,),
        ).fetchone()
        return row is not None

    def record_outreach(self, candidate: OutreachCandidate, campaign: str) -> None:
        """Record a sent or generated message."""
        conn = self._ensure_conn()
        conn.execute(
            """INSERT OR REPLACE INTO outreach
               (profile_url, name, headline, company, fit_rating, fit_reason,
                message, message_sent, sent_at, campaign)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                candidate.profile.profile_url,
                candidate.profile.name,
                candidate.profile.headline,
                candidate.profile.current_company,
                candidate.fit_rating.value,
                candidate.fit_reason,
                candidate.generated_message,
                1 if candidate.message_sent else 0,
                candidate.sent_at.isoformat() if candidate.sent_at else None,
                campaign,
            ),
        )
        conn.commit()

    def record_error(self, profile_url: str, error: str) -> None:
        """Record a failed processing attempt."""
        conn = self._ensure_conn()
        conn.execute(
            "INSERT INTO errors (profile_url, error) VALUES (?, ?)",
            (profile_url, error),
        )
        conn.commit()

    def get_session_stats(self) -> dict:
        """Return counts of messages sent today, this week, and total."""
        conn = self._ensure_conn()
        today = datetime.utcnow().date().isoformat()
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

        total = conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE message_sent = 1"
        ).fetchone()[0]

        today_count = conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE message_sent = 1 AND date(sent_at) = ?",
            (today,),
        ).fetchone()[0]

        week_count = conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE message_sent = 1 AND sent_at >= ?",
            (week_ago,),
        ).fetchone()[0]

        errors = conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]

        dry_run = conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE message_sent = 0"
        ).fetchone()[0]

        return {
            "total": total,
            "today": today_count,
            "this_week": week_count,
            "dry_run": dry_run,
            "errors": errors,
        }

    def cache_connections(self, connections: list[ConnectionEntry]) -> None:
        """Cache the user's connections for fast lookup."""
        conn = self._ensure_conn()
        # Clear old cache
        conn.execute("DELETE FROM connections_cache")
        now = datetime.utcnow().isoformat()
        conn.executemany(
            "INSERT INTO connections_cache (profile_url, name, headline, cached_at) VALUES (?, ?, ?, ?)",
            [(c.profile_url, c.name, c.headline, now) for c in connections],
        )
        conn.commit()
        log.info(f"Cached {len(connections)} connections.")

    def get_cached_connections(self, max_age_hours: int = 24) -> set[str] | None:
        """Return cached connection URLs if fresh enough, else None."""
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT cached_at FROM connections_cache LIMIT 1"
        ).fetchone()

        if row is None:
            return None

        cached_at = datetime.fromisoformat(row[0])
        if datetime.utcnow() - cached_at > timedelta(hours=max_age_hours):
            log.info("Connections cache expired.")
            return None

        rows = conn.execute("SELECT profile_url FROM connections_cache").fetchall()
        return {r[0] for r in rows}

    def was_already_connect_processed(self, profile_url: str) -> bool:
        """Check if this profile was already processed in connect outreach."""
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT 1 FROM connect_outreach WHERE profile_url = ?",
            (profile_url,),
        ).fetchone()
        return row is not None

    def was_post_already_commented(self, post_url: str) -> bool:
        """Check if we already commented on this post URL."""
        if not post_url:
            return False
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT 1 FROM connect_outreach WHERE post_url = ? AND comment_posted = 1",
            (post_url,),
        ).fetchone()
        return row is not None

    def record_connect_outreach(self, candidate: ConnectCandidate, campaign: str) -> None:
        """Record a connect outreach attempt."""
        conn = self._ensure_conn()
        conn.execute(
            """INSERT OR REPLACE INTO connect_outreach
               (profile_url, name, headline, post_url, post_text, is_gdc_post,
                comment_text, comment_posted, connect_sent, source, campaign)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                candidate.profile_url,
                candidate.name,
                candidate.headline,
                candidate.post_url,
                candidate.post_text,
                1 if candidate.is_gdc_post else 0,
                candidate.comment_text,
                1 if candidate.comment_posted else 0,
                1 if candidate.connect_sent else 0,
                candidate.source,
                campaign,
            ),
        )
        conn.commit()

    def get_connect_stats(self) -> dict:
        """Return connect outreach statistics."""
        conn = self._ensure_conn()
        today = datetime.utcnow().date().isoformat()

        total = conn.execute(
            "SELECT COUNT(*) FROM connect_outreach"
        ).fetchone()[0]

        today_count = conn.execute(
            "SELECT COUNT(*) FROM connect_outreach WHERE date(created_at) = ?",
            (today,),
        ).fetchone()[0]

        comments_posted = conn.execute(
            "SELECT COUNT(*) FROM connect_outreach WHERE comment_posted = 1"
        ).fetchone()[0]

        connects_sent = conn.execute(
            "SELECT COUNT(*) FROM connect_outreach WHERE connect_sent = 1"
        ).fetchone()[0]

        gdc_posts = conn.execute(
            "SELECT COUNT(*) FROM connect_outreach WHERE is_gdc_post = 1"
        ).fetchone()[0]

        return {
            "total_processed": total,
            "today": today_count,
            "comments_posted": comments_posted,
            "connects_sent": connects_sent,
            "gdc_posts": gdc_posts,
        }

    def export_csv(self, path: str) -> None:
        """Export outreach log as CSV."""
        conn = self._ensure_conn()
        rows = conn.execute(
            """SELECT profile_url, name, headline, company, fit_rating, fit_reason,
                      message, message_sent, sent_at, campaign, created_at
               FROM outreach ORDER BY created_at DESC"""
        ).fetchall()

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "profile_url", "name", "headline", "company", "fit_rating",
                "fit_reason", "message", "message_sent", "sent_at", "campaign",
                "created_at",
            ])
            for row in rows:
                writer.writerow(list(row))

        log.info(f"Exported {len(rows)} records to {path}")

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
