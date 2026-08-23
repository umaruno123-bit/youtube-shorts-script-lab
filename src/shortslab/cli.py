"""shortslab CLIエントリポイント。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import fetch, prepare, rank, timing, transcribe

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--channel", required=True, help="チャンネルの @handle / URL / チャンネルID")
    parser.add_argument(
        "--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="データ保存先ディレクトリ"
    )


def cmd_fetch(args: argparse.Namespace) -> None:
    result = fetch.fetch_channel(
        args.channel, args.data_dir, limit=args.limit, refresh=args.refresh
    )
    print(
        f"[fetch] {result['channel_slug']}: {result['total_found']}件検出 / "
        f"{result['new_or_updated']}件を新規保存・更新"
    )


def cmd_transcribe(args: argparse.Namespace) -> None:
    whisper_model = args.whisper_model or os.environ.get("WHISPER_MODEL_SIZE", "small")
    result = transcribe.transcribe_channel(
        args.channel,
        args.data_dir,
        whisper_model_size=whisper_model,
        language=args.lang,
        force=args.force,
        keep_audio=args.keep_audio,
    )
    print(
        f"[transcribe] {result['channel_slug']}: 字幕={result['caption']}件 / "
        f"Whisper={result['whisper']}件 / 音声保存={result['audio_saved']}件 / "
        f"失敗={len(result['failed'])}件"
    )
    for video_id, err in result["failed"]:
        print(f"  失敗: {video_id}: {err}")


def cmd_rank(args: argparse.Namespace) -> None:
    out_path = rank.rank_channel(
        args.channel, args.data_dir, top=args.top, metric=args.metric, full=args.full
    )
    print(f"[rank] レポートを出力しました: {out_path}")


def cmd_prepare(args: argparse.Namespace) -> None:
    out_path = prepare.prepare_for_channel(
        args.channel,
        args.data_dir,
        top=args.top,
        num_ideas=args.ideas,
        num_scripts=args.scripts,
        telop=not args.no_telop,
    )
    print(f"[prepare] Claude Code向け指示書を出力しました: {out_path}")
    print(
        "[prepare] Claude Code(またはclaude.ai)でこのファイルを開き、"
        "内容の指示に従ってネタ案・台本を生成してもらってください。"
        "APIキーは不要です。"
    )


def cmd_timing(args: argparse.Namespace) -> None:
    result = timing.transcribe_word_timestamps(
        args.media, language=args.lang, model_size=args.model
    )
    text = timing.render_as_text(result)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"[timing] 書き出しました: {args.out}")
    else:
        print(text)


def cmd_all(args: argparse.Namespace) -> None:
    cmd_fetch(args)
    cmd_transcribe(args)
    cmd_rank(args)
    cmd_prepare(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shortslab", description="YouTube Shorts 台本分析・生成ツール"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="チャンネルのShorts一覧とメタデータを取得")
    _add_common_args(p_fetch)
    p_fetch.add_argument("--limit", type=int, default=None, help="取得する動画数の上限")
    p_fetch.add_argument("--refresh", action="store_true", help="既存動画のメタデータも再取得する")
    p_fetch.set_defaults(func=cmd_fetch)

    p_transcribe = sub.add_parser(
        "transcribe", help="台本を文字起こしする(字幕優先+Whisperフォールバック)"
    )
    _add_common_args(p_transcribe)
    p_transcribe.add_argument(
        "--whisper-model", default=None, help="faster-whisperのモデルサイズ(未指定なら.envのWHISPER_MODEL_SIZE)"
    )
    p_transcribe.add_argument("--lang", default=None, help="Whisperの言語指定(未指定は自動判定)")
    p_transcribe.add_argument("--force", action="store_true", help="既に台本がある動画も再処理する")
    p_transcribe.add_argument(
        "--keep-audio",
        action="store_true",
        help="字幕が取れた動画でも音声をダウンロード・保持する(テンポ・話し方の確認用)",
    )
    p_transcribe.set_defaults(func=cmd_transcribe)

    p_rank = sub.add_parser("rank", help="人気順ランキングレポートを出力")
    _add_common_args(p_rank)
    p_rank.add_argument("--top", type=int, default=20)
    p_rank.add_argument("--metric", choices=["views", "engagement"], default="views")
    p_rank.add_argument(
        "--full", action="store_true", help="台本を80文字のスニペットではなく全文で出力する"
    )
    p_rank.set_defaults(func=cmd_rank)

    p_prepare = sub.add_parser(
        "prepare",
        help="Claude Code(チャット)に読ませてネタ案・フル台本を作らせるための指示書を出力",
    )
    _add_common_args(p_prepare)
    p_prepare.add_argument("--top", type=int, default=15, help="分析対象にする上位動画数")
    p_prepare.add_argument("--ideas", type=int, default=10, help="生成させるネタ案の数")
    p_prepare.add_argument("--scripts", type=int, default=5, help="フル台本化させるネタ案の数")
    p_prepare.add_argument(
        "--no-telop",
        action="store_true",
        help="docs/telop_manual.mdがあってもテロップ分割タスクを指示書に含めない",
    )
    p_prepare.set_defaults(func=cmd_prepare)

    p_timing = sub.add_parser(
        "timing",
        help="動画/音声を単語単位のタイムスタンプ付きで文字起こしする(テロップ同期の根拠データ作成用)",
    )
    p_timing.add_argument("media", type=Path, help="動画または音声ファイルのパス")
    p_timing.add_argument("--lang", default="ja", help="言語コード(デフォルト: ja)")
    p_timing.add_argument(
        "--model", default="medium", help="Whisperモデルサイズ(tiny/base/small/medium/large-v3)"
    )
    p_timing.add_argument("--out", type=Path, default=None, help="出力先テキストファイル(未指定なら標準出力)")
    p_timing.set_defaults(func=cmd_timing)

    p_all = sub.add_parser("all", help="fetch → transcribe → rank → prepare を一括実行")
    _add_common_args(p_all)
    p_all.add_argument("--limit", type=int, default=None)
    p_all.add_argument("--refresh", action="store_true")
    p_all.add_argument("--whisper-model", default=None)
    p_all.add_argument("--lang", default=None)
    p_all.add_argument("--force", action="store_true")
    p_all.add_argument("--keep-audio", action="store_true")
    p_all.add_argument("--top", type=int, default=15)
    p_all.add_argument("--metric", choices=["views", "engagement"], default="views")
    p_all.add_argument("--full", action="store_true")
    p_all.add_argument("--ideas", type=int, default=10)
    p_all.add_argument("--scripts", type=int, default=5)
    p_all.add_argument("--no-telop", action="store_true")
    p_all.set_defaults(func=cmd_all)

    return parser


def _force_utf8_console() -> None:
    """Windowsのコンソールコードページ(cp932等)でも日本語出力が文字化けしないようにする。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> None:
    _force_utf8_console()
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:  # noqa: BLE001 - CLIとしてエラーメッセージを表示して終了する
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
