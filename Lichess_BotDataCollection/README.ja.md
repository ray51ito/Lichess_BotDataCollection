# Lichess_BotDataCollection

> English version (primary): [README.md](README.md)

[Lichess のオープンデータベース](https://database.lichess.org/)から、レーティング戦の**人間対BOT**の対局をすべて取り出し、分析にそのまま使える Parquet の表にする。表は月ごとに1つのフォルダに入り、さらに複数年を縦に積んだパネルも作る。*Lichess AI preference* プロジェクトの論文（例えば [Lichess_D1](https://github.com/konbraphat51/Lichess_D1)）が共通に使うデータ収集の段階である。

Lichess では、プログラムが Bot API を通じて `BOT` の称号の付いたアカウントで対局し、人は挑戦するボットを自分で選ぶ。表には、対局ごとに、誰が誰と指したか、レーティング、結果、指し手と持ち時間、すべての局面のエンジン評価、そしてプレイヤーがその後に何をしたか（再戦、セッションの終わり、7日・28日・91日以内に同じボットへ戻ってきたか）が入る。

## 作るもの

月 `YYYY-MM` ごとに、`<data>/interim/YYYY-MM/` に次を作る。

| 表 | 内容 |
|---|---|
| `bot_games.parquet` | 人間対BOTのすべての対局（指し手、持ち時間、ヘッダ） |
| `player_games.parquet` | 同じ対局を人間の側から見た表。考慮時間、エンジン評価に基づく指標、系列の結果（再戦、セッション、7日再訪）を含む |
| `bot_profiles.parquet` | その月のボットの Lichess API のプロフィールと、エンジンの系統 |
| `sf_evals.parquet`、`maia_evals.parquet` | すべての局面の Stockfish 19 の評価（1万ノード）。指された手の Maia-1 の確率 |
| `bot_vs_bot_games`、`baseline_games`、`watched_human_games`、`user_activity` | ボット同士の対局、人間どうしのペアの0.5 %の標本、その月のボット戦プレイヤーの人間戦、ユーザーごとの人間戦の数 |
| `bot_features.parquet` | ボットごとに1行の、振る舞いの集計 |

月をまたぐもの：`<data>/interim/census-panel/`（全月を縦に積み、月の境をまたいで系列を作り直し、7日・28日・91日以内の再訪を加えたもの）と、`<data>/external/bot_accounts.parquet`（一部のダンプで BOT の称号なしに現れるものを含む、ボットのアカウントの一覧）。

すべての列は [Docs/data_dictionary.ja.md](Docs/data_dictionary.ja.md) に、コードの構成は [Docs/architecture.ja.md](Docs/architecture.ja.md) に、コードの出どころと確認の方法は [Docs/provenance.ja.md](Docs/provenance.ja.md) に書いた。

## 必要なもの

- Python 3.12 と [uv](https://docs.astral.sh/uv/)
- ディスク：月次ダンプは、取り出しの間だけ1本5〜35 GB を使う（取り出し後に消す）。1か月分の表は0.2〜1 GB
- `evaluate` の段階に [Stockfish 19](https://stockfishchess.org/)
- `maia` の段階に [lc0](https://lczero.org/)（CPU 版。v0.32.1 を使った）と [Maia-1](https://github.com/CSSLab/maia-chess) の重み `maia-1100.pb.gz` … `maia-1900.pb.gz`（`--no-maia` で省ける）
- `database.lichess.org` と Lichess の公開 API への接続（トークンは不要）

## 準備

```bash
uv sync
# データとツールの場所（既定値は ./data と ./data/tools）
export LBD_DATA_ROOT=/path/to/data
export LBD_STOCKFISH=/path/to/stockfish
export LBD_LC0=/path/to/lc0
export LBD_MAIA_WEIGHTS=/path/to/maia-weights
```

すべての場所は環境変数で変えられる：`LBD_DATA_ROOT`、`LBD_RAW_DIR`、`LBD_INTERIM_DIR`、`LBD_EXTERNAL_DIR`、`LBD_TOOLS_DIR`、`LBD_STOCKFISH`、`LBD_LC0`、`LBD_MAIA_WEIGHTS`。

## 使い方

月の範囲を準備する（途中で止めても、同じコマンドをもう一度実行すれば続きから再開する）。

```bash
uv run lbd run 2022-08 2026-08 --newest-first
uv run lbd status 2022-08 2026-08
```

すべての月の準備が終わったら、次を実行する。

```bash
uv run lbd bot-accounts 2022-08 2026-08   # ボットのアカウントの一覧（API を使う）
uv run lbd panel 2022-08 2026-08          # 月を census-panel に縦に積む
```

1か月分の個別の段階：`lbd download`、`lbd extract --watch-self`、`lbd profiles`、`lbd evaluate --all --resume`、`lbd maia --resume`、`lbd features`。オプションは `uv run lbd <command> --help` で見られる。

### 公開した全数調査の設定

論文の基になった表は、次の設定で作った（`lbd run` の既定値である）。

| 設定 | 値 |
|---|---|
| 月 | 2022-08〜2026-08（ダンプ49本）、新しい月から |
| 取り出し | 人間対BOTのすべての対局。その月のボット戦プレイヤーの人間戦（`--watch-self`）と、翌月のボット戦プレイヤーの人間戦 |
| Stockfish | Stockfish 19、1局面あたり10,000ノード、プロセスごとに1スレッドと16 MB のハッシュ。すべての対局を評価 |
| Maia | Maia-1 のネットワーク。手番の側のレーティングに合わせる（1100〜1900）。lc0 v0.32.1 |
| ライブラリの版 | `pyproject.toml` と `uv.lock` で固定（polars 1.44.2、chess 1.11.2） |

### 資源について

- Lichess は、1本のダウンロードにつき約4本を超える並列の範囲接続を絞る。既定値は3本である。
- 1か月分のすべての局面を Stockfish で評価するには、多くの CPU 時間がかかる。49か月の全数調査には、2台の PC でそれぞれ6〜20のエンジンプロセスを使って約10日かかった。`--per-bot N` を使うと、ボットごとの標本だけを評価する。
- 1つのフォルダには、一度に1つの収集だけを走らせる。`lbd run` はロックファイル（`<interim>/.lbd.lock`）を持つ。実行を強制終了したときは、これを消す。
- 生のダンプは、`bot_games.parquet` ができてから初めて消す（`--keep-dump` で残せる）。

## 監査用ノートブック

[notebooks/BotDataCollection_audit.ipynb](notebooks/BotDataCollection_audit.ipynb) は、1つの月次ダンプの先頭（既定は2022年8月の 128 MB、月の最初の約6時間）で、収集の全段階を実行して確かめる。
生データ（ダンプの PGN と Lichess API の JSON）、各段階の中間の表と最終の表の行の例、1局を生のテキストから最終的な行まで追った計算例を示す。
各段階は独立の再計算（`python-chess` による読み直しなど）と照合し、`LBD_INTERIM_DIR` が本番のフォルダを指していれば本番の表と1局ずつ比べる。
設定は環境変数 `LBD_AUDIT_MONTH`、`LBD_AUDIT_SLICE_MB`、`LBD_AUDIT_DIR`、`LBD_AUDIT_WORKERS`、`LBD_AUDIT_ANONYMISE` で変えられる。

```bash
uv run python scripts/build_notebook.py --execute   # ノートブックを作って実行する（約5〜10分）
```

## テストと確認

```bash
uv run pytest            # LBD_TOOLS_DIR がツールを指していれば、Stockfish と lc0 のテストも走る
uv run ruff check src tests
uv run mypy src tests
```

## データのライセンスと引用

Lichess のデータベースは [CC0](https://database.lichess.org/) で公開されている。コードは MIT ライセンスである（[LICENSE](LICENSE)）。データを使った論文と、Lichess のオープンデータベースをあわせて引用してほしい。
