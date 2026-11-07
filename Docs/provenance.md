# Provenance and verification

> Japanese version: [provenance.ja.md](provenance.ja.md)

This package is the data-collection part of the project's research code base (`lichess_ai_pref`, commit `1f0a1d4`, 2026-10-27), which produced the 49-month census (August 2022 – August 2026) behind the papers. The collection modules were copied unchanged apart from the package name, so that the copy can be diffed line by line against the code that made the published tables.

## Module map

| Here | Original | Changes |
|---|---|---|
| `api.py`, `pgn.py`, `download.py`, `extract.py`, `bots.py`, `engine.py`, `maia.py`, `io.py`, `pipeline.py` | same names | package name only |
| `features/games.py`, `game_metrics.py`, `sequences.py`, `identity.py`, `bot_features.py`, `bot_accounts.py` | `features/` | package name; the missing-list warning names `lbd bot-accounts` |
| `panel.py` | `analysis/census_panel.py` | package name; two docstrings no longer mention the analysis context |
| `config.py` | `config.py` | paths come from `LBD_*` environment variables; constants of the analysis stage removed |
| `runner.py` | `census.py` (`CensusDriver`, `MonthState`) | rewritten for one computer: same stage order, same stage arguments and marker names, no multi-host claims, scheduling or night mode |
| `cli.py` | `cli.py` | only the collection commands; `run`, `status`, `bot-accounts` and `panel` replace `lap census …` |
| `codebook/` | `codebook/` | unchanged |
| `tests/` | `tests/` | the collection tests; checks of analysis functions removed |

Not carried over: the analysis package (research questions, pooling, reports), the multi-host census driver and its claims, and the API collectors that only the analysis used (user profiles, rating histories, online-bot snapshots).

## How the census was run, and how `lbd run` differs

The census driver ran each stage as a low-priority subprocess (`lap <stage> <month> …`) with time limits and retries. The stage functions and their arguments were the same as those `lbd run` calls:

- `extract <month> --watch-self` (plus `--watch-months <next month>` when the next month was already extracted);
- `profiles <month>` (if the API failed, the month was built without bot families and `.profiles_missing` was written);
- `evaluate <month> --all --resume --limit 3000` in a loop until no game was left (Stockfish 19, 10,000 nodes);
- `maia <month> --resume --limit 3000` in the same way;
- `features <month>`.

Two differences matter for an exact rebuild:

1. **Seeded evaluations.** For 2024-08, 2026-07 and 2026-08 the census copied `sf_evals` and `maia_evals` from earlier full evaluations of those months (folders `<month>-full`) instead of evaluating again. Their node budget is not stored in the files.
2. **Bot profiles reflect the fetch date.** Profiles come from the API when a month is prepared (October 2026 for the census), not from the date of the games. Rerunning `profiles` later can give other families for bots that changed their bio.

The library versions are pinned to those of the census (`uv.lock`).

## Equivalence check (2026-10-30)

The inputs of August 2022 (`bot_games`, `baseline_games`, `user_activity`, `bot_profiles`, `sf_evals`) were copied from the census, `lbd features 2022-08` was run with this package, and the outputs were compared with the census tables with `polars.testing.assert_frame_equal`:

| Table | Result |
|---|---|
| `player_games.parquet` (44,600 rows, 72 columns) | identical |
| `baseline_player_games.parquet` (923,208 rows, 68 columns) | identical |
| `bot_features.parquet` | identical except `main_speed` for 14 bots whose two most frequent speeds tie; `polars` returns tied modes in no fixed order. No analysis of the papers uses this column. |

Not checked end to end on a whole month: download, extraction, profiles and the engine stages, which need a 5–35 GB dump and many engine hours per month.

## Slice audit (2026-11-02)

The notebook [notebooks/BotDataCollection_audit.ipynb](../notebooks/BotDataCollection_audit.ipynb) runs every stage on the first 128 MB of the August 2022 dump (417,400 games, 00:00–05:54 UTC on 1 August; 221 human-vs-BOT games) and compares the slice with the census rows of the same games:

| Stage | Result |
|---|---|
| download, extract | `bot_games`, `bot_vs_bot_games` and `baseline_games` identical to the census; all five tables equal an independent count of the raw text; tags, moves, clocks and `%eval` of every human-vs-BOT game equal an independent reading with `python-chess` |
| evaluate (Stockfish) | values depend on the order of evaluation (the hash table of a process carries over between games): replaying the census order reproduces census values bit for bit; the slice's own order gives a median difference of 13 cp |
| maia | 99.97 % of plies identical |
| features | columns from tags and clocks identical; evaluation columns identical when built from the census Stockfish lists; sequence columns identical on sessions that end inside the slice |
| profiles | the profiles of the slice's 16 bots, fetched again on 2026-11-02, give the same `engine_family` and `created_at_ms` as the census on every row. From some networks (a University of Tokyo address on the same day) Cloudflare answers programs with a challenge (HTTP 403); the notebook then falls back to the census profiles |

## Known properties of the data

- **Missing BOT titles (December 2023 – September 2024).** Many bot accounts appear without the title, and some names change case from game to game. `canonicalise` gives one spelling per lowercase id before sequences are built, and `bot_accounts.parquet` lets analyses drop untitled bots from the human side. The census list has 7,227 accounts, all identified by a BOT title in some month.
- **Engine families.** Keyword rules classify every bot; the hand-coded `codebook/bot_codebook.csv` overrides them for the 80 most played bots of August 2026.
- **End times are estimates** (start plus measured move times, plus the remaining clock of the flagging side in a time forfeit). Return windows start 30 minutes after this estimate.
