# Data Dictionary

> Japanese version: [data_dictionary.ja.md](data_dictionary.ja.md)

All tables are Parquet files in `<data>/interim/<YYYY-MM>/` (`LBD_INTERIM_DIR`).

## `bot_games.parquet` / `baseline_games.parquet` / `bot_vs_bot_games.parquet` / `watched_human_games.parquet` (extracted games)

One row per game. Schema: `extract.GAME_SCHEMA`.

- `bot_games`: every human-vs-BOT game, with moves.
- `baseline_games`: all games of a 0.5% sample of human pairs, without moves.
- `bot_vs_bot_games`: every bot-vs-bot game, without moves (clocks kept to estimate end times). Used to measure when a bot is online and how busy it is.
- `watched_human_games`: every human-vs-human game of a *watched* user, headers only (no moves, clocks or evals). Watched users are the month's own bot players (`lbd extract --watch-self`) and the bot players of the months passed to `--watch-months` (`lbd run` passes the next month when it is already extracted).

| Column | Type | Description |
|---|---|---|
| `game_id` | str | Lichess game id (from the `Site` tag) |
| `event` | str | e.g. `Rated Blitz game`; tournaments contain `tournament` / `swiss` |
| `utc_date`, `utc_time` | str | Start time (UTC) |
| `white`, `black` | str | Usernames |
| `white_elo`, `black_elo` | int? | Glicko-2 ratings at game start (null if `?`) |
| `white_rating_diff`, `black_rating_diff` | int? | Rating change from the game |
| `white_title`, `black_title` | str? | Title; `BOT` marks bot accounts |
| `result`, `termination` | str | PGN result; `Normal`, `Time forfeit`, `Abandoned`, ... |
| `eco`, `opening` | str | Opening classification |
| `time_control` | str | `base+increment` in seconds |
| `sans` | str? | Space-separated SAN moves (null in the baseline) |
| `clocks` | list[int] | Remaining clock (s) after each ply |
| `evals` | list[float]? | Lichess `%eval` (White cp; mate = ±10000). Only present for player-requested analyses |

## `user_activity.parquet`

| Column | Description |
|---|---|
| `user` | Username |
| `n_human_games` | Rated games against non-bot opponents in the month (all speeds) |

## `user_activity_monthly.parquet` (panel only)

| Column | Description |
|---|---|
| `user` | Username |
| `n_human_games` | Rated games against non-bot opponents in that month |
| `month` | `YYYY-MM` |

## `bot_profiles.parquet` (Lichess API)

| Column | Description |
|---|---|
| `bot`, `bot_id` | Username and id |
| `title`, `verified`, `disabled`, `tos_violation` | Account flags at fetch time |
| `created_at_ms`, `seen_at_ms` | Account creation and last-seen time (epoch ms) |
| `play_time_total_s`, `play_time_human_s` | Total play time and play time against humans |
| `real_name`, `bio` | Profile text used for classification |
| `engine_family` | Keyword-based family (`bots.EngineFamily`). At feature-build time, `codebook/bot_codebook.csv` overrides it for the 80 most-played bots |

## `maia_evals.parquet`

One row per game of the Stockfish sample. Lists are aligned with plies; entries are null where a side could not be scored.

| Column | Description |
|---|---|
| `game_id` | Lichess game id |
| `maia_prob` | Probability the rating-matched Maia network gave the move actually played (floored at 5e-5) |
| `maia_top_prob` | Probability of Maia's most likely move in that position |
| `maia_is_top` | Whether the played move was Maia's most likely move |
| `maia_entropy` | Shannon entropy (nats) of Maia's move distribution, a measure of position ambiguity (scored since 2026-10-03; absent in older files) |

## `sf_evals.parquet`

| Column | Description |
|---|---|
| `game_id` | Game id |
| `sf_evals` | Stockfish 19 eval (White cp; mate = ±10000) after each ply, 10k nodes per position |

## `player_games.parquet` (annotated human-vs-bot rows; also the baseline layout)

One row per focal player per game. In the bot table the focal player is the human (`player`) and the bot is the `opponent`. The baseline table has one row for each side.

| Group | Columns |
|---|---|
| Identity and time | `game_id`, `start`, `end` (estimated: measured move times, plus the flagging side's remaining clock in a time forfeit), `duration_s`, `speed` (from the Event tag, or from the time control for variants), `variant` (`standard` / `chess960`), `is_tournament`, `base_s`, `inc_s` |
| Players | `player`, `opponent` (one spelling per account: the most frequent spelling of its lowercase id, per month and over the panel), `player_is_white`, `opponent_is_bot`, `player_elo`, `opponent_elo`, `elo_gap`, `expected_score` (Elo formula) |
| Result | `player_score` (1/0.5/0), `outcome` (win/draw/loss), `player_rating_diff`, `end_type` (checkmate/resign/timeout/draw/abandoned/other), `loser` (player/opponent) |
| Moves | `n_plies`, `opening` (first 6 plies), `line` (first 16 plies), `eco`, `opening_name` |
| Clocks | `player_final_clock_s`, `opponent_final_clock_s` (clock at each side's last move) |
| Think time | `{player,opponent}_time_{mean,median,cv,frac_fast,n}`: seconds per move (first move untimed); `frac_fast` = share of moves ≤ 1 s |
| Evals (Stockfish sample only; null otherwise) | `has_evals`, `opponent_mean_loss`, `player_mean_loss` (mean win-probability loss per move), `opponent_blunders`, `player_blunders` (drops ≥ 0.15), `opponent_mistakes` (≥ 0.10), `lead_changes` (crossings between > 0.6 and < 0.4), `player_max_wp`, `player_min_wp`, `surprise` (Σ\|Δwp\|), `uncertainty` (mean wp(1-wp)), `opponent_conversion_plies`, `player_conversion_plies` (plies from first reaching wp ≥ 0.95 to the end), `final_player_wp` |
| Sequence outcomes | `next_opponent`, `next_opponent_elo`, `gap_next_s`, `rematch`, `continue_session`, `switch`, `switch_elo_delta`, `player_game_index`, `pair_game_index`, `pair_session_id`, `session_game_index`, `session_length`, `session_last`, `gap_pair_next_s`, `return_7d` (null if censored) |
| Joined | `lichess_analysed` (game had Lichess `%eval`), `n_human_games` (summed over the spellings of the account), `engine_family`, `created_at_ms` |

Win probability follows Lichess' formula `wp = 1 / (1 + exp(-0.00368208 · cp))`.

## `bot_features.parquet` (one row per bot)

`n_games`, `n_players`, `games_per_player`, `bot_elo_median`, `main_speed`, `player_elo_median`, `player_score_mean`, `expected_score_mean`, `think_median_s`, `think_cv`, `think_frac_fast`, `lost_by_resign`, `lost_by_mate`, `lost_on_time`, `won_on_time`, `won_by_mate`, `bot_mean_loss`, `bot_blunder_rate`, `n_eval_games`, `rematch_rate`, `return_7d_rate`, `mean_session_length`, `opening_diversity` (mean Gini–Simpson diversity of the bot's first move as White and its reply to 1.e4 as Black).

## `<data>/external/` (Lichess API, not in the dumps)

| File | Columns |
|---|---|
| `bot_accounts.parquet` | `user` (lowercase Lichess id), `source` (`titled`: BOT title in any census month's games; `api`: untitled account confirmed as BOT by the users API). Built by `lbd bot-accounts`; analyses drop these accounts from the human side |

## Census panel (`<data>/interim/census-panel/player_games.parquet`)

The 49 months' `player_games` stacked, without `line` and `opening_name`, with sequences rebuilt over the joint timeline (`lbd panel`). Extra columns:

| Column | Meaning |
|---|---|
| `month` | Source month `YYYY-MM` |
| `player_session_last` | No bot game by the player within the session gap afterwards (end of the player's bot session) |
| `return_7d`, `return_28d`, `return_91d` | Same bot played again between 30 min and 7 / 28 / 91 days later (meaningful on `session_last` rows; null when the window passes the data end) |
| `any_return_7d`, `any_return_28d`, `any_return_91d` | Any bot played again in that window (meaningful on `player_session_last` rows) |

