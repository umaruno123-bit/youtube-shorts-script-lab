"""再生数・エンゲージメントで動画をランキングし、Markdownレポートを出力する。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from . import store

METRIC_COLUMNS = {
    "views": "view_count",
    "engagement": "engagement_score",
}


def top_videos(
    conn: sqlite3.Connection, top: int = 20, metric: str = "views"
) -> list[sqlite3.Row]:
    column = METRIC_COLUMNS.get(metric, "view_count")
    store.recompute_engagement_scores(conn)
    rows = conn.execute(
        f"""
        SELECT * FROM videos
        WHERE transcript IS NOT NULL AND transcript != ''
        ORDER BY {column} DESC
        LIMIT ?
        """,
        (top,),
    ).fetchall()
    return rows


def render_ranking_markdown(
    rows: list[sqlite3.Row], channel: str, metric: str, full: bool = False
) -> str:
    lines = [
        f"# {channel} Shorts 人気ランキング ({metric})",
        "",
        f"生成日時: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    for i, row in enumerate(rows, start=1):
        transcript = (row["transcript"] or "").strip()
        lines += [
            f"## {i}. {row['title']}",
            f"- URL: {row['url']}",
            f"- 再生数: {row['view_count']:,} / いいね: {row['like_count']:,} / "
            f"コメント: {row['comment_count']:,} / エンゲージメント: {row['engagement_score']:.4f}",
        ]
        if full:
            lines += ["- 台本:", "```", transcript, "```", ""]
        else:
            snippet = transcript.replace("\n", " ")[:80]
            lines += [f"- 台本冒頭: {snippet}...", ""]
    return "\n".join(lines)


def rank_channel(
    channel: str, data_dir: Path, top: int = 20, metric: str = "views", full: bool = False
) -> Path:
    channel_slug = store.slugify(channel)
    db_path = store.db_path_for(data_dir, channel_slug)
    conn = store.connect(db_path)
    try:
        rows = top_videos(conn, top=top, metric=metric)
        markdown = render_ranking_markdown(rows, channel, metric, full=full)
    finally:
        conn.close()

    reports_dir = data_dir / channel_slug / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"ranking_{datetime.now():%Y%m%d_%H%M%S}.md"
    out_path.write_text(markdown, encoding="utf-8")
    return out_path
