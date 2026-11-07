# Architecture

> Japanese version: [architecture.ja.md](architecture.ja.md)

`lichess_bot_data` is a batch pipeline. Each stage reads and writes Parquet files in one month folder (`<data>/interim/YYYY-MM/`), so a stage can be rerun on its own, and a marker file `.<stage>_done` records what is finished.

## Stages and data flow

```mermaid
flowchart LR
    dump[(monthly dump<br/>.pgn.zst)] -->|download| raw[raw/]
    raw -->|extract| games[bot_games<br/>bot_vs_bot_games<br/>baseline_games<br/>watched_human_games<br/>user_activity]
    games -->|profiles: Lichess API| prof[bot_profiles]
    games -->|evaluate: Stockfish| sf[sf_evals]
    sf -->|maia: lc0 + Maia-1| maia[maia_evals]
    games --> feat
    prof --> feat
    sf --> feat
    feat[features] --> pg[player_games<br/>baseline_player_games<br/>bot_features]
    pg -->|panel: all months| panel[census-panel/<br/>player_games<br/>user_activity_monthly]
    games -->|bot-accounts: all months + API| acc[external/<br/>bot_accounts]
```

| Stage | Module | What it does |
|---|---|---|
| download | `download.py` | Resumable HTTP range download with a few parallel connections; progress in a sidecar JSON |
| extract | `extract.py`, `pgn.py` | Streams the zstd dump in game-aligned blocks through a process pool; keeps human-vs-BOT games with moves, other kinds without |
| profiles | `bots.py`, `api.py` | Fetches the bots' public profiles (300 per request) and classifies their engine family by keywords |
| evaluate | `engine.py` | Stockfish evaluation of every position, in checkpointed chunks |
| maia | `maia.py` | Probability that the rating-matched Maia-1 network plays each move |
| features | `features/*.py`, `pipeline.py` | Player-side table, think times, engine measures, canonical names, sequence outcomes, codebook families, bot aggregates |
| panel | `panel.py` | Stacks months, rebuilds sequences across month boundaries, adds 28- and 91-day and any-bot returns |
| bot-accounts | `features/bot_accounts.py` | Lowercase ids of every account shown as BOT in any month, plus untitled accounts confirmed by the API |
| run / status | `runner.py`, `cli.py` | Runs the stages of a month range in order and resumes from the markers |

## Classes

```mermaid
classDiagram
    class MonthRunner {
        +run(months)
        +run_month(month)
        +paths(month) MonthPaths
    }
    class RunSettings {
        download_workers
        extract_workers
        engine_workers
        eval_chunk
        nodes
        per_bot
        maia
        keep_dump
    }
    class MonthState {
        +done(stage) bool
        +mark(stage)
        +empty bool
        +complete() bool
    }
    class MonthPaths {
        root
        bot_games
        player_games
        sf_evals
        maia_evals
        bot_profiles
        +for_month(month)$
    }
    class RangeDownloader {
        +run() Path
    }
    class DownloadPlan {
        +pending() list
        +rechunked(size)
    }
    class DumpExtractor {
        +run() ExtractionSummary
    }
    class BlockResult
    class BotProfileCollector {
        +collect(names, path)
    }
    class LichessApi {
        +users(names)
        +user(name)
    }
    class StockfishEvaluator {
        +evaluate(games)
    }
    class MaiaScorer {
        +score(games)
    }
    class MaiaPolicy {
        +probabilities(moves)
    }
    MonthRunner --> RunSettings
    MonthRunner --> MonthState
    MonthRunner --> MonthPaths
    MonthRunner ..> RangeDownloader
    MonthRunner ..> DumpExtractor
    RangeDownloader --> DownloadPlan
    DumpExtractor ..> BlockResult : process_block
    MonthRunner ..> BotProfileCollector : collect_profiles
    BotProfileCollector --> LichessApi
    MonthRunner ..> StockfishEvaluator : evaluate_sample
    MonthRunner ..> MaiaScorer : score_maia
    MaiaScorer ..> MaiaPolicy
```

The features stage is a set of functions rather than classes: `build_player_table` (one row per game from the focal player's side), `canonicalise` (one spelling per lowercase id), `annotate_sequences` (rematch, session, 7-day return), `apply_codebook` and `aggregate_bot_features`, called in that order by `pipeline.build_tables`.

## One month in `lbd run`

```mermaid
sequenceDiagram
    participant CLI as lbd run
    participant R as MonthRunner
    participant S as MonthState
    participant L as Lichess
    participant E as Engines
    CLI->>R: run(months)
    R->>R: take .lbd.lock
    loop each month
        R->>S: done(extract)?
        alt not extracted
            R->>L: download dump (range requests)
            R->>R: DumpExtractor.run (watch-self, next month's players)
            R->>S: mark extract, delete dump
        end
        R->>L: profiles (POST /api/users)
        R->>S: mark profiles
        loop until no new game
            R->>E: Stockfish on 3,000 games (resume)
        end
        R->>S: mark evaluate
        loop until no new game
            R->>E: Maia on 3,000 games (resume)
        end
        R->>S: mark maia
        R->>R: build_tables (features)
        R->>S: mark features
    end
    R->>R: release lock
```

## Outcome definitions

They are fixed in `features/sequences.py` (`SequenceConfig`) and `panel.py`:

- **Rematch**: the player's next game is against the same bot and starts within 120 s of this game's end.
- **Session**: games against one bot whose gaps (end to next start) are at most 30 minutes.
- **Return within N days**: after a session's last game, the same bot is played again more than 30 minutes and at most N days later. It is null when the window runs past the last game of the data (per month for the month tables, over the whole panel for the panel).
- **Game end** is estimated from the start time plus the measured move times, plus the flagging side's remaining clock in a time forfeit.

## Design notes

- Every write goes through `io.write_parquet_atomic`, so a crash leaves the old file or none.
- Engine processes are started per batch and quit inside the task: a python-chess engine kept in a pool worker blocks the worker's exit.
- Names are case-varied in the December 2023 – September 2024 dumps, so sequences are built after `canonicalise`, and joins with activity and profiles use lowercase ids.
