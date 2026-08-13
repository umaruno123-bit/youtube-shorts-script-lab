"""チャンネルごとの動画メタデータ・台本を保存するSQLiteレイヤー。"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    channel_slug TEXT NOT NULL,
    title TEXT,
    url TEXT,
    duration_sec INTEGER,
    view_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    upload_date TEXT,
    description TEXT,
    transcript TEXT,
    transcript_source TEXT,
    transcript_lang TEXT,
    engagement_score REAL,
    fetched_at TEXT,
    transcribed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_slug);
"""


def slugify(channel_handle: str) -> str:
    """'@Some Handle' のようなチャンネル指定をフォルダ名に使える形に変換する。"""
    slug = channel_handle.strip().lstrip("@")
    slug = re.sub(r"[^\w\-]+", "_", slug, flags=re.UNICODE).strip("_")
    return slug.lower() or "channel"


def db_path_for(data_dir: Path, channel_slug: str) -> Path:
    channel_dir = data_dir / channel_slug
    channel_dir.mkdir(parents=True, exist_ok=True)
    return channel_dir / "shortslab.db"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_video(conn: sqlite3.Connection, video: dict[str, Any]) -> None:
    """fetch.pyが取得したメタデータをinsertまたはupdateする。台本情報は上書きしない。"""
    existing = get_video(conn, video["id"])
    fetched_at = _now()
    if existing is None:
        conn.execute(
            """
            INSERT INTO videos (
                id, channel_slug, title, url, duration_sec,
                view_count, like_count, comment_count, upload_date,
                description, fetched_at
            ) VALUES (:id, :channel_slug, :title, :url, :duration_sec,
                :view_count, :like_count, :comment_count, :upload_date,
                :description, :fetched_at)
            """,
            {**video, "fetched_at": fetched_at},
        )
    else:
        conn.execute(
            """
            UPDATE videos SET
                title = :title,
                url = :url,
                duration_sec = :duration_sec,
                view_count = :view_count,
                like_count = :like_count,
                comment_count = :comment_count,
                upload_date = :upload_date,
                description = :description,
                fetched_at = :fetched_at
            WHERE id = :id
            """,
            {**video, "fetched_at": fetched_at},
        )
    conn.commit()


def get_video(conn: sqlite3.Connection, video_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()


def list_videos(
    conn: sqlite3.Connection,
    only_missing_transcript: bool = False,
    order_by: str = "view_count DESC",
) -> list[sqlite3.Row]:
    query = "SELECT * FROM videos"
    if only_missing_transcript:
        query += " WHERE transcript IS NULL OR transcript = ''"
    query += f" ORDER BY {order_by}"
    return conn.execute(query).fetchall()


def update_transcript(
    conn: sqlite3.Connection,
    video_id: str,
    transcript: str,
    source: str,
    lang: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE videos SET transcript = ?, transcript_source = ?,
            transcript_lang = ?, transcribed_at = ?
        WHERE id = ?
        """,
        (transcript, source, lang, _now(), video_id),
    )
    conn.commit()


def recompute_engagement_scores(conn: sqlite3.Connection) -> None:
    rows: Iterable[sqlite3.Row] = conn.execute(
        "SELECT id, view_count, like_count, comment_count FROM videos"
    ).fetchall()
    for row in rows:
        views = row["view_count"] or 0
        score = (row["like_count"] or 0) + (row["comment_count"] or 0)
        score = (score / views) if views else 0.0
        conn.execute(
            "UPDATE videos SET engagement_score = ? WHERE id = ?", (score, row["id"])
        )
    conn.commit()
