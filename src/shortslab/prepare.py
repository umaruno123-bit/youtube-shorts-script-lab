"""人気動画TOP N の台本と指示書を1つのMarkdownにまとめ、Claude Code(チャット)に
そのまま読ませて「ネタ案+フル台本」を生成させるための入力ファイルを作る。

Anthropic APIキーは不要。Claude Codeが使える環境であれば、出力ファイルを開いて
Claudeに読み込ませるだけでよい。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import store


def _format_video_block(index: int, video: dict) -> str:
    transcript = (video.get("transcript") or "").strip()
    return (
        f"### {index}. {video.get('title')}\n"
        f"- 再生数: {video.get('view_count', 0):,} / いいね: {video.get('like_count', 0):,}\n"
        f"- URL: {video.get('url')}\n"
        f"- 台本:\n```\n{transcript}\n```\n"
    )


def build_claude_brief(
    videos: list[dict],
    channel: str,
    channel_slug: str,
    num_ideas: int,
    num_scripts: int,
) -> str:
    videos_text = "\n".join(
        _format_video_block(i, v) for i, v in enumerate(videos, start=1)
    )
    stamp_hint = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"""# Claude Codeへの依頼: 「{channel}」Shorts 新規ネタ・台本の生成

このファイルは `shortslab prepare` が自動生成したものです。
以下は「{channel}」の人気YouTube Shorts動画TOP{len(videos)}(再生数順)の実際の台本です。
これを分析し、下記の3つのタスクを行ってください。

## 入力データ: 人気動画TOP{len(videos)}の台本

{videos_text}

## タスク

1. **パターン分析**: 上記の動画に共通する要素を分析し、Markdownでまとめてください。
   - 冒頭フック(最初の1〜3秒)の型
   - 全体の構成・展開の型
   - 話し方・トーン・口調の特徴
   - 締め方・CTA(視聴継続やチャンネル登録を促す言い回し)の傾向
   - 再生数が特に高い動画に共通する要素の仮説
2. **ネタ案生成**: パターン分析を踏まえ、このチャンネルで新しく投稿したら再生される
   可能性が高い企画案を{num_ideas}件、考えてください。既存動画の焼き直しではなく、
   同じ「型」を新しい切り口・テーマに応用したオリジナル案にしてください。
   各案について「タイトル案」「冒頭フックのセリフ例」「企画概要(2〜3文)」を書いてください。
3. **フル台本化**: 2で出したネタ案のうち{num_scripts}件について、そのまま撮影・
   ナレーションに使えるレベルのShorts台本(尺目安30〜60秒)を作成してください。
   構成は「【フック】」「【本編】」「【締め・CTA】」「尺の目安(秒数)」としてください。

## 出力先(実際にファイルを書き出してください)

- 1(パターン分析)と2(ネタ案)を合わせて:
  `data/{channel_slug}/reports/ideas_{stamp_hint}.md`
- 3(フル台本)を:
  `data/{channel_slug}/reports/scripts_{stamp_hint}.md`

## 注意

- 既存動画の台本をそのまま複製せず、構造やパターンを抽出したオリジナルの
  コンテンツを作成してください(著作権配慮のため)。
- 日本語で出力してください。
"""


def prepare_for_channel(
    channel: str,
    data_dir: Path,
    top: int = 15,
    num_ideas: int = 10,
    num_scripts: int = 5,
) -> Path:
    channel_slug = store.slugify(channel)
    db_path = store.db_path_for(data_dir, channel_slug)
    conn = store.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT title, url, view_count, like_count, transcript FROM videos
            WHERE transcript IS NOT NULL AND transcript != ''
            ORDER BY view_count DESC LIMIT ?
            """,
            (top,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise RuntimeError(
            "台本が保存された動画がありません。先に `fetch` と `transcribe` を実行してください。"
        )

    videos = [dict(row) for row in rows]
    brief = build_claude_brief(videos, channel, channel_slug, num_ideas, num_scripts)

    reports_dir = data_dir / channel_slug / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"claude_brief_{datetime.now():%Y%m%d_%H%M%S}.md"
    out_path.write_text(brief, encoding="utf-8")
    return out_path
