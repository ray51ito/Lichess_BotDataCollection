# データ辞書

> 英語版（主）: [data_dictionary.md](data_dictionary.md)

すべてのテーブルは `<data>/interim/<YYYY-MM>/`（`LBD_INTERIM_DIR`）内の Parquet ファイルである。

## `bot_games.parquet` / `baseline_games.parquet` / `bot_vs_bot_games.parquet` / `watched_human_games.parquet`（抽出された対局）

1 行が 1 対局に対応する。スキーマ: `extract.GAME_SCHEMA`。

- `bot_games`: 人間対ボットの全対局（指し手つき）。
- `baseline_games`: 人間ペアの 0.5% サンプルの全対局（指し手なし）。
- `bot_vs_bot_games`: ボット同士の全対局（指し手なし。終了時刻を推定するため持ち時間は保持）。ボットがいつオンラインで、どれだけ混んでいたかの測定に使う。
- `watched_human_games`: *監視対象* ユーザーの人間同士の全対局（ヘッダーのみ。指し手・持ち時間・評価値なし）。監視対象は、その月自身のボット対局者（`lbd extract --watch-self`）と、`--watch-months` に渡した月のボット対局者である（`lbd run` は、翌月がすでに取り出し済みならその月を渡す）。

| 列 | 型 | 説明 |
|---|---|---|
| `game_id` | str | Lichess の対局 ID（`Site` タグから取得） |
| `event` | str | 例: `Rated Blitz game`。トーナメントでは `tournament` / `swiss` を含む |
| `utc_date`, `utc_time` | str | 開始時刻（UTC） |
| `white`, `black` | str | ユーザー名 |
| `white_elo`, `black_elo` | int? | 対局開始時点の Glicko-2 レーティング（`?` の場合は null） |
| `white_rating_diff`, `black_rating_diff` | int? | その対局によるレーティング変動 |
| `white_title`, `black_title` | str? | 称号。`BOT` はボットアカウントを示す |
| `result`, `termination` | str | PGN の結果。`Normal`、`Time forfeit`、`Abandoned` など |
| `eco`, `opening` | str | オープニング分類 |
| `time_control` | str | 秒単位の `base+increment` |
| `sans` | str? | 空白区切りの SAN 指し手（ベースラインでは null） |
| `clocks` | list[int] | 各 ply 後の残り持ち時間（s） |
| `evals` | list[float]? | Lichess の `%eval`（白視点 cp、メイトは ±10000）。プレイヤーが解析を要求した対局にのみ存在する |

## `user_activity.parquet`

| 列 | 説明 |
|---|---|
| `user` | ユーザー名 |
| `n_human_games` | 当該月における非ボット相手のレーティング対局数（全スピード） |

## `user_activity_monthly.parquet`（パネルのみ）

| 列 | 説明 |
|---|---|
| `user` | ユーザー名 |
| `n_human_games` | その月の非ボット相手のレーティング戦の局数 |
| `month` | `YYYY-MM` |

## `bot_profiles.parquet`（Lichess API）

| 列 | 説明 |
|---|---|
| `bot`, `bot_id` | ユーザー名と ID |
| `title`, `verified`, `disabled`, `tos_violation` | 取得時点のアカウントフラグ |
| `created_at_ms`, `seen_at_ms` | アカウント作成時刻と最終ログイン時刻（エポックミリ秒） |
| `play_time_total_s`, `play_time_human_s` | 総プレイ時間と対人間のプレイ時間 |
| `real_name`, `bio` | 分類に用いるプロフィールテキスト |
| `engine_family` | キーワードに基づく系統（`bots.EngineFamily`）。特徴量構築時に、最も多く対戦された80ボットについては `codebook/bot_codebook.csv` が優先される |

## `maia_evals.parquet`

1 行が Stockfish サンプルの 1 対局に対応する。リストは ply に揃えてあり、片方の手番を採点できなかった箇所は null。

| 列 | 説明 |
|---|---|
| `game_id` | Lichess の対局 ID |
| `maia_prob` | レーティングを合わせた Maia ネットワークが、実際に指された手に与えた確率（下限 5e-5） |
| `maia_top_prob` | その局面で Maia が最も確率を高く見積もった手の確率 |
| `maia_is_top` | 指された手が Maia の最有力手だったか |
| `maia_entropy` | Maia の手の分布のシャノンエントロピー（nats）。局面の曖昧さの指標（2026-10-03 以降に採点したファイルのみ） |

## `sf_evals.parquet`

| 列 | 説明 |
|---|---|
| `game_id` | 対局 ID |
| `sf_evals` | 各 ply 後の Stockfish 19 評価値（白視点 cp、メイトは ±10000）。1 局面あたり 10k ノード |

## `player_games.parquet`（注釈付きの人間対ボット行。ベースラインも同じレイアウト）

1 行が 1 対局における 1 人の注目プレイヤーに対応する。ボットテーブルでは注目プレイヤーは人間（`player`）であり、ボットは `opponent` である。ベースラインテーブルでは両サイドそれぞれに 1 行ずつ存在する。

| グループ | 列 |
|---|---|
| 識別子と時刻 | `game_id`, `start`, `end`（推定値：計測した手番時間の合計。時間切れでは、切れた側の残り時間を加える）, `duration_s`, `speed`（Event タグから。バリアントでは持ち時間から推定）, `variant`（`standard` / `chess960`）, `is_tournament`, `base_s`, `inc_s` |
| プレイヤー | `player`, `opponent`（アカウントごとに1つの表記：小文字のidごとに最も多い表記。月ごとと、パネル全体でそろえる）, `player_is_white`, `opponent_is_bot`, `player_elo`, `opponent_elo`, `elo_gap`, `expected_score`（Elo の式） |
| 結果 | `player_score`（1/0.5/0）, `outcome`（win/draw/loss）, `player_rating_diff`, `end_type`（checkmate/resign/timeout/draw/abandoned/other）, `loser`（player/opponent） |
| 指し手 | `n_plies`, `opening`（最初の 6 ply）, `line`（最初の 16 ply）, `eco`, `opening_name` |
| 持ち時間 | `player_final_clock_s`, `opponent_final_clock_s`（各サイドの最終手時点の持ち時間） |
| 思考時間 | `{player,opponent}_time_{mean,median,cv,frac_fast,n}`: 1 手あたりの秒数（初手は計時なし）。`frac_fast` = 1 s 以下の手の割合 |
| 評価値（Stockfish サンプルのみ。それ以外は null） | `has_evals`, `opponent_mean_loss`, `player_mean_loss`（1 手あたりの平均勝率損失）, `opponent_blunders`, `player_blunders`（0.15 以上の低下）, `opponent_mistakes`（0.10 以上）, `lead_changes`（> 0.6 と < 0.4 の間の往来回数）, `player_max_wp`, `player_min_wp`, `surprise`（Σ\|Δwp\|）, `uncertainty`（wp(1-wp) の平均）, `opponent_conversion_plies`, `player_conversion_plies`（初めて wp ≥ 0.95 に達してから終局までの ply 数）, `final_player_wp` |
| 系列アウトカム | `next_opponent`, `next_opponent_elo`, `gap_next_s`, `rematch`, `continue_session`, `switch`, `switch_elo_delta`, `player_game_index`, `pair_game_index`, `pair_session_id`, `session_game_index`, `session_length`, `session_last`, `gap_pair_next_s`, `return_7d`（打ち切りの場合は null） |
| 結合列 | `lichess_analysed`（対局に Lichess の `%eval` があったか）, `n_human_games`（アカウントの全表記の合計）, `engine_family`, `created_at_ms` |

勝率は Lichess の式 `wp = 1 / (1 + exp(-0.00368208 · cp))` に従う。

## `bot_features.parquet`（1 行が 1 ボットに対応）

`n_games`, `n_players`, `games_per_player`, `bot_elo_median`, `main_speed`, `player_elo_median`, `player_score_mean`, `expected_score_mean`, `think_median_s`, `think_cv`, `think_frac_fast`, `lost_by_resign`, `lost_by_mate`, `lost_on_time`, `won_on_time`, `won_by_mate`, `bot_mean_loss`, `bot_blunder_rate`, `n_eval_games`, `rematch_rate`, `return_7d_rate`, `mean_session_length`, `opening_diversity`（白番でのボットの初手、および黒番での 1.e4 に対する応手の Gini–Simpson 多様度の平均）。

## `<data>/external/`（Lichess API。ダンプには含まれない）

| ファイル | 列 |
|---|---|
| `bot_accounts.parquet` | `user`（小文字のLichess id）、`source`（`titled`：全数調査のどこかの月の対局でBOTの称号がある、`api`：称号のないアカウントでusers APIによりBOTと確認）。`lbd bot-accounts` で作る。分析ではこれらのアカウントを人間側から除く |

## 全数調査のパネル（`<data>/interim/census-panel/player_games.parquet`）

49か月の `player_games` を縦積みしたもの。`line` と `opening_name` は除き、シーケンスは共通の時間軸の上で作り直している（`lbd panel`）。追加の列は次のとおり。

| 列 | 意味 |
|---|---|
| `month` | 元の月 `YYYY-MM` |
| `player_session_last` | その後セッションの間隔内にプレイヤーのボット対局がない（プレイヤーのボットセッションの終わり） |
| `return_7d`、`return_28d`、`return_91d` | 30分後から7／28／91日後までに同じボットとまた指した（`session_last` の行で意味を持つ。期間がデータの終わりを越えるとnull） |
| `any_return_7d`、`any_return_28d`、`any_return_91d` | その期間にどれかのボットとまた指した（`player_session_last` の行で意味を持つ） |

