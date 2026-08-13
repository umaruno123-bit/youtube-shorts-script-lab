"""字幕(公式/自動)を優先して台本テキストを取得し、無ければローカルWhisperで文字起こしする。"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yt_dlp
from tqdm import tqdm

from . import fetch, net, store

_TAG_RE = re.compile(r"<[^>]+>")
_TIME_RE = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->")

# 動画1本ごとの処理間隔(秒)。YouTube側のレート制限(HTTP 429)を避けるための最低限のマナー。
REQUEST_INTERVAL_SEC = 1.5

# faster-whisperのモデルはサイズごとにロードが重いのでプロセス内でキャッシュする
_whisper_models: dict[str, Any] = {}


def _download_text(url: str) -> str:
    def _run() -> str:
        with urllib.request.urlopen(url) as resp:  # noqa: S310 - YouTube提供の字幕URLのみ使用
            return resp.read().decode("utf-8", errors="ignore")

    return net.with_backoff(_run)


def _vtt_to_text(vtt: str) -> str:
    """VTT字幕をプレーンテキスト化する。YouTubeの自動字幕はローリング表示で行が
    重複しやすいため、直前と同じ行は捨てて重複を減らす(完全な重複排除ではない簡易処理)。"""
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.startswith(("Kind:", "Language:")):
            continue
        if _TIME_RE.search(line) or line.isdigit():
            continue
        clean = _TAG_RE.sub("", line).strip()
        if not clean:
            continue
        if lines and lines[-1] == clean:
            continue
        lines.append(clean)
    return "\n".join(lines)


def get_caption_text(
    info: dict[str, Any], lang_prefs: tuple[str, ...] = ("ja", "ja-JP", "en")
) -> tuple[str, str] | None:
    """動画メタデータから手動字幕→自動字幕の優先順でテキスト化を試みる。"""
    for source_key in ("subtitles", "automatic_captions"):
        subs = info.get(source_key) or {}
        for lang in lang_prefs:
            formats = subs.get(lang)
            if not formats:
                continue
            vtt_fmt = next((f for f in formats if f.get("ext") == "vtt"), formats[0])
            url = vtt_fmt.get("url")
            if not url:
                continue
            text = _vtt_to_text(_download_text(url))
            if text:
                return text, lang
    return None


def download_audio(video_id: str, media_dir: Path) -> Path:
    """429(レート制限)を受けた場合は間隔を空けて自動リトライする。"""
    media_dir.mkdir(parents=True, exist_ok=True)
    existing = list(media_dir.glob(f"{video_id}.*"))
    if existing:
        return existing[0]
    out_template = str(media_dir / f"{video_id}.%(ext)s")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "sleep_interval_requests": 1,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a"},
        ],
    }

    def _run() -> None:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    net.with_backoff(_run)
    candidates = list(media_dir.glob(f"{video_id}.*"))
    if not candidates:
        raise RuntimeError(f"音声ファイルのダウンロードに失敗しました: {video_id}")
    return candidates[0]


def _get_whisper_model(model_size: str):
    if model_size not in _whisper_models:
        from faster_whisper import WhisperModel

        _whisper_models[model_size] = WhisperModel(
            model_size, device="auto", compute_type="auto"
        )
    return _whisper_models[model_size]


def transcribe_with_whisper(
    audio_path: Path, model_size: str = "small", language: str | None = None
) -> tuple[str, str]:
    model = _get_whisper_model(model_size)
    segments, info = model.transcribe(str(audio_path), language=language)
    text = "".join(segment.text for segment in segments).strip()
    return text, info.language


def transcribe_channel(
    channel: str,
    data_dir: Path,
    whisper_model_size: str = "small",
    language: str | None = None,
    force: bool = False,
    keep_audio: bool = False,
) -> dict[str, Any]:
    """未文字起こしの動画をすべて処理する。字幕があれば字幕、無ければ音声DL+Whisper。

    keep_audio=True の場合、字幕が取れた動画でも音声をダウンロードして保持する
    (テンポ・話し方など、台本テキストだけでは分からない部分を確認したい場合向け)。
    """
    channel_slug = store.slugify(channel)
    db_path = store.db_path_for(data_dir, channel_slug)
    media_dir = data_dir / channel_slug / "media"
    conn = store.connect(db_path)
    caption_count = 0
    whisper_count = 0
    audio_saved_count = 0
    failed: list[tuple[str, str]] = []
    try:
        videos = list(store.list_videos(conn, only_missing_transcript=not force))
        audio_only_ids: set[str] = set()
        if keep_audio and not force:
            # 既に台本はあるが音声だけ未取得の動画を、メタデータ・字幕の再取得無しで追加する
            pending_ids = {row["id"] for row in videos}
            for row in store.list_videos(conn, only_missing_transcript=False):
                if row["id"] in pending_ids or not row["transcript"]:
                    continue
                if not list(media_dir.glob(f"{row['id']}.*")):
                    videos.append(row)
                    audio_only_ids.add(row["id"])

        for row in tqdm(videos, desc=f"transcribing ({channel_slug})"):
            video_id = row["id"]
            try:
                if video_id in audio_only_ids:
                    download_audio(video_id, media_dir)
                    audio_saved_count += 1
                    time.sleep(REQUEST_INTERVAL_SEC)
                    continue
                info = fetch.fetch_video_metadata(video_id)
                caption = get_caption_text(info)
                if caption:
                    text, lang = caption
                    store.update_transcript(conn, video_id, text, "caption", lang)
                    caption_count += 1
                    if keep_audio:
                        download_audio(video_id, media_dir)
                        audio_saved_count += 1
                else:
                    audio_path = download_audio(video_id, media_dir)
                    audio_saved_count += 1
                    text, lang = transcribe_with_whisper(
                        audio_path, whisper_model_size, language
                    )
                    store.update_transcript(conn, video_id, text, "whisper", lang)
                    whisper_count += 1
            except Exception as exc:  # noqa: BLE001 - 1本失敗しても他の処理を続ける
                failed.append((video_id, str(exc)))
            time.sleep(REQUEST_INTERVAL_SEC)
    finally:
        conn.close()
    return {
        "channel_slug": channel_slug,
        "caption": caption_count,
        "whisper": whisper_count,
        "audio_saved": audio_saved_count,
        "failed": failed,
    }
