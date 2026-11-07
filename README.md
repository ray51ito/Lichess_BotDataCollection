# Lichess_BotDataCollection

> Japanese version: [README.ja.md](README.ja.md)

Collects every rated **human-vs-BOT** chess game from the [Lichess open database](https://database.lichess.org/) into analysis-ready Parquet tables, one folder per month, plus a stacked multi-year panel. It is the shared data stage of the papers of the *Lichess AI preference* project (for example [Lichess_D1](https://github.com/konbraphat51/Lichess_D1)).

On Lichess, programs play through the Bot API under accounts titled `BOT`, and people choose which bot to challenge. The tables keep, for every game, who played whom, the ratings, the result, the moves and clocks, engine evaluations of every position, and what the player did next (rematch, end of session, return to the same bot within 7, 28 or 91 days).

## What it produces

For each month `YYYY-MM`, in `<data>/interim/YYYY-MM/`:

| Table | Contents |
|---|---|
| `bot_games.parquet` | Every human-vs-BOT game with moves, clocks and headers |
| `player_games.parquet` | The same games from the human's side, with think times, engine-based measures and sequence outcomes (rematch, session, 7-day return) |
| `bot_profiles.parquet` | Lichess API profiles of the month's bots, with an engine family |
| `sf_evals.parquet`, `maia_evals.parquet` | Stockfish 19 evaluations (10k nodes) of every position; Maia-1 probabilities of the moves played |
| `bot_vs_bot_games`, `baseline_games`, `watched_human_games`, `user_activity` | Bot-vs-bot games, a 0.5% sample of human pairs, the human games of the month's bot players, human-game counts per user |
| `bot_features.parquet` | One row per bot with aggregate behaviour |

Across months: `<data>/interim/census-panel/` (every month stacked, sequences rebuilt across month boundaries, returns within 7, 28 and 91 days) and `<data>/external/bot_accounts.parquet` (bot accounts, including those some dumps show without the BOT title).

Every column is described in [Docs/data_dictionary.md](Docs/data_dictionary.md). How the code is organised is in [Docs/architecture.md](Docs/architecture.md); where it comes from and how it was checked is in [Docs/provenance.md](Docs/provenance.md).

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Disk: one monthly dump is 5–35 GB while it is being extracted (it is deleted afterwards); the tables of one month take 0.2–1 GB
- [Stockfish 19](https://stockfishchess.org/) for the `evaluate` stage
- [lc0](https://lczero.org/) (CPU build; v0.32.1 was used) and the [Maia-1](https://github.com/CSSLab/maia-chess) weights `maia-1100.pb.gz` … `maia-1900.pb.gz` for the `maia` stage (optional: `--no-maia`)
- Network access to `database.lichess.org` and the public Lichess API (no token needed)

## Setup

```bash
uv sync
# where data and tools live (defaults: ./data, ./data/tools)
export LBD_DATA_ROOT=/path/to/data
export LBD_STOCKFISH=/path/to/stockfish
export LBD_LC0=/path/to/lc0
export LBD_MAIA_WEIGHTS=/path/to/maia-weights
```

All paths can be moved with environment variables: `LBD_DATA_ROOT`, `LBD_RAW_DIR`, `LBD_INTERIM_DIR`, `LBD_EXTERNAL_DIR`, `LBD_TOOLS_DIR`, `LBD_STOCKFISH`, `LBD_LC0`, `LBD_MAIA_WEIGHTS`.

## Usage

Prepare a range of months (resumable: stop it at any time and run the same command again):

```bash
uv run lbd run 2022-08 2026-08 --newest-first
uv run lbd status 2022-08 2026-08
```

Then, once every month is prepared:

```bash
uv run lbd bot-accounts 2022-08 2026-08   # list bot accounts (needs the API)
uv run lbd panel 2022-08 2026-08          # stack the months into census-panel
```

Single stages, for one month: `lbd download`, `lbd extract --watch-self`, `lbd profiles`, `lbd evaluate --all --resume`, `lbd maia --resume`, `lbd features`. Run `uv run lbd <command> --help` for their options.

### Settings of the published census

The tables behind the papers were built with these settings (they are the defaults of `lbd run`):

| Setting | Value |
|---|---|
| Months | 2022-08 to 2026-08 (49 dumps), newest first |
| Extraction | every human-vs-BOT game; the human games of the month's own bot players (`--watch-self`) and of the next month's bot players |
| Stockfish | Stockfish 19, 10,000 nodes per position, 1 thread and 16 MB hash per process, every game evaluated |
| Maia | Maia-1 networks, rating-matched (1100–1900) to the side to move, lc0 v0.32.1 |
| Library versions | pinned in `pyproject.toml` / `uv.lock` (polars 1.44.2, chess 1.11.2) |

### Resources

- Lichess throttles more than about 4 parallel range connections per download; the default is 3.
- Evaluating every position of a month with Stockfish takes many CPU-hours; the 49-month census took about ten days on two PCs with 6–20 engine processes each. `--per-bot N` evaluates a per-bot sample instead.
- Run one collection at a time on a folder: `lbd run` holds a lock file (`<interim>/.lbd.lock`; delete it if a run was killed).
- A raw dump is deleted only after `bot_games.parquet` exists (`--keep-dump` keeps it).

## Audit notebook

[notebooks/BotDataCollection_audit.ipynb](notebooks/BotDataCollection_audit.ipynb) runs and checks every stage of the collection on the start of one monthly dump (by default the first 128 MB of August 2022, about the first six hours of the month). It shows the raw data (the dump's PGN and the Lichess API's JSON), sample rows of every intermediate and final table, and one game followed from its raw text to its final row. Each stage is checked against an independent recomputation (for example, the games are read again with `python-chess`), and, when `LBD_INTERIM_DIR` points at the census folders, compared game by game with the census tables. Settings: `LBD_AUDIT_MONTH`, `LBD_AUDIT_SLICE_MB`, `LBD_AUDIT_DIR`, `LBD_AUDIT_WORKERS`, `LBD_AUDIT_ANONYMISE`.

```bash
uv run python scripts/build_notebook.py --execute   # writes and runs the notebook (about 5-10 minutes)
```

## Tests and checks

```bash
uv run pytest            # Stockfish/lc0 tests run when LBD_TOOLS_DIR points at the tools
uv run ruff check src tests
uv run mypy src tests
```

## Data licence and citation

The Lichess database is released under [CC0](https://database.lichess.org/). The code is MIT-licensed (see [LICENSE](LICENSE)). Please cite the paper that uses the data together with the Lichess open database.
