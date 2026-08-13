# youtube-shorts-script-lab

指定したYouTubeチャンネルのShorts動画をすべて収集し、台本を文字起こしして人気順に分析。
そのパターンをもとに、**Claude Code(チャット)** で新しいネタ案とフル台本を生成するツールです。

```
fetch(一覧・メタデータ取得) → transcribe(文字起こし) → rank(人気順レポート) → prepare(Claude向け指示書を出力)
                                                                                    ↓
                                                          Claude Codeにそのファイルを読ませてネタ案・台本を生成
```

データ収集(fetch/transcribe/rank)は普通のPythonスクリプトで、**YouTube公式APIキーもAnthropic APIキーも不要**です
(yt-dlpでShortsタブを直接取得します)。最後の生成ステップはAPIを自動で呼ぶのではなく、
`prepare` が「人気動画の台本＋やってほしいことを書いた指示書」を1つのMarkdownファイルに出力するので、
**Claude Code(またはclaude.ai)が使える人であれば、そのファイルを読ませて頼むだけ**で再現できます。
追加の課金設定は不要です。

## ⚠️ 利用にあたっての注意

- **自分が権利を持つ、または分析・研究の許可を得たチャンネル**で利用してください。
- 生成される「ネタ案・台本」はあくまで構成パターンの分析結果であり、既存動画の台本をそのまま複製・再配布しないでください。
- YouTubeの利用規約・著作権法を遵守してください。本ツールの利用によって生じたトラブルについて作者は責任を負いません。

## 必要なもの

- Python 3.10 以上
- [ffmpeg](https://ffmpeg.org/download.html)(yt-dlpの音声抽出・Whisperの音声処理に必要)
  - Windows: `winget install ffmpeg` または `choco install ffmpeg`
  - macOS: `brew install ffmpeg`
- (最後の生成ステップのみ) Claude Code または claude.ai が使える環境

## セットアップ

```bash
# 1. 仮想環境を作成
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 2. インストール(依存パッケージ + shortslabコマンドが使えるようになる)
pip install -e .
```

`.env` の設定は必須ではありません。Whisperのモデルサイズだけ変えたい場合は
`.env.example` を `.env` にコピーして `WHISPER_MODEL_SIZE` を編集してください。

## 使い方

チャンネルは `@ハンドル名`(例: `@example`)、チャンネルURL、チャンネルID(`UCxxxx...`)のいずれかで指定できます。

```bash
# 1. Shorts一覧とメタデータ(再生数・いいね数など)を取得
shortslab fetch --channel @example

# 2. 台本を文字起こし(字幕があれば字幕、無ければローカルWhisperで自動文字起こし)
shortslab transcribe --channel @example

# 3. 人気順ランキングレポートを出力(data/<channel>/reports/ranking_*.md)
shortslab rank --channel @example --top 20

# 4. Claude Code向けの指示書(人気動画の台本+タスク内容)を出力
shortslab prepare --channel @example --top 15 --ideas 10 --scripts 5

# すべて一括実行したい場合(4のprepareまで)
shortslab all --channel @example
```

### 最後のステップ: Claude Codeで生成する

`prepare` を実行すると `data/<channel_slug>/reports/claude_brief_YYYYMMDD_HHMMSS.md` が
作られます。このプロジェクトフォルダで Claude Code を開き、たとえば次のように頼んでください。

```
data/<channel_slug>/reports/claude_brief_YYYYMMDD_HHMMSS.md を読んで、
書かれている指示のとおりにネタ案とフル台本を作成し、指定のファイルに保存して
```

Claude Codeがファイルを読み、パターン分析・ネタ案・フル台本を生成して
`ideas_*.md` / `scripts_*.md` として保存してくれます。claude.ai のチャットに
ファイルの中身を貼り付ける形でも同様に使えます。

### 出力される主なファイル

```
data/<channel_slug>/
  shortslab.db                       # 動画メタデータ・台本を保存したSQLite
  media/                             # 音声ファイル(字幕が無くWhisperを使った動画、
                                      # または--keep-audio指定時は字幕がある動画も含む)
  reports/
    ranking_YYYYMMDD_HHMMSS.md       # 人気順ランキング
    claude_brief_YYYYMMDD_HHMMSS.md  # Claude Codeへ渡す指示書(prepareの出力)
    ideas_*.md                       # Claude Codeが生成するネタ案(手動で作成される)
    scripts_*.md                     # Claude Codeが生成するフル台本(手動で作成される)
```

### 主なオプション

| コマンド | オプション | 説明 |
|---|---|---|
| `fetch` | `--limit N` | 取得する動画数の上限 |
| | `--refresh` | 既存動画のメタデータも再取得する |
| `transcribe` | `--whisper-model small` | faster-whisperのモデルサイズ(`tiny`/`base`/`small`/`medium`/`large-v3`) |
| | `--force` | 既に台本がある動画も再処理する |
| | `--keep-audio` | 字幕が取れた動画でも音声をダウンロード・保持する(テンポ・話し方の確認用) |
| `rank` | `--top 20` / `--metric views\|engagement` | 上位件数と並び替え指標 |
| | `--full` | 台本を80文字スニペットではなく全文で出力する |
| `prepare` | `--top` / `--ideas` / `--scripts` | 分析対象数・作らせるネタ案数・フル台本化させる数 |

すべてのコマンドで `--data-dir` によりデータ保存先を変更できます(デフォルトはプロジェクト直下の `data/`)。

## 仕組み(内部構成)

- `src/shortslab/fetch.py` — yt-dlpでチャンネルのShortsタブから動画一覧・詳細メタデータを取得
- `src/shortslab/transcribe.py` — 公式/自動字幕を優先取得、無ければ音声をDLしてfaster-whisperで文字起こし
- `src/shortslab/store.py` — SQLiteでのメタデータ・台本の永続化
- `src/shortslab/rank.py` — 再生数・エンゲージメント率でのランキング算出とレポート出力
- `src/shortslab/prepare.py` — 人気動画の台本+タスク指示をまとめたClaude Code向けMarkdownを出力
- `src/shortslab/net.py` — YouTube側のレート制限(429)対策の簡易リトライ処理
- `src/shortslab/cli.py` — `shortslab` コマンドのエントリポイント

## トラブルシューティング

- 音声ダウンロード/Whisper文字起こしが失敗する → ffmpegがインストールされ、PATHが通っているか確認してください。
- 初回の`transcribe`実行時、Whisperモデルのダウンロードで時間がかかることがあります。
- `prepare` が「台本が保存された動画がありません」と表示される → 先に `fetch` → `transcribe` を実行してください。
- `HTTP Error 429: Too Many Requests` が出る → YouTube側の一時的なレート制限です。
  動画1本ごとに間隔を空け、429検知時は自動で待って再試行しますが、短時間に大量の動画
  (特に`--keep-audio`併用時)を処理すると制限にかかることがあります。その場合は
  数分〜数十分待ってから再実行してください。`fetch`/`transcribe`は処理済みの動画を
  スキップするので、失敗した分だけ再試行されます。
