"""Writes notebooks/BotDataCollection_audit.ipynb (markdown in English, then Japanese).

The notebook audits the collection on a slice of one monthly dump: it shows the raw data
(the dump and the Lichess API), runs every stage of the package on the slice, checks each
stage against an independent recomputation, and compares the slice with the census tables.
The notebook is generated so that its text and code can be reviewed as plain Python.
Run ``uv run python scripts/build_notebook.py`` and then execute the notebook
(``uv run python scripts/build_notebook.py --execute`` does both).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "BotDataCollection_audit.ipynb"


def md(english: str, japanese: str) -> nbformat.NotebookNode:
    """A markdown cell with the English text first and the Japanese text below a rule."""
    return nbformat.v4.new_markdown_cell(f"{english.strip()}\n\n---\n\n{japanese.strip()}")


def code(source: str) -> nbformat.NotebookNode:
    """A code cell."""
    return nbformat.v4.new_code_cell(source.strip())


INTRO: list[nbformat.NotebookNode] = [
    md(
        """
# Audit of the collection: from the raw Lichess data to the final tables

**What this notebook is for.** [Lichess_BotDataCollection](https://github.com/konbraphat51/Lichess_BotDataCollection)
turns the Lichess open database into the tables behind the papers. This notebook lets a
reader check that process step by step: what the raw data look like, exactly how each
value is extracted and computed, and what the final tables hold.

**How.** Collecting a whole month takes a 5-35 GB download and many engine hours, so the
notebook works on a **slice**: the first 128 MB of one monthly dump (by default August
2022, about the first six hours of the month). On the slice it

1. shows the raw data: the compressed dump file and the Lichess API's answers;
2. runs every stage of the package, unchanged, as `lbd run` does;
3. shows sample rows of every intermediate and final table, and follows one game from the
   raw text to its final row;
4. checks each stage against an **independent recomputation** written in this notebook
   (for example, the moves and clocks are read again with the `python-chess` library);
5. compares the slice with the **census tables** (the tables the papers use), game by game.

Every table shows only a few sample rows. Human players are shown under pseudonyms
(`human_001`, ...) and game ids as `game_001`, ...; bots are public accounts and keep their
names (set `LBD_AUDIT_ANONYMISE=0` to show the real values).

**How each step is laid out.** (1) what the step does, (2) the code and its output with
sample rows, (3) a check, and (4) how to read the output. References are listed at the end.
""",
        """
# 収集の監査：Lichess の生データから最終的な表まで

**このノートブックの目的。** [Lichess_BotDataCollection](https://github.com/konbraphat51/Lichess_BotDataCollection)
は、Lichess のオープンデータベースを論文で使う表に変換する。
このノートブックでは、その過程を段階ごとに確かめられる。生データがどのようなものか、各値をどのように取り出して計算するか、最終的な表に何が入るかを順に示す。

**方法。** 1か月分を集めるには 5〜35 GB のダウンロードとエンジンによる長時間の計算が要る。
そこでこのノートブックは**切り出し**を使う。1つの月次ダンプの先頭 128 MB（既定は2022年8月で、月の最初の約6時間）である。
この切り出しについて、次のことを行う。

1. 生データを示す。圧縮されたダンプのファイルと、Lichess API の応答である。
2. パッケージのすべての段階を、`lbd run` と同じように、変更せずに実行する。
3. すべての中間の表と最終の表の行の例を示し、1局を生のテキストから最終的な行まで追う。
4. 各段階を、このノートブックの中で書いた**独立の再計算**と照合する（たとえば、指し手と時計を `python-chess` ライブラリで読み直す）。
5. 切り出しを**本番の表**（論文が使う表）と1局ずつ比べる。

表には行の例をいくつか示すだけである。人間のプレイヤーは仮名（`human_001` など）で、対局の ID は `game_001` などで示す。
ボットは公開のアカウントなので名前をそのまま示す（実際の値を示すには `LBD_AUDIT_ANONYMISE=0` とする）。

**各段階の構成。** (1) その段階ですること、(2) コードと出力（行の例）、(3) 確認、(4) 出力の読み方、の順に示す。参考文献は最後にまとめた。
""",
    ),
    md(
        """
## The path of the data

| Stage | Input | Output (in `<month folder>`) | Code |
|---|---|---|---|
| download | `database.lichess.org` monthly dump | `lichess_db_standard_rated_YYYY-MM.pgn.zst` (deleted after extraction) | `download.py` |
| extract | the dump | `bot_games`, `bot_vs_bot_games`, `baseline_games`, `watched_human_games`, `user_activity` | `extract.py`, `pgn.py` |
| profiles | bot names; Lichess API `POST /api/users` | `bot_profiles` | `bots.py`, `api.py` |
| evaluate | `bot_games`; Stockfish 19 | `sf_evals` | `engine.py`, `pipeline.py` |
| maia | `bot_games`, `sf_evals`; lc0 + Maia-1 | `maia_evals` | `maia.py` |
| features | all of the above | `player_games`, `baseline_player_games`, `bot_features` | `features/*.py`, `pipeline.py` |
| bot-accounts | all months; Lichess API | `external/bot_accounts` | `features/bot_accounts.py` |
| panel | all months' `player_games` and `user_activity` | `census-panel/player_games`, `user_activity_monthly` | `panel.py` |

## Terms used throughout

| Term | Meaning |
|---|---|
| **PGN** | Portable Game Notation, the text format of chess games (Edwards, 1994): tag pairs such as `[White "name"]`, then the moves. Lichess adds the remaining clock after each move as a comment `{ [%clk 0:04:58] }`, and an engine evaluation `[%eval 0.3]` when someone had the game analysed. |
| **SAN** | Standard Algebraic Notation of a move, such as `Nf3` or `exd5` (Edwards, 1994). |
| **Ply** | One move of one side (a "half-move"). |
| **BOT title** | Lichess marks accounts run by programs (through its Bot API) with the title `BOT`; the dump records each player's title. |
| **Centipawn (cp)** | An engine's evaluation in hundredths of a pawn, from White's side. A forced mate is stored as ±10,000. |
| **Win probability (wp)** | Lichess' conversion of an evaluation: `wp = 1 / (1 + exp(-0.00368208 * cp))` (Lichess, n.d.). |
| **Expected score** | Elo's formula (Elo, 1978): `1 / (1 + 10^((opponent rating - player rating) / 400))`. Lichess ratings are Glicko-2 ratings (Glickman, 2022). |
| **Stockfish** | An open-source chess engine (Stockfish developers, 2026). The census used version 19 with 10,000 nodes per position. |
| **Maia** | Neural networks trained to predict the move a human of a given rating plays (McIlroy-Young et al., 2020), run with the lc0 engine. |
| **Census** | The 49 monthly tables (August 2022 - August 2026) built by `lbd run`, which the papers use. |
""",
        """
## データの流れ

| 段階 | 入力 | 出力（`<月のフォルダ>` 内） | コード |
|---|---|---|---|
| download | `database.lichess.org` の月次ダンプ | `lichess_db_standard_rated_YYYY-MM.pgn.zst`（抽出の後に削除） | `download.py` |
| extract | ダンプ | `bot_games`、`bot_vs_bot_games`、`baseline_games`、`watched_human_games`、`user_activity` | `extract.py`、`pgn.py` |
| profiles | ボットの名前、Lichess API `POST /api/users` | `bot_profiles` | `bots.py`、`api.py` |
| evaluate | `bot_games`、Stockfish 19 | `sf_evals` | `engine.py`、`pipeline.py` |
| maia | `bot_games`、`sf_evals`、lc0 + Maia-1 | `maia_evals` | `maia.py` |
| features | 上のすべて | `player_games`、`baseline_player_games`、`bot_features` | `features/*.py`、`pipeline.py` |
| bot-accounts | すべての月、Lichess API | `external/bot_accounts` | `features/bot_accounts.py` |
| panel | すべての月の `player_games` と `user_activity` | `census-panel/player_games`、`user_activity_monthly` | `panel.py` |

## 全体で使う用語

| 用語 | 意味 |
|---|---|
| **PGN** | チェスの棋譜のテキスト形式（Edwards, 1994）。`[White "名前"]` のようなタグの組のあとに指し手が続く。Lichess は各手の後の残り時間をコメント `{ [%clk 0:04:58] }` として加え、誰かが解析を依頼した対局にはエンジンの評価 `[%eval 0.3]` も加える。 |
| **SAN** | `Nf3` や `exd5` のような指し手の標準代数記法（Edwards, 1994）。 |
| **プライ（ply）** | 片方の1手（「半手」）。 |
| **BOT 称号** | Lichess は、プログラムが（Bot API を通して）指すアカウントに `BOT` という称号を付ける。ダンプには各プレイヤーの称号が記録されている。 |
| **センチポーン（cp）** | エンジンの評価値を、白から見てポーン1個の100分の1単位で表したもの。詰みは ±10,000 として記録する。 |
| **勝率（wp）** | Lichess による評価値の変換：`wp = 1 / (1 + exp(-0.00368208 * cp))`（Lichess, n.d.）。 |
| **期待スコア** | Elo の式（Elo, 1978）：`1 / (1 + 10^((相手のレーティング - 自分のレーティング) / 400))`。Lichess のレーティングは Glicko-2 による（Glickman, 2022）。 |
| **Stockfish** | オープンソースのチェスエンジン（Stockfish developers, 2026）。本番ではバージョン19を、1局面あたり10,000ノードで使った。 |
| **Maia** | あるレーティングの人間が指す手を予測するように訓練したニューラルネットワーク（McIlroy-Young et al., 2020）。lc0 エンジンで動かす。 |
| **本番（census）** | `lbd run` が作った49か月分（2022年8月〜2026年8月）の表。論文はこれを使う。 |
""",
    ),
]

SETUP: list[nbformat.NotebookNode] = [
    md(
        """
## 0. Setup

**What this step does.** It reads the settings, checks that the engines are present, and
says whether the census tables of the month are available for the comparison in step 9.

Set these environment variables before starting Jupyter (defaults in brackets):

- `LBD_AUDIT_MONTH`: the month to audit (`2022-08`)
- `LBD_AUDIT_SLICE_MB`: how many MB of the compressed dump to read, a multiple of 16 (`128`)
- `LBD_AUDIT_DIR`: where the slice and its tables are written (`<LBD_DATA_ROOT>/audit`);
  nothing is written into the census folders
- `LBD_AUDIT_WORKERS`: parallel processes for extraction and the engines (`2`)
- `LBD_AUDIT_ANONYMISE`: `0` shows real names and game ids (`1`)
- the package's own variables: `LBD_TOOLS_DIR` (or `LBD_STOCKFISH`, `LBD_LC0`,
  `LBD_MAIA_WEIGHTS`) for the engines, and `LBD_INTERIM_DIR` pointing at the census
  month folders for step 9

A run takes about 5-10 minutes (the download of the slice and the Stockfish stage take
most of it).

**How to read the output.** Each tool line should say `found`. `census tables: True`
means step 9 can compare the slice with the census.
""",
        """
## 0. 準備

**この段階ですること。** 設定を読み、エンジンがそろっているかを確かめ、段階9の比較に使う本番の表がその月にあるかを示す。

Jupyter を起動する前に、次の環境変数を設定する（括弧内は既定値）。

- `LBD_AUDIT_MONTH`：監査する月（`2022-08`）
- `LBD_AUDIT_SLICE_MB`：圧縮されたダンプを何 MB 読むか。16の倍数（`128`）
- `LBD_AUDIT_DIR`：切り出しとその表を書き出す場所（`<LBD_DATA_ROOT>/audit`）。本番のフォルダには何も書かない
- `LBD_AUDIT_WORKERS`：抽出とエンジンの並列プロセス数（`2`）
- `LBD_AUDIT_ANONYMISE`：`0` にすると実際の名前と対局 ID を示す（`1`）
- パッケージ自身の変数：エンジンには `LBD_TOOLS_DIR`（または `LBD_STOCKFISH`、`LBD_LC0`、`LBD_MAIA_WEIGHTS`）、段階9には本番の月のフォルダを指す `LBD_INTERIM_DIR`

1回の実行には約5〜10分かかる（大半は切り出しのダウンロードと Stockfish の段階である）。

**出力の読み方。** ツールの行はすべて `found` になるはずである。`census tables: True` なら、段階9で切り出しを本番と比べられる。
""",
    ),
    code(
        """
import io
import json
import math
import os
import re
import shutil
import statistics
import zlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

import chess
import chess.pgn
import httpx
import polars as pl
import zstandard
from IPython.display import display

from lichess_bot_data import config
from lichess_bot_data.api import LichessApi
from lichess_bot_data.bots import BotProfileCollector, apply_codebook, classify_engine, load_codebook
from lichess_bot_data.download import DownloadPlan
from lichess_bot_data.engine import EngineSettings, _evaluate_batch
from lichess_bot_data.extract import DumpExtractor
from lichess_bot_data.features.bot_accounts import confirmed_by_api, suspects, titled_bots
from lichess_bot_data.maia import maia_rating
from lichess_bot_data.panel import SEQUENCE_COLUMNS, build_panel
from lichess_bot_data.pgn import parse_headers, parse_movetext, split_game
from lichess_bot_data.pipeline import MonthPaths, build_tables, evaluate_sample, score_maia, stratified_sample
from lichess_bot_data.runner import EVERY_GAME, RunSettings

MONTH = os.environ.get("LBD_AUDIT_MONTH", "2022-08")
SLICE_MB = int(os.environ.get("LBD_AUDIT_SLICE_MB", "128"))
AUDIT_DIR = Path(os.environ.get("LBD_AUDIT_DIR", config.DATA_ROOT / "audit"))
WORKERS = int(os.environ.get("LBD_AUDIT_WORKERS", "2"))
ANONYMISE = os.environ.get("LBD_AUDIT_ANONYMISE", "1") != "0"
NODES = RunSettings().nodes  # the census setting: 10,000 nodes per position

paths = MonthPaths(AUDIT_DIR / "interim" / MONTH)
census = MonthPaths(config.INTERIM_DIR / MONTH)
HAS_CENSUS = census.player_games.exists()

pl.Config.set_tbl_rows(30)
pl.Config.set_tbl_cols(30)
pl.Config.set_fmt_str_lengths(60)
pl.Config.set_fmt_table_cell_list_len(6)
print("month:", MONTH, "| slice:", SLICE_MB, "MB | workers:", WORKERS)
print("audit folder:", AUDIT_DIR)
for tool in (config.STOCKFISH_PATH, config.LC0_PATH, config.MAIA_WEIGHTS_DIR / "maia-1500.pb.gz"):
    print("found  " if tool.exists() else "MISSING", tool)
print("census tables:", HAS_CENSUS, f"({census.root})")
for package in ("lichess-bot-data", "polars", "chess", "zstandard", "httpx"):
    print(f"{package} {version(package)}")
""",
    ),
    md(
        """
**Pseudonyms.** The helpers below replace human names and game ids in what is *shown*;
the tables on disk keep the real values. Bots are recognised by their BOT title in the
slice (filled in after step 2).
""",
        """
**仮名。** 次の関数は、*表示する*ときだけ人間の名前と対局 ID を置き換える。ディスク上の表は実際の値のままである。
ボットは切り出しの中の BOT 称号で見分ける（段階2の後で埋める）。
""",
    ),
    code(
        """
BOTS: set[str] = set()  # lowercase names of accounts shown with the BOT title in the slice
_aliases: dict[str, dict[str, str]] = {"human": {}, "game": {}}
NAME_COLUMNS = ("white", "black", "player", "opponent", "next_opponent", "user")


def alias(value: str | None, kind: str = "human") -> str | None:
    \"\"\"Pseudonym of a human name or game id (bots and None are returned unchanged).\"\"\"
    if value is None or not ANONYMISE or (kind == "human" and value.lower() in BOTS):
        return value
    table = _aliases[kind]
    key = value.lower() if kind == "human" else value
    if key not in table:
        table[key] = f"{kind}_{len(table) + 1:03d}"
    return table[key]


def anon(frame: pl.DataFrame) -> pl.DataFrame:
    \"\"\"The frame with human names and game ids replaced by pseudonyms.\"\"\"
    if not ANONYMISE:
        return frame
    replace = [
        pl.col(c).map_elements(alias, return_dtype=pl.Utf8) for c in NAME_COLUMNS if c in frame.columns
    ]
    if "game_id" in frame.columns:
        replace.append(pl.col("game_id").map_elements(lambda g: alias(g, "game"), return_dtype=pl.Utf8))
    return frame.with_columns(replace) if replace else frame


def anon_pgn(text: str) -> str:
    \"\"\"PGN text with the player names and the game link replaced by pseudonyms.\"\"\"
    if not ANONYMISE:
        return text
    text = re.sub(r'^\\[(White|Black) "(.*)"\\]$', lambda m: f'[{m[1]} "{alias(m[2])}"]', text, flags=re.M)
    return re.sub(
        r'^\\[Site "https://lichess.org/(\\w+)"\\]$',
        lambda m: f'[Site "https://lichess.org/{alias(m[1], "game")}"]',
        text,
        flags=re.M,
    )


def vertical(row: dict[str, object]) -> pl.DataFrame:
    \"\"\"One row shown as a two-column table (column name, value).\"\"\"
    return pl.DataFrame({"column": list(row), "value": [str(v) for v in row.values()]})
""",
    ),
]

RAW_DUMP: list[nbformat.NotebookNode] = [
    md(
        """
## 1. Raw data (1): the monthly dump

**What this step does.** Lichess publishes every rated standard game of a month as one
file, `lichess_db_standard_rated_YYYY-MM.pgn.zst`: PGN text compressed with Zstandard
(Collet & Kucherawy, 2021). The package's downloader (`download.RangeDownloader`) splits
the file into 16 MB byte ranges (`download.DownloadPlan`) and fetches them with HTTP range
requests (Fielding et al., 2022), a few at a time, so that a broken download resumes.

Here only the first `SLICE_MB / 16` ranges of the same plan are fetched. Zstandard can be
decompressed from the start of a file, so the slice decompresses into the first hours of
the month. The last game is cut off mid-way; the text is cut at the start of that game
(the same boundary `extract.iter_blocks` uses) and compressed again as a small dump file
that the extractor reads exactly as it would read a full dump.

**How to read the output.** The size of the whole dump and the share fetched; then the
slice: how many games it holds and the time they span.
""",
        """
## 1. 生データ（1）：月次ダンプ

**この段階ですること。** Lichess は、ある月のレーティング戦（標準ルール）のすべての対局を、1つのファイル `lichess_db_standard_rated_YYYY-MM.pgn.zst` として公開している。
中身は PGN のテキストを Zstandard（Collet & Kucherawy, 2021）で圧縮したものである。
パッケージのダウンローダ（`download.RangeDownloader`）は、ファイルを 16 MB ずつのバイト範囲に分け（`download.DownloadPlan`）、HTTP の範囲指定リクエスト（Fielding et al., 2022）で数本ずつ並行して取得する。途中で切れても続きから再開できるようにするためである。

ここでは、同じ分け方の最初の `SLICE_MB / 16` 個の範囲だけを取得する。
Zstandard はファイルの先頭から展開できるので、切り出しは月の最初の数時間分のテキストになる。
最後の対局は途中で切れているので、その対局の始まりでテキストを切る（`extract.iter_blocks` と同じ境界）。
それを小さなダンプファイルとして圧縮し直す。抽出の段階は、これを本物のダンプとまったく同じように読む。

**出力の読み方。** ダンプ全体の大きさと、取得した割合を示す。続いて切り出しに含まれる対局数と、その時間の幅を示す。
""",
    ),
    code(
        """
url = config.dump_url(MONTH)
head = httpx.head(url, follow_redirects=True, timeout=60)
head.raise_for_status()
plan = DownloadPlan(url, int(head.headers["content-length"]), chunk_size=16 * 1024 * 1024)
ranges = [plan.chunk_range(i) for i in range(SLICE_MB // 16)]
print(url)
print(f"whole dump: {plan.total_size / 1e9:.1f} GB in {plan.n_chunks:,} ranges of 16 MB; "
      f"last modified {head.headers.get('last-modified')}")
print(f"fetched: ranges 0-{len(ranges) - 1} = bytes {ranges[0][0]:,}-{ranges[-1][1]:,} "
      f"({100 * (ranges[-1][1] + 1) / plan.total_size:.2f}% of the file)")

raw_dir = AUDIT_DIR / "raw"
raw_dir.mkdir(parents=True, exist_ok=True)
head_file = raw_dir / f"{MONTH}_first_{SLICE_MB}MB.pgn.zst.part"
if not head_file.exists():
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        parts = []
        for start, end in ranges:
            response = client.get(url, headers={"Range": f"bytes={start}-{end}"})
            assert response.status_code == 206, response.status_code  # 206 = partial content
            parts.append(response.content)
    head_file.write_bytes(b"".join(parts))

# decompress what was fetched, then cut before the first incomplete game
decompressed = bytearray()
with zstandard.ZstdDecompressor(max_window_size=2**31).stream_reader(io.BytesIO(head_file.read_bytes())) as reader:
    while chunk := reader.read(1 << 22):
        decompressed += chunk
cut = bytes(decompressed).rfind(b"\\n\\n[Event ")
slice_text = bytes(decompressed[:cut + 1]).decode("utf-8")
slice_dump = raw_dir / f"lichess_db_standard_rated_{MONTH}.pgn.zst"
slice_dump.write_bytes(zstandard.ZstdCompressor().compress(slice_text.encode("utf-8")))
print(f"decompressed {len(decompressed) / 1e6:.0f} MB; kept {len(slice_text) / 1e6:.0f} MB up to the last complete game")
""",
    ),
    md(
        """
**An independent count of the slice.** Before the package reads the slice, the cell below
reads it with its own simple rule: split the text before every `[Event ` tag and read each
game's tags with one regular expression. The resulting table `raw_games` (one row per game,
tags only) is used to check the extraction in step 3. Each game is classified by the two
`WhiteTitle` / `BlackTitle` tags.
""",
        """
**切り出しの独立した集計。** パッケージが切り出しを読む前に、次のセルが独自の単純な規則で読む。
すべての `[Event ` タグの前でテキストを分け、各対局のタグを1つの正規表現で読む。
こうして作る表 `raw_games`（1対局1行、タグだけ）は、段階3で抽出を確かめるのに使う。
各対局は `WhiteTitle` と `BlackTitle` の2つのタグで分類する。
""",
    ),
    code(
        """
games_text = re.split(r"\\n\\n(?=\\[Event )", slice_text.strip())
TAG = re.compile(r'^\\[(\\w+) "(.*)"\\]$', re.M)


def raw_tags(game: str) -> dict[str, str | None]:
    \"\"\"The tags of one game that the checks need.\"\"\"
    tags = dict(TAG.findall(game.split("\\n\\n", 1)[0]))
    return {
        "game_id": tags["Site"].rsplit("/", 1)[-1],
        "white": tags["White"],
        "black": tags["Black"],
        "white_title": tags.get("WhiteTitle"),
        "black_title": tags.get("BlackTitle"),
        "utc": f"{tags['UTCDate']} {tags['UTCTime']}",
    }


raw_games = pl.DataFrame([raw_tags(g) for g in games_text], infer_schema_length=None).with_columns(
    pl.when((pl.col("white_title") == "BOT") & (pl.col("black_title") == "BOT")).then(pl.lit("bot vs bot"))
    .when((pl.col("white_title") == "BOT") | (pl.col("black_title") == "BOT")).then(pl.lit("human vs bot"))
    .otherwise(pl.lit("human vs human"))
    .alias("kind")
)
for side in ("white", "black"):
    BOTS.update(raw_games.filter(pl.col(f"{side}_title") == "BOT")[side].str.to_lowercase().to_list())
print(f"{raw_games.height:,} games from {raw_games['utc'].min()} to {raw_games['utc'].max()} (UTC); "
      f"{len(BOTS)} bot accounts")
display(raw_games.group_by("kind").len().sort("kind"))
""",
    ),
    md(
        """
**One raw game.** The example followed through the whole notebook is a human-vs-bot game
from a player who played the same bot at least three times in the slice (the first such
game in the dump). Below is its complete raw text. Note the `BlackTitle` / `WhiteTitle`
tag of the bot and the `%clk` comment after each move.
""",
        """
**生の対局の例。** このノートブック全体で追う例は、切り出しの中で同じボットと3局以上指したプレイヤーの、人間対ボットの1局である（ダンプの中で最初に現れるもの）。
次がその生のテキストのすべてである。ボットの `BlackTitle` か `WhiteTitle` のタグと、各手の後の `%clk` のコメントに注目してほしい。
""",
    ),
    code(
        """
human_side = pl.when(pl.col("white_title") == "BOT").then(pl.col("black")).otherwise(pl.col("white"))
bot_side = pl.when(pl.col("white_title") == "BOT").then(pl.col("white")).otherwise(pl.col("black"))
hvb = raw_games.with_row_index("position").filter(pl.col("kind") == "human vs bot").with_columns(
    human_side.alias("human"), bot_side.alias("bot")
)
repeat_pairs = hvb.group_by("human", "bot").len().filter(pl.col("len") >= 3)
example_raw = hvb.join(repeat_pairs, on=["human", "bot"]).sort("position").row(0, named=True)
EXAMPLE_ID, EXAMPLE_HUMAN, EXAMPLE_BOT = example_raw["game_id"], example_raw["human"], example_raw["bot"]
example_text = games_text[example_raw["position"]]
print(anon_pgn(example_text))
""",
    ),
]

PARSE: list[nbformat.NotebookNode] = [
    md(
        """
## 2. Reading one game: tags, moves, clocks

**What this step does.** `pgn.parse_headers` turns the tag lines into a dictionary, and
`pgn.parse_movetext` walks the move text: move numbers (`12.`, `12...`) are skipped, each
SAN move becomes one ply, and the comment after a move gives that ply's clock (`%clk
h:mm:ss` in seconds) and, if present, its evaluation (`%eval`). The table shows the first
ten plies of the example.

**Check.** The same game is read again with `python-chess` (Fiekas, 2024), an independent
PGN parser that also replays every move on a board, so an illegal or misread move would
fail. Its moves, clocks and evaluations must equal the package's.
""",
        """
## 2. 1局を読む：タグ、指し手、時計

**この段階ですること。** `pgn.parse_headers` はタグの行を辞書に変える。`pgn.parse_movetext` は指し手の部分を先頭から読む。
手数（`12.`、`12...`）は読み飛ばし、SAN の指し手1つを1プライとする。
指し手の後のコメントから、そのプライの残り時間（`%clk h:mm:ss` を秒に直す）と、あれば評価値（`%eval`）を取る。
表は例の対局の最初の10プライである。

**確認。** 同じ対局を `python-chess`（Fiekas, 2024）で読み直す。これは独立の PGN パーサで、すべての手を盤の上で指し直すので、反則手や読み違いがあれば失敗する。
その指し手、残り時間、評価値はパッケージのものと等しくなければならない。
""",
    ),
    code(
        """
head_text, move_text = split_game(example_text)
headers = parse_headers(head_text)
moves = parse_movetext(move_text)
display(anon(pl.DataFrame([{
    "game_id": headers["Site"].rsplit("/", 1)[-1], "white": headers["White"], "black": headers["Black"],
    "WhiteTitle": headers.get("WhiteTitle"), "BlackTitle": headers.get("BlackTitle"),
    "WhiteElo": headers["WhiteElo"], "BlackElo": headers["BlackElo"], "Result": headers["Result"],
    "Termination": headers["Termination"], "TimeControl": headers["TimeControl"],
}])))
display(pl.DataFrame({
    "ply": range(1, 11), "san": moves.sans[:10], "clock_s": moves.clocks[:10], "eval_cp": moves.evals[:10],
}, strict=False))

reference = chess.pgn.read_game(io.StringIO(example_text))
board, ref_sans, ref_clocks = reference.board(), [], []
for node in reference.mainline():
    ref_sans.append(node.parent.board().san(node.move))
    ref_clocks.append(None if node.clock() is None else int(node.clock()))
print("python-chess moves equal:", ref_sans == moves.sans, "| clocks equal:", ref_clocks == moves.clocks,
      "| plies:", len(ref_sans))
""",
    ),
]

EXTRACT: list[nbformat.NotebookNode] = [
    md(
        """
## 3. Extraction: from the dump to five tables

**What this step does.** `extract.DumpExtractor` reads the dump in blocks that start at a
game boundary, parses the blocks in a process pool, and sorts every game by the two title
tags (exactly as `lbd run` calls it, with `watch_self=True`):

| Table | Which games | What is kept |
|---|---|---|
| `bot_games` | exactly one side has the BOT title | tags, SAN moves, clocks, Lichess evals |
| `bot_vs_bot_games` | both sides have the BOT title | tags and clocks (no moves) |
| `baseline_games` | human vs human, for a fixed 0.5% of player pairs: `crc32(sorted lowercase names) mod 1000 < 5` | tags and clocks (no moves) |
| `watched_human_games` | human vs human games of anyone who played a bot this month | tags only |
| `user_activity` | every human-vs-human game | number of such games per name |

`lbd run` also watches the next month's bot players when that month is already extracted;
the slice has no next month, so this list is empty here.

**How to read the output.** The extraction summary, then a few rows of each table. The
`clocks` and `evals` columns are lists with one entry per ply.
""",
        """
## 3. 抽出：ダンプから5つの表へ

**この段階ですること。** `extract.DumpExtractor` は、対局の境目から始まるブロックごとにダンプを読み、ブロックをプロセスプールで解析する。
そして、すべての対局を2つの称号タグで振り分ける（`lbd run` と同じく `watch_self=True` で呼ぶ）。

| 表 | どの対局か | 何を残すか |
|---|---|---|
| `bot_games` | 片方だけに BOT 称号がある | タグ、SAN の指し手、残り時間、Lichess の評価値 |
| `bot_vs_bot_games` | 両方に BOT 称号がある | タグと残り時間（指し手は残さない） |
| `baseline_games` | 人間同士で、プレイヤーの組の決まった0.5%：`crc32(小文字の名前を並べたもの) mod 1000 < 5` | タグと残り時間（指し手は残さない） |
| `watched_human_games` | その月にボットと指した人の、人間同士の対局 | タグだけ |
| `user_activity` | 人間同士のすべての対局 | 名前ごとの対局数 |

`lbd run` は、翌月がすでに抽出済みなら、翌月にボットと指した人も見張る。切り出しには翌月がないので、ここではこの一覧は空である。

**出力の読み方。** 抽出の要約と、各表の行の例を示す。`clocks` と `evals` の列は、1プライ1要素のリストである。
""",
    ),
    code(
        """
summary = DumpExtractor(slice_dump, paths.root, WORKERS, watch_self=True).run()
print(summary)
bot_games = pl.read_parquet(paths.bot_games)
bot_vs_bot = pl.read_parquet(paths.bot_vs_bot_games)
baseline = pl.read_parquet(paths.baseline_games)
watched = pl.read_parquet(paths.watched_human_games)
activity = pl.read_parquet(paths.user_activity)
SHOWN = ["game_id", "white", "black", "white_title", "black_title", "white_elo", "black_elo",
         "result", "termination", "time_control", "sans", "clocks", "evals"]
print("bot_games: the example game and two more")
display(anon(pl.concat([bot_games.filter(pl.col("game_id") == EXAMPLE_ID), bot_games.head(2)]).select(SHOWN)))
for name, table in (("bot_vs_bot_games", bot_vs_bot), ("baseline_games", baseline), ("watched_human_games", watched)):
    print(name)
    display(anon(table.head(2).select(SHOWN)))
print("user_activity")
display(anon(activity.sort("n_human_games", descending=True).head(3)))
""",
    ),
    md(
        """
**Check 1: every game lands in the right table.** The row counts are compared with the
independent count of step 1, and the baseline, watched games and activity counts are
recomputed from `raw_games` with the rules in the table above.
""",
        """
**確認1：すべての対局が正しい表に入る。** 行数を段階1の独立した集計と比べる。
さらに、ベースライン、見張った対局、対局数を、上の表の規則で `raw_games` から計算し直す。
""",
    ),
    code(
        """
human_games = raw_games.filter(pl.col("kind") == "human vs human")
pair_key = pl.concat_str(pl.min_horizontal(pl.col("white").str.to_lowercase(), pl.col("black").str.to_lowercase()),
                         pl.lit("\\0"),
                         pl.max_horizontal(pl.col("white").str.to_lowercase(), pl.col("black").str.to_lowercase()))
sampled = human_games.filter(
    pair_key.map_elements(lambda k: zlib.crc32(k.encode()) % 1000 < 5, return_dtype=pl.Boolean)
)
bot_players = set(hvb["human"].to_list())
watched_ref = human_games.filter(pl.col("white").is_in(bot_players) | pl.col("black").is_in(bot_players))
counts_ref = Counter(human_games["white"].to_list()) + Counter(human_games["black"].to_list())
activity_ok = dict(zip(activity["user"], activity["n_human_games"], strict=True)) == dict(counts_ref)


def same_ids(table: pl.DataFrame, reference: pl.DataFrame) -> bool:
    \"\"\"Whether two tables hold exactly the same games.\"\"\"
    return sorted(table["game_id"].to_list()) == sorted(reference["game_id"].to_list())


pl.DataFrame({
    "table": ["bot_games", "bot_vs_bot_games", "baseline_games", "watched_human_games", "user_activity"],
    "rows": [bot_games.height, bot_vs_bot.height, baseline.height, watched.height, activity.height],
    "independent count": [hvb.height, raw_games.filter(pl.col("kind") == "bot vs bot").height,
                          sampled.height, watched_ref.height, len(counts_ref)],
    "same games / counts": [same_ids(bot_games, hvb), same_ids(bot_vs_bot, raw_games.filter(pl.col("kind") == "bot vs bot")),
                            same_ids(baseline, sampled), same_ids(watched, watched_ref), activity_ok],
})
""",
    ),
    md(
        """
**Check 2: every human-vs-bot game is read correctly.** Each game of `bot_games` is read
again with `python-chess` from the raw text. Its tags, SAN moves (generated by replaying
the moves on a board), clocks and evaluations (`%eval`, mate as ±10,000) must equal the
row of `bot_games`.
""",
        """
**確認2：人間対ボットのすべての対局が正しく読まれる。** `bot_games` の各対局を、生のテキストから `python-chess` で読み直す。
そのタグ、SAN の指し手（盤の上で指し直して作る）、残り時間、評価値（`%eval`、詰みは ±10,000）が、`bot_games` の行と等しくなければならない。
""",
    ),
    code(
        """
text_by_id = {g["game_id"]: games_text[i] for i, g in enumerate(raw_games.iter_rows(named=True))
              if g["kind"] == "human vs bot"}


def to_int(value: str | None) -> int | None:
    \"\"\"An integer tag value, None when missing or '?'.\"\"\"
    return int(value) if value not in (None, "?") else None


def reference_row(text: str) -> dict[str, object]:
    \"\"\"One game read by python-chess, in the layout of bot_games.\"\"\"
    game = chess.pgn.read_game(io.StringIO(text))
    h = game.headers
    sans, clocks, evals = [], [], []
    for node in game.mainline():
        sans.append(node.parent.board().san(node.move))
        clocks.append(None if node.clock() is None else int(node.clock()))
        score = node.eval()
        if score is None:
            evals.append(None)
        elif score.is_mate():
            evals.append(10000.0 if score.white().mate() > 0 else -10000.0)
        else:
            evals.append(float(score.white().score()))
    return {
        "game_id": h["Site"].rsplit("/", 1)[-1], "event": h["Event"], "white": h["White"], "black": h["Black"],
        "white_elo": to_int(h.get("WhiteElo")), "black_elo": to_int(h.get("BlackElo")),
        "white_title": h.get("WhiteTitle"), "black_title": h.get("BlackTitle"), "result": h["Result"],
        "termination": h.get("Termination"), "time_control": h.get("TimeControl"),
        "sans": " ".join(sans), "clocks": clocks,
        "evals": evals if any(e is not None for e in evals) else None,
    }


checked = list(reference_row(text_by_id[g]) for g in bot_games["game_id"])
mismatches = Counter()
for ref, row in zip(checked, bot_games.iter_rows(named=True), strict=True):
    for key, value in ref.items():
        other = row[key]
        if key == "evals" and value is not None and other is not None:
            same = len(value) == len(other) and all(
                (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-3)
                for a, b in zip(value, other, strict=True))
        else:
            same = value == other
        mismatches[key] += not same
print(f"{len(checked)} games checked; mismatches per column:", dict(mismatches))
""",
    ),
]

API: list[nbformat.NotebookNode] = [
    md(
        """
## 4. Raw data (2): bot profiles from the Lichess API

**What this step does.** The dump does not say what program a bot runs. The `profiles`
stage sends the names of the month's bots to the public endpoint `POST /api/users`
(at most 300 names per request, no token) and keeps a few fields of each answer
(`bots._profile_row`). The bot's name, real-name field and bio are then searched for
keywords (`bots.classify_engine`) to assign an engine family, and a hand-made codebook
(`codebook/bot_codebook.csv`) overrides the keyword family for the 80 most played bots.

The first cell shows the raw JSON answer for the example bot and the row it becomes.
If the API cannot be reached (it can refuse automated requests from some networks), the
cell says so and uses the census's `bot_profiles` rows for the slice's bots instead, so
the later stages can still run; profiles then reflect the census's fetch date
(October 2026), not today.
""",
        """
## 4. 生データ（2）：Lichess API から得るボットのプロフィール

**この段階ですること。** ダンプには、ボットがどのプログラムで動いているかは書かれていない。
`profiles` の段階は、その月のボットの名前を公開のエンドポイント `POST /api/users` に送り（1回に300名まで、トークン不要）、応答のいくつかの欄を残す（`bots._profile_row`）。
次に、ボットの名前、本名の欄、自己紹介からキーワードを探してエンジンの系統を決める（`bots.classify_engine`）。
最も多く指された80体のボットについては、手作業のコードブック（`codebook/bot_codebook.csv`）がキーワードによる系統を上書きする。

最初のセルは、例のボットについての生の JSON の応答と、それがなる行を示す。
API に届かないとき（ネットワークによっては自動のリクエストを拒むことがある）は、セルがそのことを表示し、本番の `bot_profiles` から切り出しのボットの行を代わりに使う。
こうすると後の段階は実行できるが、プロフィールは今日ではなく本番の取得日（2026年10月）のものになる。
""",
    ),
    code(
        """
slice_bots = sorted(set(bot_games.select(bot_side).to_series().to_list()))
try:
    raw_answer = LichessApi().users([EXAMPLE_BOT])
    API_OK = True
except httpx.HTTPError as exc:
    API_OK = False
    print("The Lichess API refused the request:", exc)

if API_OK:
    shown = dict(raw_answer[0])
    print(f"raw JSON for {EXAMPLE_BOT} (keys: {', '.join(shown)}):")
    print(json.dumps(shown, indent=1, ensure_ascii=False)[:3000])
    profiles = BotProfileCollector().collect(slice_bots, paths.bot_profiles)
    print(f"profiles of {profiles.height} of {len(slice_bots)} bots fetched from the API")
elif census.bot_profiles.exists():
    keep = pl.Series([b.lower() for b in slice_bots]).implode()
    profiles = pl.read_parquet(census.bot_profiles).filter(pl.col("bot").str.to_lowercase().is_in(keep))
    profiles.write_parquet(paths.bot_profiles)
    print(f"FALLBACK: {profiles.height} of {len(slice_bots)} bot profiles copied from the census ({census.bot_profiles})")
else:
    profiles = None
    print("No profiles: the features stage runs without engine families, as lbd run does after a failed fetch")
if profiles is not None:
    display(vertical(profiles.filter(pl.col("bot") == EXAMPLE_BOT).row(0, named=True)))
""",
    ),
    md(
        """
**Engine family, worked out.** The keyword rules are tried in a fixed order and the first
match wins (`maia`, then human-like, Leela, Stockfish, weak/novelty, homemade; otherwise
`unknown`). The table applies `classify_engine` to a few made-up texts, then shows the
families of the slice's most played bots, before and after the codebook.
""",
        """
**エンジンの系統の計算例。** キーワードの規則は決まった順に試し、最初に当てはまったものを採る（`maia`、人間らしさ、Leela、Stockfish、弱い・ネタ、自作の順。どれにも当てはまらなければ `unknown`）。
表は、いくつかの作った文に `classify_engine` を当てはめ、続いて切り出しで最も多く指されたボットの系統を、コードブックの前と後で示す。
""",
    ),
    code(
        """
display(pl.DataFrame([
    {"username": u, "bio": b, "engine_family": str(classify_engine(u, b, None))}
    for u, b in [("maia9", "Maia, trained on human games"), ("FishBot", "Stockfish 16 at depth 10"),
                 ("RustyKnight", "my own engine written in Rust"), ("RandomMover", "plays random moves"),
                 ("SomeBot", "hello")]
]))
if profiles is not None:
    played = bot_games.select(bot_side.alias("bot")).group_by("bot").len()
    coded = apply_codebook(profiles, load_codebook(config.CODEBOOK_PATH))
    display(
        played.join(profiles.select("bot", pl.col("engine_family").alias("keyword_family")), on="bot", how="left")
        .join(coded.select("bot", "engine_family", "family_source"), on="bot", how="left")
        .sort("len", descending=True).head(8)
    )
""",
    ),
]

ENGINES: list[nbformat.NotebookNode] = [
    md(
        """
## 5. Engine evaluations: Stockfish and Maia

**What this step does.** Lichess `%eval` exists only for the few games someone had
analysed, so the package evaluates every position itself. The `evaluate` stage replays
each game of `bot_games` and asks Stockfish 19 for an evaluation after every ply with a
budget of 10,000 nodes (1 thread, 16 MB hash), as in the census. A checkmate on the board
is stored as ±10,000 and a finished game (stalemate, repetition) as 0. The order matters
for reproducing exact values: the games are shuffled with a fixed seed
(`pipeline.stratified_sample`), taken 3,000 at a time, and each Stockfish process
evaluates 200 games in a row.

The `maia` stage gives each move to the Maia-1 network closest to the mover's rating
(`maia.maia_rating`: rounded to 100 and kept within 1100-1900) and stores the
probability the network gave the move played, the top move's probability, and the
entropy of its distribution (Shannon, 1948).

**How to read the output.** A few rows of each table; the lists have one entry per ply.
""",
        """
## 5. エンジンによる評価：Stockfish と Maia

**この段階ですること。** Lichess の `%eval` は、誰かが解析を依頼した少数の対局にしかない。そこでパッケージはすべての局面を自分で評価する。
`evaluate` の段階は `bot_games` の各対局を指し直し、毎プライの後の局面を Stockfish 19 に評価させる。本番と同じく、予算は1局面10,000ノード（1スレッド、ハッシュ16 MB）である。
盤上の詰みは ±10,000、終わった対局（ステイルメイト、千日手など）は0として記録する。
正確な値を再現するには順序が大事である。対局は固定の種で並べ替え（`pipeline.stratified_sample`）、3,000局ずつ取り出し、Stockfish の各プロセスが200局を続けて評価する。

`maia` の段階は、各手を、指した側のレーティングに最も近い Maia-1 ネットワークに渡す（`maia.maia_rating`：100単位に丸め、1100〜1900に収める）。
そして、ネットワークが実際の手に与えた確率、最も確率の高い手の確率、分布のエントロピー（Shannon, 1948）を記録する。

**出力の読み方。** 各表の行の例を示す。リストは1プライ1要素である。
""",
    ),
    code(
        """
sf_evals = evaluate_sample(paths, EVERY_GAME, NODES, WORKERS)
maia_evals = score_maia(paths, WORKERS)
display(anon(sf_evals.head(3)))
display(anon(maia_evals.head(3)))
""",
    ),
    md(
        """
**From evaluation to win probability, worked out.** For the first ten plies of the
example, the table converts Stockfish's White-side centipawns into White's win
probability, turns it to the human's side, and shows how much win probability each move
cost its mover (`loss`, never negative). `features.game_metrics.eval_metrics` averages
these losses per side (`player_mean_loss`, `opponent_mean_loss`) and counts the blunders
(loss ≥ 0.15) in step 6. Before the first move White is assumed to be 20 cp ahead.
Maia's columns show the rating-matched network's view of the same moves.
""",
        """
**評価値から勝率への計算例。** 例の対局の最初の10プライについて、Stockfish の白から見たセンチポーンを白の勝率に変え、それを人間の側から見た値に直す。
そして、各手が指した側の勝率をどれだけ下げたか（`loss`、負にはしない）を示す。
`features.game_metrics.eval_metrics` は、段階6でこの損失を側ごとに平均し（`player_mean_loss`、`opponent_mean_loss`）、大悪手（損失0.15以上）を数える。
最初の手の前は、白が20 cp 有利と仮定する。
Maia の列は、レーティングを合わせたネットワークが同じ手をどう見たかを示す。
""",
    ),
    code(
        """
example_game = bot_games.filter(pl.col("game_id") == EXAMPLE_ID).row(0, named=True)
human_is_white = example_game["white_title"] != "BOT"
cps = sf_evals.filter(pl.col("game_id") == EXAMPLE_ID)["sf_evals"][0].to_list()
maia_row = maia_evals.filter(pl.col("game_id") == EXAMPLE_ID).row(0, named=True)


def white_wp(cp: float) -> float:
    \"\"\"Lichess' win probability of White for a White-side centipawn evaluation.\"\"\"
    return 1 / (1 + math.exp(-0.00368208 * cp))


sign = 1 if human_is_white else -1
human_wp = [white_wp(sign * 20)] + [white_wp(sign * cp) for cp in cps]
rows = []
for ply in range(10):
    mover_is_human = (ply % 2 == 0) == human_is_white
    change = human_wp[ply + 1] - human_wp[ply]
    rows.append({
        "ply": ply + 1, "san": example_game["sans"].split()[ply], "mover": "human" if mover_is_human else "bot",
        "sf_cp_white": cps[ply], "human_wp": round(human_wp[ply + 1], 3),
        "loss": round(max(-change if mover_is_human else change, 0.0), 3),
        "maia_net": maia_rating(example_game["white_elo"] if ply % 2 == 0 else example_game["black_elo"]),
        "maia_prob": round(maia_row["maia_prob"][ply], 3), "maia_is_top": maia_row["maia_is_top"][ply],
    })
pl.DataFrame(rows)
""",
    ),
]

FEATURES: list[nbformat.NotebookNode] = [
    md(
        """
## 6. Features: one row per game from the human's side

**What this step does.** `pipeline.build_tables` builds the final month tables:

1. Lichess `%eval` lists are replaced by the Stockfish lists (`lichess_analysed` keeps
   whether the game had a Lichess analysis).
2. `features.games.player_row` turns each game into one row from the human's side
   (`player` = human, `opponent` = bot): time and speed, ratings and expected score,
   result and how the game ended, opening, think times from the clocks, and the
   evaluation measures.
3. `features.identity.canonicalise` gives every account one spelling (some dumps vary
   the case of names).
4. `features.sequences.annotate_sequences` adds what the player did next (step 7).
5. The player's number of human-vs-human games (`user_activity`) and the bot's engine
   family and account age (`bot_profiles`) are joined by lowercase name.

The same code builds `baseline_player_games` (both sides of each baseline game) and
`bot_features` (one row per bot, step 8).

**How to read the output.** The example game's final row, every column, shown vertically.
""",
        """
## 6. 特徴量：人間の側から見た1局1行

**この段階ですること。** `pipeline.build_tables` が月の最終的な表を作る。

1. Lichess の `%eval` のリストを Stockfish のリストに置き換える（`lichess_analysed` は、その対局に Lichess の解析があったかを残す）。
2. `features.games.player_row` が各対局を人間の側から見た1行にする（`player` が人間、`opponent` がボット）。中身は、時刻と持ち時間の種類、レーティングと期待スコア、結果と終わり方、序盤、残り時間から求めた考慮時間、評価値による指標である。
3. `features.identity.canonicalise` が各アカウントの綴りを1つにそろえる（ダンプによっては名前の大文字小文字が揃っていない）。
4. `features.sequences.annotate_sequences` がプレイヤーがその後どうしたかを加える（段階7）。
5. プレイヤーの人間同士の対局数（`user_activity`）と、ボットのエンジンの系統とアカウントの作成日（`bot_profiles`）を、小文字の名前で結合する。

同じコードが `baseline_player_games`（ベースラインの各対局の両側）と `bot_features`（1ボット1行、段階8）も作る。

**出力の読み方。** 例の対局の最終的な行を、すべての列について縦に並べて示す。
""",
    ),
    code(
        """
build_tables(paths)
player_games = pl.read_parquet(paths.player_games)
print(f"player_games: {player_games.height} rows x {player_games.width} columns")
example_row = anon(player_games.filter(pl.col("game_id") == EXAMPLE_ID)).row(0, named=True)
vertical(example_row)
""",
    ),
    md(
        """
**The example row, worked out by hand.** The cell below recomputes the main columns of the
example from its `bot_games` row:

- `start` = `UTCDate` + `UTCTime`.
- Think time of a move = the side's previous clock − its clock after the move + the
  increment. Each side's first move is untimed on Lichess and skipped.
- `duration_s` = the sum of all measured think times; after a time forfeit the remaining
  clock of the side to move is added; `end` = `start` + `duration_s`.
- `expected_score` from Elo's formula; `player_score` from `Result` and the human's colour.
- `end_type`: draw if the result is ½-½; otherwise `Time forfeit` → timeout,
  `Abandoned` → abandoned, `Normal` → checkmate if the final position is mate (here
  checked on a `python-chess` board) and resign if not.
""",
        """
**例の行の手計算。** 次のセルは、例の主な列を `bot_games` の行から計算し直す。

- `start` = `UTCDate` + `UTCTime`。
- 1手の考慮時間 = その側の前の残り時間 − 手の後の残り時間 + 加算時間。Lichess では各側の最初の手は計時されないので除く。
- `duration_s` = 測れた考慮時間の合計。時間切れのときは、手番の側の残り時間を加える。`end` = `start` + `duration_s`。
- `expected_score` は Elo の式から、`player_score` は `Result` と人間の手番の色から求める。
- `end_type`：結果が ½-½ なら引き分け。そうでなければ `Time forfeit` → 時間切れ、`Abandoned` → 放棄、`Normal` → 最終局面が詰みなら詰み、そうでなければ投了（詰みはここでは `python-chess` の盤で確かめる）。
""",
    ),
    code(
        """
def think_times(clocks: list[int | None], increment: int, white: bool) -> list[float]:
    \"\"\"Measured think times (s) of one side; each side's first move is untimed.\"\"\"
    own = clocks[0 if white else 1::2]
    return [max(before - after + increment, 0) for before, after in zip(own, own[1:])
            if before is not None and after is not None]


def end_kind(game: dict[str, object]) -> str:
    \"\"\"How the game ended, with checkmate read from a python-chess board.\"\"\"
    if game["result"] == "1/2-1/2":
        return "draw"
    if game["termination"] == "Time forfeit":
        return "timeout"
    if game["termination"] == "Abandoned":
        return "abandoned"
    if game["termination"] == "Normal":
        board = chess.Board()
        for san in (game["sans"] or "").split():
            board.push_san(san)
        return "checkmate" if board.is_checkmate() else "resign"
    return "other"


def recompute(game: dict[str, object]) -> dict[str, object]:
    \"\"\"The main player_games columns of one bot_games row, computed independently.\"\"\"
    human_white = game["white_title"] != "BOT"
    increment = int(game["time_control"].split("+")[1]) if "+" in game["time_control"] else 0
    clocks = game["clocks"]
    times_h = think_times(clocks, increment, human_white)
    times_b = think_times(clocks, increment, not human_white)
    kind = end_kind(game)
    duration = float(sum(times_h) + sum(times_b))
    if kind == "timeout":
        # the side to move used up its last recorded clock (White's clocks sit at even plies)
        duration += [c for c in clocks[len(clocks) % 2::2] if c is not None][-1]
    start = datetime.strptime(f"{game['utc_date']} {game['utc_time']}", "%Y.%m.%d %H:%M:%S").replace(tzinfo=UTC)
    me, them = ("white", "black") if human_white else ("black", "white")
    white_score = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[game["result"]]
    return {
        "game_id": game["game_id"], "player": game[me], "opponent": game[them], "start": start,
        "duration_s": duration, "end": start + timedelta(seconds=duration),
        "expected_score": 1 / (1 + 10 ** ((game[f"{them}_elo"] - game[f"{me}_elo"]) / 400)),
        "player_score": white_score if human_white else 1 - white_score, "end_type": kind,
        "n_plies": len(game["sans"].split()),
        "player_time_mean": statistics.fmean(times_h) if times_h else None,
        "opponent_time_median": statistics.median(times_b) if times_b else None,
        "opponent_time_frac_fast": sum(t <= 1 for t in times_b) / len(times_b) if times_b else None,
    }


mine = recompute(example_game)
human_clocks = example_game["clocks"][0 if human_is_white else 1::2]
print("human's clocks after each move:", human_clocks[:8], "...")
print("human's think times:           ", think_times(example_game["clocks"], int(example_game["time_control"].split("+")[1]), human_is_white)[:7], "...")
stored = player_games.filter(pl.col("game_id") == EXAMPLE_ID).row(0, named=True)
hide = {"game_id": lambda v: alias(v, "game"), "player": alias, "opponent": alias}
pl.DataFrame([
    {"column": k, "recomputed": str(hide.get(k, str)(v)), "stored": str(hide.get(k, str)(stored[k]))}
    for k, v in mine.items()
])
""",
    ),
    md(
        """
**Check: every row.** The same independent recomputation is applied to every row of
`player_games`, and also the evaluation measures (mean loss per move of each side,
blunders, final win probability) from the Stockfish lists. Each column should agree on
every row (floating-point values within 1e-9).
""",
        """
**確認：すべての行。** 同じ独立の再計算を `player_games` のすべての行に当てはめる。
さらに、評価値による指標（各側の1手あたりの平均損失、大悪手の数、最終局面の勝率）も Stockfish のリストから計算し直す。
どの列もすべての行で一致するはずである（浮動小数点の値は1e-9以内）。
""",
    ),
    code(
        """
def eval_reference(cps: list[float], human_white: bool) -> dict[str, object]:
    \"\"\"Loss per move, blunders and final win probability from the human's side.\"\"\"
    sign = 1 if human_white else -1
    wp = [white_wp(sign * 20)] + [white_wp(sign * cp) for cp in cps]
    human_loss, bot_loss = [], []
    for ply in range(len(cps)):
        change = wp[ply + 1] - wp[ply]
        if (ply % 2 == 0) == human_white:
            human_loss.append(max(-change, 0.0))
        else:
            bot_loss.append(max(change, 0.0))
    return {
        "player_mean_loss": statistics.fmean(human_loss) if human_loss else 0.0,
        "opponent_mean_loss": statistics.fmean(bot_loss) if bot_loss else 0.0,
        "player_blunders": sum(x >= 0.15 for x in human_loss),
        "opponent_blunders": sum(x >= 0.15 for x in bot_loss),
        "final_player_wp": wp[-1],
    }


evals_by_id = dict(zip(sf_evals["game_id"], sf_evals["sf_evals"].to_list(), strict=True))
reference_rows = []
for game in bot_games.iter_rows(named=True):
    row = recompute(game)
    if evals_by_id.get(game["game_id"]):
        row |= eval_reference(evals_by_id[game["game_id"]], game["white_title"] != "BOT")
    reference_rows.append(row)
reference = pl.DataFrame(reference_rows, infer_schema_length=None)
joined = reference.join(player_games, on="game_id", suffix="_stored")


def agreement(frame: pl.DataFrame, column: str, other: str) -> float:
    \"\"\"Share of rows where two columns agree (both null counts as agreeing).\"\"\"
    a, b = frame[column], frame[other]
    same = (a - b).abs() < 1e-9 if a.dtype.is_float() and b.dtype.is_numeric() else a == b
    return float((same.fill_null(False) | (a.is_null() & b.is_null())).mean())


pl.DataFrame({
    "column": [c for c in reference.columns if c != "game_id"],
    "rows": joined.height,
    "agreement": [agreement(joined, c, f"{c}_stored") for c in reference.columns if c != "game_id"],
})
""",
    ),
]

SEQUENCES: list[nbformat.NotebookNode] = [
    md(
        """
## 7. What the player did next: rematch, session, return

**What this step does.** `features.sequences.annotate_sequences` orders each player's
games by start time and adds:

| Column | Rule |
|---|---|
| `gap_next_s`, `next_opponent` | Seconds from this game's (estimated) end to the player's next bot game, and its bot |
| `rematch` | The next game is against the same bot and starts within 120 s |
| `continue_session` | The next game (any bot) starts within 30 minutes |
| `pair_session_id`, `session_game_index`, `session_length`, `session_last` | Games against one bot with gaps of at most 30 minutes form a session |
| `return_7d` | On a session's last game: the same bot is played again more than 30 minutes and at most 7 days later. Null when the 7 days run past the last game of the data |

**How to read the output.** The example player's games against the example bot. In the
slice the data end a few hours after the start of the month, so every 7-day window runs
past the end and `return_7d` is null on every row; step 9 shows the census values, where
the month continues.
""",
        """
## 7. プレイヤーがその後どうしたか：再戦、セッション、再訪

**この段階ですること。** `features.sequences.annotate_sequences` は、各プレイヤーの対局を開始時刻の順に並べ、次の列を加える。

| 列 | 規則 |
|---|---|
| `gap_next_s`、`next_opponent` | この対局の（推定の）終了から、そのプレイヤーの次のボット戦までの秒数と、そのボット |
| `rematch` | 次の対局が同じボットとで、120秒以内に始まる |
| `continue_session` | 次の対局（どのボットでも）が30分以内に始まる |
| `pair_session_id`、`session_game_index`、`session_length`、`session_last` | 1体のボットとの、間隔が30分以下で続く対局をセッションとする |
| `return_7d` | セッションの最後の対局で、30分より後かつ7日以内に同じボットとまた指す。7日がデータの最後の対局を越えるときは空欄 |

**出力の読み方。** 例のプレイヤーが例のボットと指した対局を示す。
切り出しではデータが月の始まりから数時間で終わるので、7日の窓はどれも終わりを越え、`return_7d` はすべての行で空欄になる。
段階9では、月が続いている本番の値を示す。
""",
    ),
    code(
        """
SEQUENCE_SHOWN = ["start", "end", "player", "opponent", "player_score", "gap_next_s", "next_opponent", "rematch",
                  "continue_session", "pair_session_id", "session_game_index", "session_length", "session_last", "return_7d"]
example_pair = (pl.col("player").str.to_lowercase() == EXAMPLE_HUMAN.lower()) & (
    pl.col("opponent").str.to_lowercase() == EXAMPLE_BOT.lower())
print("data end of the slice (last start):", player_games["start"].max())
example_sessions = player_games.filter(example_pair).sort("start").select(SEQUENCE_SHOWN)
print(f"{example_sessions.height} games; the first four and the last two:")
anon(pl.concat([example_sessions.head(4), example_sessions.tail(2)]))
""",
    ),
    md(
        """
**Check: every row.** The cell below rebuilds these columns with plain loops, player by
player, and compares them with the stored ones.
""",
        """
**確認：すべての行。** 次のセルは、これらの列をプレイヤーごとに単純なループで作り直し、記録された値と比べる。
""",
    ),
    code(
        """
def sequence_reference(table: pl.DataFrame) -> pl.DataFrame:
    \"\"\"Rematch, session and return columns rebuilt with plain loops.\"\"\"
    data_end = table["start"].max()
    out = []
    rows = table.sort("player", "start").select("game_id", "player", "opponent", "start", "end").to_dicts()
    by_player: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_player.setdefault(row["player"], []).append(row)
    for games in by_player.values():
        for i, g in enumerate(games):
            nxt = games[i + 1] if i + 1 < len(games) else None
            gap = (nxt["start"] - g["end"]).total_seconds() if nxt else None
            pair = [h for h in games if h["opponent"] == g["opponent"]]
            j = pair.index(g)
            pair_gap = (pair[j + 1]["start"] - g["end"]).total_seconds() if j + 1 < len(pair) else None
            new_session = [k == 0 or (h["start"] - pair[k - 1]["end"]).total_seconds() > 1800 for k, h in enumerate(pair)]
            session_id = sum(new_session[: j + 1])
            members = [k for k in range(len(pair)) if sum(new_session[: k + 1]) == session_id]
            censored = g["end"] > data_end - timedelta(days=7)
            out.append({
                "game_id": g["game_id"],
                "rematch": nxt is not None and nxt["opponent"] == g["opponent"] and gap <= 120,
                "continue_session": gap is not None and gap <= 1800,
                "pair_session_id": session_id,
                "session_length": len(members),
                "session_last": j == members[-1],
                "return_7d": None if censored else (pair_gap is not None and 1800 < pair_gap <= 7 * 86400),
            })
    return pl.DataFrame(out, schema_overrides={"return_7d": pl.Boolean})


seq_ref = sequence_reference(player_games)
seq_joined = seq_ref.join(player_games, on="game_id", suffix="_stored")
pl.DataFrame({
    "column": [c for c in seq_ref.columns if c != "game_id"],
    "rows": seq_joined.height,
    "agreement": [agreement(seq_joined, c, f"{c}_stored") for c in seq_ref.columns if c != "game_id"],
})
""",
    ),
]

AGGREGATES: list[nbformat.NotebookNode] = [
    md(
        """
## 8. The other final tables: bot features, baseline, bot accounts

**What this step does.**

- `bot_features` (`features.bot_features.aggregate_bot_features`): one row per bot,
  aggregated over its `player_games` rows: games, players, median ratings, mean score,
  think time, how its games ended, engine error, rematch and return rates, and opening
  diversity (Gini-Simpson index, 1 - Σp², of its first moves; Simpson, 1949).
- `baseline_player_games`: the human-vs-human baseline built with the same code, one row
  for each side of each game.
- `external/bot_accounts` (`lbd bot-accounts`): every account shown with the BOT title in
  any month, plus untitled accounts that met at least 10 different bots in one month and
  whose API profile has the title. Normally built over all census months; here over the
  slice only.

**How to read the output.** The most played bots of the slice; the example bot's row
recomputed by hand; one baseline game (two rows); the bot accounts found in the slice.
""",
        """
## 8. ほかの最終的な表：ボットの特徴量、ベースライン、ボットのアカウント

**この段階ですること。**

- `bot_features`（`features.bot_features.aggregate_bot_features`）：1ボット1行。そのボットの `player_games` の行を集計する。内容は、対局数、プレイヤー数、レーティングの中央値、平均スコア、考慮時間、対局の終わり方、エンジンの誤り、再戦率と再訪率、序盤の多様さ（最初の手の Gini–Simpson 指数 1 − Σp²；Simpson, 1949）である。
- `baseline_player_games`：同じコードで作る人間同士のベースライン。各対局の両側を1行ずつにする。
- `external/bot_accounts`（`lbd bot-accounts`）：どこか1か月でも BOT 称号付きで現れたアカウントと、称号なしで1か月に10体以上の別々のボットと指し、API のプロフィールに称号があったアカウント。ふつうは本番のすべての月から作るが、ここでは切り出しだけから作る。

**出力の読み方。** 切り出しで最も多く指されたボット、手で計算し直した例のボットの行、ベースラインの1局（2行）、切り出しで見つかったボットのアカウントを示す。
""",
    ),
    code(
        """
bot_features = pl.read_parquet(paths.bot_features)
display(bot_features.head(5).select("opponent", "n_games", "n_players", "bot_elo_median", "main_speed",
                                     "player_score_mean", "think_median_s", "bot_mean_loss", "rematch_rate",
                                     "return_7d_rate", "mean_session_length", "opening_diversity"))
rows = player_games.filter(pl.col("opponent") == EXAMPLE_BOT)
starts = rows.filter(pl.col("session_game_index") == 0)
by_hand = {
    "n_games": rows.height,
    "n_players": rows["player"].n_unique(),
    "player_score_mean": rows["player_score"].mean(),
    "think_median_s": rows["opponent_time_median"].median(),
    "rematch_rate": rows["rematch"].mean(),
    "mean_session_length": starts["session_length"].mean(),
}
stored_bot = bot_features.filter(pl.col("opponent") == EXAMPLE_BOT).row(0, named=True)
display(pl.DataFrame([{"column": k, "by hand": str(v), "stored": str(stored_bot[k])} for k, v in by_hand.items()]))

baseline_player_games = pl.read_parquet(paths.baseline_player_games)
one = baseline_player_games["game_id"][0]
display(anon(baseline_player_games.filter(pl.col("game_id") == one).select(
    "game_id", "player", "opponent", "player_is_white", "opponent_is_bot", "player_elo", "opponent_elo",
    "expected_score", "player_score", "speed", "player_time_median", "has_evals")))

titled = titled_bots(AUDIT_DIR / "interim", [MONTH])
untitled_suspects = suspects(AUDIT_DIR / "interim", [MONTH], titled)
confirmed = confirmed_by_api(untitled_suspects) if untitled_suspects and API_OK else set()
accounts = pl.DataFrame({"user": [*sorted(titled), *sorted(confirmed)],
                         "source": ["titled"] * len(titled) + ["api"] * len(confirmed)})
(AUDIT_DIR / "external").mkdir(parents=True, exist_ok=True)
accounts.write_parquet(AUDIT_DIR / "external" / "bot_accounts.parquet")
print(f"bot accounts: {len(titled)} titled, {len(untitled_suspects)} untitled suspects "
      f"(>= 10 bots in the slice), {len(confirmed)} confirmed by the API")
census_accounts = config.EXTERNAL_DIR / "bot_accounts.parquet"
if census_accounts.exists():
    known = set(pl.read_parquet(census_accounts)["user"].to_list())
    print(f"all titled accounts of the slice are in the census list: {titled <= known}")
accounts.head(5)
""",
    ),
]

PANEL: list[nbformat.NotebookNode] = [
    md(
        """
## 9. The four-year panel and the comparison with the census

**What this step does.** `panel.build_panel` stacks the months' `player_games` (here one
month, the slice), keeps the first copy of a game that appears in two dumps, gives every
account one spelling over all months, rebuilds the sequence columns over the joint
timeline (so a session at the end of a month can be followed into the next), and adds:
`month`, `player_session_last` (no bot game by the player within 30 minutes afterwards),
`return_28d`, `return_91d` (same bot) and `any_return_7d/28d/91d` (any bot). This table,
`census-panel/player_games.parquet`, is the final dataset the papers read.

**How to read the output.** The columns the panel adds, then the last three games of the
example pair (where its session ends): first as built from the slice (returns null: the slice ends after a few hours), then, if present,
the same games in the census panel, where the data continue to August 2026.
""",
        """
## 9. 4年分のパネルと、本番との比較

**この段階ですること。** `panel.build_panel` は、各月の `player_games` を積み重ね（ここでは切り出しの1か月だけ）、2つのダンプに現れる対局は最初の1つだけを残す。
すべての月を通じて各アカウントの綴りを1つにそろえ、時系列をつなげて系列の列を作り直す（月の終わりのセッションを翌月まで追えるようにするため）。そして次の列を加える。
`month`、`player_session_last`（その後30分以内にそのプレイヤーのボット戦がない）、`return_28d`、`return_91d`（同じボット）、`any_return_7d/28d/91d`（どのボットでも）である。
この表 `census-panel/player_games.parquet` が、論文が読む最終的なデータセットである。

**出力の読み方。** パネルが加える列を示し、続いて例の組の最後の3局（セッションが終わるところ）を示す。まず切り出しから作ったもの（切り出しは数時間で終わるので再訪は空欄）、次に、あれば本番のパネルの同じ対局（データは2026年8月まで続く）を示す。
""",
    ),
    code(
        """
panel_paths = build_panel(AUDIT_DIR / "interim", [MONTH])
panel = pl.read_parquet(panel_paths.player_games)
print("added by the panel:", sorted(set(panel.columns) - set(player_games.columns)))
print("dropped by the panel:", sorted(set(player_games.columns) - set(panel.columns)))
PANEL_SHOWN = ["month", "start", "player", "opponent", "session_last", "return_7d", "return_28d", "return_91d",
               "player_session_last", "any_return_7d", "any_return_28d", "any_return_91d"]
display(anon(panel.filter(example_pair).sort("start").select(PANEL_SHOWN).tail(3)))

census_panel = config.INTERIM_DIR / "census-panel" / "player_games.parquet"
if census_panel.exists():
    ids = player_games.filter(example_pair)["game_id"].implode()
    print("the same games in the census panel:")
    display(anon(pl.scan_parquet(census_panel).filter(pl.col("game_id").is_in(ids)).collect()
                 .sort("start").select(PANEL_SHOWN).tail(3)))
""",
    ),
    md(
        """
**Comparison with the census month.** If the census tables of the month are available,
every table of the slice is compared with the census rows of the same games:

1. The extracted tables must be identical.
2. In `player_games`, the columns from the tags and clocks must be identical. The
   evaluation columns differ, because Stockfish's values depend on the order in which one
   process evaluates games (its hash table keeps what earlier searches found). To show
   this is the only reason, (a) a few games are evaluated again in exactly the census
   order and must give the census values bit for bit, and (b) the features are rebuilt
   with the census Stockfish lists and must then agree on every row. Maia scores one move
   at a time without memory, so its values should agree.
3. Sequence columns must agree on the sessions that end inside the slice (every game of
   the session has its next game inside the slice); other sessions are cut off by the end
   of the slice. `n_human_games` counts only the
   slice's human games, so it can only be smaller than the census value.
""",
        """
**本番の月との比較。** その月の本番の表があれば、切り出しのすべての表を、同じ対局の本番の行と比べる。

1. 抽出した表は同一でなければならない。
2. `player_games` のうち、タグと残り時間から作る列は同一でなければならない。
   評価値の列は異なる。Stockfish の値は、1つのプロセスがどの順で対局を評価したかに依存するからである（ハッシュ表が前の探索の結果を覚えている）。
   これが唯一の理由であることを示すために、(a) いくつかの対局を本番とまったく同じ順で評価し直し、本番の値とビット単位で一致することを示す。
   (b) 本番の Stockfish のリストで特徴量を作り直し、すべての行で一致することを示す。
   Maia は記憶をもたずに1手ずつ評価するので、その値は一致するはずである。
3. 系列の列は、切り出しの中で終わるセッション（セッションのどの対局も、次の対局が切り出しの中にある）で一致しなければならない。それ以外のセッションは、切り出しの終わりで切られている。
   `n_human_games` は切り出しの中の人間同士の対局だけを数えるので、本番の値より小さいことしかない。
""",
    ),
    code(
        """
if not HAS_CENSUS:
    print("No census tables for", MONTH, "- set LBD_INTERIM_DIR to the census interim folder to run this step")
else:
    ids = bot_games["game_id"].implode()
    for name in ("bot_games", "bot_vs_bot_games", "baseline_games"):
        mine_t = pl.read_parquet(getattr(paths, name))
        census_t = pl.read_parquet(getattr(census, name)).filter(pl.col("game_id").is_in(mine_t["game_id"].implode()))
        print(f"{name}: {mine_t.height} slice rows, {census_t.height} found in the census, identical: "
              f"{mine_t.sort('game_id').equals(census_t.sort('game_id').select(mine_t.columns))}")
    census_games = pl.read_parquet(census.player_games).filter(pl.col("game_id").is_in(ids))
""",
    ),
    code(
        """
if HAS_CENSUS:
    # (a) replay the census order: shuffle with the census seed, batches of 200 per process
    order = stratified_sample(pl.read_parquet(census.bot_games), EVERY_GAME).select("game_id", "sans").with_row_index("position")
    census_sf = pl.read_parquet(census.sf_evals)
    print("the census sf_evals file follows the replayed order:", census_sf["game_id"].equals(order["game_id"]))
    cheapest = (order.filter(pl.col("game_id").is_in(ids)).with_columns((pl.col("position") % 200).alias("in_batch"))
                .sort("in_batch").head(3))
    replay = []
    for g in cheapest.iter_rows(named=True):
        batch = order.slice(g["position"] - g["in_batch"], g["in_batch"] + 1)
        values = dict(_evaluate_batch(list(zip(batch["game_id"], batch["sans"], strict=True)),
                                      EngineSettings(config.STOCKFISH_PATH, NODES)))[g["game_id"]]
        census_values = census_sf.filter(pl.col("game_id") == g["game_id"])["sf_evals"][0].to_list()
        slice_values = sf_evals.filter(pl.col("game_id") == g["game_id"])["sf_evals"][0].to_list()
        replay.append({"game_id": g["game_id"], "position in its census batch": g["in_batch"],
                       "plies": len(values), "replay == census": values == census_values,
                       "slice run == census": slice_values == census_values})
    display(anon(pl.DataFrame(replay)))

    # the size of the order effect over all slice games, and Maia
    plies = (sf_evals.join(census_sf, on="game_id", suffix="_census")
             .explode("sf_evals", "sf_evals_census", empty_as_null=True).drop_nulls())
    diff = (plies["sf_evals"] - plies["sf_evals_census"]).abs()
    census_maia = pl.read_parquet(census.maia_evals)
    maia_plies = (maia_evals.select("game_id", "maia_prob").join(census_maia.select("game_id", "maia_prob"), on="game_id",
                  suffix="_census").explode("maia_prob", "maia_prob_census", empty_as_null=True).drop_nulls())
    print(f"Stockfish, slice run vs census: {plies.height:,} plies, {100 * (diff == 0).mean():.1f}% identical, "
          f"median |difference| {diff.median():.0f} cp, correlation {plies.select(pl.corr('sf_evals', 'sf_evals_census')).item():.3f}")
    print(f"Maia, slice run vs census: {maia_plies.height:,} plies, "
          f"{100 * (maia_plies['maia_prob'] == maia_plies['maia_prob_census']).mean():.2f}% identical")
""",
    ),
    code(
        """
if HAS_CENSUS:
    # (b) the features rebuilt with the census Stockfish lists
    rebuilt = MonthPaths(AUDIT_DIR / "interim" / f"{MONTH}-census-evals")
    rebuilt.root.mkdir(parents=True, exist_ok=True)
    for name in ("bot_games", "baseline_games", "user_activity", "bot_profiles"):
        if getattr(paths, name).exists():
            shutil.copy(getattr(paths, name), getattr(rebuilt, name))
    census_sf.filter(pl.col("game_id").is_in(ids)).write_parquet(rebuilt.sf_evals)
    build_tables(rebuilt)
    with_census_evals = pl.read_parquet(rebuilt.player_games)

    EVAL_COLUMNS = ["has_evals", "opponent_mean_loss", "player_mean_loss", "opponent_blunders", "player_blunders",
                    "opponent_mistakes", "lead_changes", "player_max_wp", "player_min_wp", "surprise", "uncertainty",
                    "opponent_conversion_plies", "player_conversion_plies", "final_player_wp"]
    last_start = player_games["start"].max()
    # rows of census sessions whose games all have their next game (any bot, same bot) inside the slice
    next_inside = (
        (pl.col("gap_next_s").is_null() | (pl.col("end") + pl.duration(seconds=pl.col("gap_next_s")) <= last_start))
        & (pl.col("gap_pair_next_s").is_null()
           | (pl.col("end") + pl.duration(seconds=pl.col("gap_pair_next_s")) <= last_start))
    )
    inside = census_games.filter(next_inside.all().over("player", "opponent", "pair_session_id"))["game_id"].implode()

    def compare(slice_table: pl.DataFrame, columns: list[str], rows: pl.Expr) -> tuple[list[float], int]:
        \"\"\"Per-column agreement of a slice table with the census rows of the same games.\"\"\"
        both = slice_table.filter(rows).join(census_games, on="game_id", suffix="_census")
        return [agreement(both, c, f"{c}_census") for c in columns], both.height

    tag_columns = [c for c in player_games.columns
                   if c not in {*EVAL_COLUMNS, *SEQUENCE_COLUMNS, "game_id", "n_human_games"}]
    groups = [
        ("tags, clocks, profiles", player_games, tag_columns, pl.lit(True)),
        ("evaluations, slice Stockfish run", player_games, EVAL_COLUMNS, pl.lit(True)),
        ("evaluations, census Stockfish lists", with_census_evals, EVAL_COLUMNS, pl.lit(True)),
        ("sequences, all rows", player_games, [c for c in SEQUENCE_COLUMNS if c != "return_7d"], pl.lit(True)),
        ("sequences, sessions ending inside the slice", player_games, [c for c in SEQUENCE_COLUMNS if c != "return_7d"],
         pl.col("game_id").is_in(inside)),
    ]
    rows_out = []
    for label, table, columns, rows in groups:
        shares, n = compare(table, columns, rows)
        rows_out.append({"columns": label, "n columns": len(columns), "rows": n, "lowest agreement": min(shares),
                         "columns below 100%": ", ".join(c for c, s in zip(columns, shares, strict=True) if s < 1) or "-"})
    display(pl.DataFrame(rows_out))
    activity_check = player_games.join(census_games, on="game_id", suffix="_census")
    print("n_human_games: slice <= census on every row:",
          bool((activity_check["n_human_games"] <= activity_check["n_human_games_census"]).all()))
""",
    ),
]

LINEAGE: list[nbformat.NotebookNode] = [
    md(
        """
## 10. Where each final column comes from

| Final columns (`player_games`, panel) | Raw source | Computed by |
|---|---|---|
| `game_id`, `player`, `opponent`, ratings, `player_rating_diff`, `eco`, `opening_name` | PGN tags `Site`, `White`/`Black`, `WhiteElo`/`BlackElo`, `*RatingDiff`, `ECO`, `Opening` | `extract._record`, `games.player_row`, `identity.canonicalise` |
| `opponent_is_bot`, which side is the human | PGN tags `WhiteTitle`/`BlackTitle` = `BOT` | `extract.process_block`, `games._focal_sides` |
| `start`, `speed`, `variant`, `is_tournament`, `base_s`, `inc_s` | PGN tags `UTCDate`, `UTCTime`, `Event`, `TimeControl` | `games.player_row` |
| `player_score`, `outcome`, `end_type`, `loser` | PGN tags `Result`, `Termination`; last SAN move | `game_metrics.player_score`, `game_metrics.end_type` |
| `expected_score`, `elo_gap` | ratings | Elo's formula |
| `n_plies`, `opening`, `line` | SAN moves | `games.player_row` |
| think times, `end`, `duration_s`, final clocks | `%clk` comments | `game_metrics.move_times`, `games.flag_time_s` |
| `has_evals`, losses, blunders, win probabilities, `surprise`, `uncertainty`, conversions | Stockfish 19 on the replayed moves (`sf_evals`) | `engine.evaluate_game`, `game_metrics.eval_metrics` |
| `lichess_analysed` | presence of `%eval` comments | `pipeline._with_engine_evals` |
| sequence columns, `return_7d` | the order of the player's games | `sequences.annotate_sequences` |
| `return_28d`, `return_91d`, `any_return_*`, `player_session_last`, `month` | the order of the player's games over all months | `panel.add_long_returns`, `panel.build_panel` |
| `n_human_games` | human-vs-human games in the dump | `extract.process_block`, `identity.activity_by_id` |
| `engine_family`, `created_at_ms` | Lichess API profile (name, real name, bio); codebook | `bots.classify_engine`, `bots.apply_codebook` |
| Maia columns (`maia_evals`, joined by the analyses) | lc0 + Maia-1 on the replayed moves | `maia.MaiaScorer` |

## 11. Summary of the checks

- **Dump → extracted tables.** Every game of the slice lands in the right table, and every
  human-vs-bot game's tags, moves, clocks and evaluations equal an independent reading with
  `python-chess` (steps 2-3).
- **Extracted tables → `player_games`.** The main columns and the evaluation measures
  agree with an independent recomputation on every row (step 6), and so do the sequence
  columns (step 7).
- **Slice → census.** The extracted tables are identical to the census rows of the same
  games; `player_games` agrees wherever the slice has the same information as the census.
  Stockfish values differ only because of the evaluation order, which is shown by
  reproducing census values exactly (step 9).
- **Not checked here.** Games after the slice; the API answers as they were in October
  2026 (profiles change when bots edit their bio); the census list of bot accounts, which
  needs all months.
""",
        """
## 10. 最終的な各列はどこから来るか

| 最終的な列（`player_games`、パネル） | 生データの出どころ | 計算するコード |
|---|---|---|
| `game_id`、`player`、`opponent`、レーティング、`player_rating_diff`、`eco`、`opening_name` | PGN タグ `Site`、`White`/`Black`、`WhiteElo`/`BlackElo`、`*RatingDiff`、`ECO`、`Opening` | `extract._record`、`games.player_row`、`identity.canonicalise` |
| `opponent_is_bot`、どちらが人間か | PGN タグ `WhiteTitle`/`BlackTitle` = `BOT` | `extract.process_block`、`games._focal_sides` |
| `start`、`speed`、`variant`、`is_tournament`、`base_s`、`inc_s` | PGN タグ `UTCDate`、`UTCTime`、`Event`、`TimeControl` | `games.player_row` |
| `player_score`、`outcome`、`end_type`、`loser` | PGN タグ `Result`、`Termination`、最後の SAN の指し手 | `game_metrics.player_score`、`game_metrics.end_type` |
| `expected_score`、`elo_gap` | レーティング | Elo の式 |
| `n_plies`、`opening`、`line` | SAN の指し手 | `games.player_row` |
| 考慮時間、`end`、`duration_s`、最後の残り時間 | `%clk` のコメント | `game_metrics.move_times`、`games.flag_time_s` |
| `has_evals`、損失、大悪手、勝率、`surprise`、`uncertainty`、勝ち切りまでの手数 | 指し直した手に対する Stockfish 19（`sf_evals`） | `engine.evaluate_game`、`game_metrics.eval_metrics` |
| `lichess_analysed` | `%eval` のコメントの有無 | `pipeline._with_engine_evals` |
| 系列の列、`return_7d` | プレイヤーの対局の順序 | `sequences.annotate_sequences` |
| `return_28d`、`return_91d`、`any_return_*`、`player_session_last`、`month` | すべての月を通したプレイヤーの対局の順序 | `panel.add_long_returns`、`panel.build_panel` |
| `n_human_games` | ダンプの中の人間同士の対局 | `extract.process_block`、`identity.activity_by_id` |
| `engine_family`、`created_at_ms` | Lichess API のプロフィール（名前、本名、自己紹介）、コードブック | `bots.classify_engine`、`bots.apply_codebook` |
| Maia の列（`maia_evals`、分析の段階で結合） | 指し直した手に対する lc0 + Maia-1 | `maia.MaiaScorer` |

## 11. 確認のまとめ

- **ダンプ → 抽出した表。** 切り出しのすべての対局が正しい表に入る。人間対ボットのすべての対局のタグ、指し手、残り時間、評価値は、`python-chess` による独立の読み取りと等しい（段階2〜3）。
- **抽出した表 → `player_games`。** 主な列と評価値による指標は、すべての行で独立の再計算と一致する（段階6）。系列の列も同じである（段階7）。
- **切り出し → 本番。** 抽出した表は、同じ対局の本番の行と同一である。`player_games` は、切り出しが本番と同じ情報をもつところではすべて一致する。
  Stockfish の値が異なる理由は評価の順序だけであり、本番の値を正確に再現することでそれを示した（段階9）。
- **ここで確かめていないこと。** 切り出しより後の対局。2026年10月時点の API の応答（ボットが自己紹介を書き換えるとプロフィールは変わる）。すべての月を要する本番のボットのアカウントの一覧。
""",
    ),
    md(
        """
## References

- Collet, Y., & Kucherawy, M. (2021). *Zstandard Compression and the 'application/zstd'
  Media Type* (RFC 8878). IETF. https://doi.org/10.17487/RFC8878
- Edwards, S. J. (1994). *Standard: Portable Game Notation Specification and Implementation
  Guide*. https://www.saremba.de/chessgml/standards/pgn/pgn-complete.htm
- Elo, A. E. (1978). *The Rating of Chessplayers, Past and Present*. Arco.
- Fiekas, N. (2024). *python-chess: a chess library for Python* (version 1.11).
  https://python-chess.readthedocs.io/
- Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP Semantics* (RFC 9110), section
  14 (range requests). IETF. https://doi.org/10.17487/RFC9110
- Glickman, M. E. (2022). *Example of the Glicko-2 system*.
  http://www.glicko.net/glicko/glicko2.pdf
- Lichess (n.d.). *Lichess open database* (https://database.lichess.org/), *API reference*
  (https://lichess.org/api) and the win-probability formula in the Lichess source
  (https://github.com/lichess-org/lila, `WinPercent.scala`).
- McIlroy-Young, R., Sen, S., Kleinberg, J., & Anderson, A. (2020). Aligning superhuman AI
  with human behavior: Chess as a model system. In *Proceedings of the 26th ACM SIGKDD
  International Conference on Knowledge Discovery & Data Mining* (pp. 1677-1687).
  https://doi.org/10.1145/3394486.3403219
- Shannon, C. E. (1948). A mathematical theory of communication. *Bell System Technical
  Journal*, 27(3), 379-423. https://doi.org/10.1002/j.1538-7305.1948.tb01338.x
- Simpson, E. H. (1949). Measurement of diversity. *Nature*, 163, 688.
  https://doi.org/10.1038/163688a0
- Stockfish developers (2026). *Stockfish 19*. https://stockfishchess.org/
""",
        """
## 参考文献

文献の一覧は上の英語版と同じである。本文の（著者, 年）はこの一覧を指す。
""",
    ),
]

CELLS: list[nbformat.NotebookNode] = [
    *INTRO,
    *SETUP,
    *RAW_DUMP,
    *PARSE,
    *EXTRACT,
    *API,
    *ENGINES,
    *FEATURES,
    *SEQUENCES,
    *AGGREGATES,
    *PANEL,
    *LINEAGE,
]


def build(execute: bool) -> Path:
    """Writes the notebook, optionally executing it in place."""
    notebook = nbformat.v4.new_notebook()
    notebook.cells = CELLS
    notebook.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    if execute:
        NotebookClient(
            notebook, timeout=7200, resources={"metadata": {"path": str(ROOT)}}
        ).execute()
    NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, NOTEBOOK)
    return NOTEBOOK


def main() -> None:
    """Parses arguments and writes the notebook."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run every cell before saving")
    print(build(parser.parse_args().execute))


if __name__ == "__main__":
    main()
