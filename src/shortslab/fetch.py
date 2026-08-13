"""yt-dlpを使い、チャンネルのShorts一覧とメタデータを取得してDBに保存する。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yt_dlp
from tqdm import tqdm

from . import net, store

# 動画1本ごとの処理間隔(秒)。YouTube側のレート制限(HTTP 429)を避けるための最低限のマナー。
REQUEST_INTERVAL_SEC = 1.5


def normalize_channel_url(channel: str) -> str:
    """'@handle' / 'handle' / チャンネルURL / チャンネルID を Shorts タブのURLに正規化する。"""
    channel = channel.strip()
    if channel.startswith("http://") or channel.startswith("https://"):
        base = channel.rstrip("/")
        if base.endswith("/shorts"):
            return base
        return f"{base}/shorts"
    if channel.startswith("UC") and " " not in channel:
        return f"https://www.youtube.com/channel/{channel}/shorts"
    handle = channel if channel.startswith("@") else f"@{channel}"
    return f"https://www.youtube.com/{handle}/shorts"


def list_shorts_ids(channel: str, limit: int | None = None) -> list[str]:
    """Shortsタブを軽量(flat)展開して動画IDの一覧を返す。"""
    url = normalize_channel_url(channel)
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "sleep_interval_requests": 1,
    }

    def _run() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    info = net.with_backoff(_run)
    entries = info.get("entries") or [] if info else []
    ids = [e["id"] for e in entries if e and e.get("id")]
    if limit:
        ids = ids[:limit]
    return ids


def fetch_video_metadata(video_id: str) -> dict[str, Any]:
    """1本の動画の詳細メタデータ(再生数・いいね数・字幕情報など)を取得する。
    429(レート制限)を受けた場合は間隔を空けて自動リトライする。"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "sleep_interval_requests": 1,
    }

    def _run() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    return net.with_backoff(_run)


def _to_video_row(info: dict[str, Any], channel_slug: str) -> dict[str, Any]:
    return {
        "id": info["id"],
        "channel_slug": channel_slug,
        "title": info.get("title"),
        "url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={info['id']}",
        "duration_sec": info.get("duration"),
        "view_count": info.get("view_count") or 0,
        "like_count": info.get("like_count") or 0,
        "comment_count": info.get("comment_count") or 0,
        "upload_date": info.get("upload_date"),
        "description": info.get("description"),
    }


def fetch_channel(
    channel: str,
    data_dir: Path,
    limit: int | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """チャンネルのShortsを一覧し、新規/更新分をDBに保存する。"""
    channel_slug = store.slugify(channel)
    db_path = store.db_path_for(data_dir, channel_slug)
    conn = store.connect(db_path)
    try:
        ids = list_shorts_ids(channel, limit=limit)
        new_count = 0
        for video_id in tqdm(ids, desc=f"fetching metadata ({channel_slug})"):
            if not refresh and store.get_video(conn, video_id) is not None:
                continue
            info = fetch_video_metadata(video_id)
            store.upsert_video(conn, _to_video_row(info, channel_slug))
            new_count += 1
            time.sleep(REQUEST_INTERVAL_SEC)
        store.recompute_engagement_scores(conn)
    finally:
        conn.close()
    return {"channel_slug": channel_slug, "total_found": len(ids), "new_or_updated": new_count}
