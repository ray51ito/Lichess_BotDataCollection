# 出どころと確認

> English version (primary): [provenance.md](provenance.md)

このパッケージは、プロジェクトの研究用コード（`lichess_ai_pref`、コミット `1f0a1d4`、2026-10-27）のうち、データ収集の部分である。論文の基になった49か月の全数調査（2022年8月〜2026年8月）は、そのコードで作った。収集のモジュールはパッケージ名のほかは変えずに写したので、公開した表を作ったコードと1行ずつ突き合わせられる。

## モジュールの対応

| ここ | 元 | 変更 |
|---|---|---|
| `api.py`、`pgn.py`、`download.py`、`extract.py`、`bots.py`、`engine.py`、`maia.py`、`io.py`、`pipeline.py` | 同じ名前 | パッケージ名だけ |
| `features/games.py`、`game_metrics.py`、`sequences.py`、`identity.py`、`bot_features.py`、`bot_accounts.py` | `features/` | パッケージ名。一覧がないときの警告が `lbd bot-accounts` を示す |
| `panel.py` | `analysis/census_panel.py` | パッケージ名。2つの docstring から分析側の名前を除いた |
| `config.py` | `config.py` | 場所を `LBD_*` の環境変数から取る。分析段階の定数を除いた |
| `runner.py` | `census.py`（`CensusDriver`、`MonthState`） | 1台の計算機向けに書き直した。段階の順序、段階の引数、目印の名前は同じ。複数台の調整、予定実行、夜間モードはない |
| `cli.py` | `cli.py` | 収集のコマンドだけ。`run`、`status`、`bot-accounts`、`panel` が `lap census …` に代わる |
| `codebook/` | `codebook/` | 変更なし |
| `tests/` | `tests/` | 収集のテスト。分析の関数を確かめる部分は除いた |

写していないもの：分析のパッケージ（研究課題、統合、報告書）、複数台用の全数調査の駆動部とその調整の仕組み、分析だけが使った API の収集（ユーザーのプロフィール、レーティングの履歴、オンラインのボットの記録）。

## 全数調査の実行と、`lbd run` との違い

全数調査の駆動部は、各段階を優先度の低いサブプロセス（`lap <stage> <month> …`）として、時間の上限と再試行つきで走らせた。段階の関数と引数は、`lbd run` が呼ぶものと同じである。

- `extract <month> --watch-self`（翌月がすでに取り出し済みなら `--watch-months <翌月>` も）
- `profiles <month>`（API が失敗したときは、その月をボットの系統なしで作り、`.profiles_missing` を書いた）
- `evaluate <month> --all --resume --limit 3000` を、残りの対局がなくなるまで繰り返す（Stockfish 19、10,000ノード）
- `maia <month> --resume --limit 3000` を同じように
- `features <month>`

完全に作り直すときに効く違いが2つある。

1. **流用した評価。** 2024-08、2026-07、2026-08 では、全数調査は評価をやり直さず、それ以前にその月を全局評価した結果（`<month>-full` のフォルダ）から `sf_evals` と `maia_evals` を写した。そのときのノード数はファイルに残っていない。
2. **ボットのプロフィールは取得した日のもの。** プロフィールは、月を準備したとき（全数調査では2026年10月）に API から取るもので、対局の日のものではない。後で `profiles` をやり直すと、自己紹介を変えたボットでは系統が変わりうる。

ライブラリの版は、全数調査と同じものに固定している（`uv.lock`）。

## 一致の確認（2026-10-30）

2022年8月の入力（`bot_games`、`baseline_games`、`user_activity`、`bot_profiles`、`sf_evals`）を全数調査から写し、このパッケージで `lbd features 2022-08` を実行し、出力を全数調査の表と `polars.testing.assert_frame_equal` で比べた。

| 表 | 結果 |
|---|---|
| `player_games.parquet`（44,600行、72列） | 完全に一致 |
| `baseline_player_games.parquet`（923,208行、68列） | 完全に一致 |
| `bot_features.parquet` | `main_speed` のほかは一致。違ったのは、最も多い持ち時間の区分が2つ同数だった14体のボットで、`polars` は同数の最頻値を決まった順に返さない。論文の分析はこの列を使わない。 |

1か月分を端から端までは確かめていないもの：ダウンロード、取り出し、プロフィール、エンジンの段階。1か月につき5〜35 GB のダンプと多くのエンジン時間が要る。

## 切り出しによる監査（2026-11-02）

ノートブック [notebooks/BotDataCollection_audit.ipynb](../notebooks/BotDataCollection_audit.ipynb) は、2022年8月のダンプの先頭 128 MB（417,400局、8月1日 00:00〜05:54 UTC、人間対BOTは221局）ですべての段階を実行し、切り出しを同じ対局の本番の行と比べる。

| 段階 | 結果 |
|---|---|
| download、extract | `bot_games`、`bot_vs_bot_games`、`baseline_games` は本番と同一。5つの表はすべて生のテキストの独立した集計と一致。人間対BOTのすべての対局のタグ、指し手、残り時間、`%eval` は `python-chess` による独立の読み取りと一致 |
| evaluate（Stockfish） | 値は評価の順序に依存する（プロセスのハッシュ表が対局をまたいで引き継がれる）。本番の順序を再現すると本番の値がビット単位で再現される。切り出し自身の順序では、差の中央値は 13 cp |
| maia | 99.97 % のプライが同一 |
| features | タグと残り時間から作る列は同一。評価値の列は、本番の Stockfish のリストから作ると同一。系列の列は、切り出しの中で終わるセッションについて同一 |
| profiles | 切り出しの16体のボットのプロフィールを2026-11-02に取得し直すと、`engine_family` と `created_at_ms` はすべての行で本番と一致する。ネットワークによっては（同じ日の東京大学のアドレスなど）、Cloudflare がプログラムからの接続に確認を求めて HTTP 403 を返す。そのときノートブックは本番のプロフィールで代わりに進める |

## データについて分かっていること

- **BOT の称号の欠落（2023年12月〜2024年9月）。** 多くのボットのアカウントが称号なしで現れ、一部の名前は対局ごとに大文字・小文字が変わる。`canonicalise` が系列を作る前に小文字の id ごとに表記を1つにし、`bot_accounts.parquet` を使うと、分析で称号のないボットを人間側から除ける。全数調査の一覧には7,227のアカウントがあり、すべてどこかの月の BOT の称号で見つかったものである。
- **エンジンの系統。** すべてのボットをキーワードの規則で分類し、2026年8月に最もよく指された80体については、手作業でコード化した `codebook/bot_codebook.csv` がそれを上書きする。
- **対局の終わりは推定である**（開始時刻に測った考慮時間を足し、時間切れのときは時間切れになった側の残り時間も足す）。再訪の期間は、この推定の30分後から始まる。
