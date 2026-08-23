"""音声/動画の実際の発話タイミングを単語単位で取得する。

テロップと音声のズレを防ぐための最重要ツール。無音区間の検出だけで
台本テキストとタイムコードを推測で対応づけるとズレが蓄積するため、
faster-whisperで実際に「何が」「何秒に」話されているかを直接文字起こしする。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def transcribe_word_timestamps(
    media_path: Path,
    language: str = "ja",
    model_size: str = "medium",
) -> dict[str, Any]:
    """動画/音声ファイルを単語単位のタイムスタンプ付きで文字起こしする。

    戻り値: {"duration": float, "segments": [{"start", "end", "text", "words": [...]}]}
    words の各要素は {"start", "end", "word"}。
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, info = model.transcribe(
        str(media_path),
        language=language,
        word_timestamps=True,
        vad_filter=False,
        beam_size=5,
    )

    result_segments = []
    for seg in segments:
        words = [
            {"start": w.start, "end": w.end, "word": w.word} for w in (seg.words or [])
        ]
        result_segments.append(
            {"start": seg.start, "end": seg.end, "text": seg.text, "words": words}
        )

    return {"duration": info.duration, "segments": result_segments}


def render_as_text(result: dict[str, Any]) -> str:
    """人間が読んで区切りを判断しやすいテキスト形式に整形する。"""
    lines = [f"duration: {result['duration']:.3f}", ""]
    for seg in result["segments"]:
        lines.append(f"[{seg['start']:7.2f} - {seg['end']:7.2f}] {seg['text']}")
        for w in seg["words"]:
            lines.append(f"    {w['start']:7.2f} - {w['end']:7.2f}  {w['word']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    import argparse
    import sys

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="shortslab-timing",
        description="動画/音声を単語単位のタイムスタンプ付きで文字起こしする(テロップ同期の根拠データ作成用)",
    )
    parser.add_argument("media", type=Path, help="動画または音声ファイルのパス")
    parser.add_argument("--lang", default="ja", help="言語コード(デフォルト: ja)")
    parser.add_argument(
        "--model", default="medium", help="Whisperモデルサイズ(tiny/base/small/medium/large-v3)"
    )
    parser.add_argument("--out", type=Path, default=None, help="出力先テキストファイル(未指定なら標準出力)")
    args = parser.parse_args(argv)

    result = transcribe_word_timestamps(args.media, language=args.lang, model_size=args.model)
    text = render_as_text(result)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"書き出しました: {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
