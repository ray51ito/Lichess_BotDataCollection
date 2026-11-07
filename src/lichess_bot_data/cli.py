"""Command-line entry point (``lbd <command>``) for every collection stage."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

import polars as pl

from lichess_bot_data import config
from lichess_bot_data.download import RangeDownloader
from lichess_bot_data.extract import DumpExtractor
from lichess_bot_data.features.bot_accounts import BOT_ACCOUNTS_PATH, build_bot_accounts
from lichess_bot_data.panel import build_panel
from lichess_bot_data.pipeline import (
    MonthPaths,
    bot_players,
    build_tables,
    collect_profiles,
    evaluate_sample,
    score_maia,
)
from lichess_bot_data.runner import (
    EVERY_GAME,
    MonthRunner,
    MonthState,
    RunSettings,
    month_range,
    status_table,
)


def _cmd_download(args: argparse.Namespace) -> None:
    RangeDownloader(
        config.dump_url(args.month),
        config.dump_path(args.month),
        args.workers,
        max_mb_s=args.max_mb_s,
    ).run()


def _cmd_extract(args: argparse.Namespace) -> None:
    watch: set[str] = set()
    for month in args.watch_months or []:
        watch |= bot_players(MonthPaths.for_month(month))
    print(f"watching {len(watch):,} users", flush=True)
    dump = Path(args.dump) if args.dump else config.dump_path(args.month)
    extractor = DumpExtractor(
        dump,
        MonthPaths.for_month(args.month).root,
        args.workers,
        watch_users=frozenset(watch),
        watch_self=args.watch_self,
    )
    print(extractor.run())


def _cmd_profiles(args: argparse.Namespace) -> None:
    print(collect_profiles(MonthPaths.for_month(args.month))["engine_family"].value_counts())


def _cmd_evaluate(args: argparse.Namespace) -> None:
    per_bot = EVERY_GAME if args.all else args.per_bot
    evaluate_sample(
        MonthPaths.for_month(args.month),
        per_bot,
        args.nodes,
        args.workers,
        limit=args.limit,
        resume=args.resume,
    )


def _cmd_maia(args: argparse.Namespace) -> None:
    score_maia(MonthPaths.for_month(args.month), args.workers, args.limit, args.resume)


def _cmd_features(args: argparse.Namespace) -> None:
    build_tables(MonthPaths.for_month(args.month))


def _prepared(months: Sequence[str]) -> list[str]:
    # months with every stage done and at least one human-vs-bot game
    return [
        m
        for m in months
        if MonthState(config.INTERIM_DIR / m).complete()
        and not MonthState(config.INTERIM_DIR / m).empty
    ]


def _cmd_bot_accounts(args: argparse.Namespace) -> None:
    # every extracted month counts: a missing table is skipped month by month
    months = [m for m in month_range(args.first, args.last) if (config.INTERIM_DIR / m).is_dir()]
    table = build_bot_accounts(config.INTERIM_DIR, months)
    BOT_ACCOUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.write_parquet(BOT_ACCOUNTS_PATH)
    print(f"{table.height} bot accounts -> {BOT_ACCOUNTS_PATH}")


def _cmd_panel(args: argparse.Namespace) -> None:
    months = _prepared(list(month_range(args.first, args.last)))
    print(f"stacking {len(months)} months", flush=True)
    print(f"panel -> {build_panel(config.INTERIM_DIR, months).root}")


def _cmd_run(args: argparse.Namespace) -> None:
    months = list(month_range(args.first, args.last))
    if args.newest_first:
        months.reverse()
    settings = RunSettings(
        download_workers=args.download_workers,
        extract_workers=args.extract_workers,
        engine_workers=args.engine_workers,
        eval_chunk=args.eval_chunk,
        nodes=args.nodes,
        per_bot=args.per_bot,
        maia=not args.no_maia,
        keep_dump=args.keep_dump,
    )
    MonthRunner(settings).run(months)


def _cmd_status(args: argparse.Namespace) -> None:
    table = status_table(config.INTERIM_DIR, list(month_range(args.first, args.last)))
    # ASCII borders: some Windows consoles cannot print box-drawing characters
    with pl.Config(tbl_rows=-1, tbl_formatting="ASCII_MARKDOWN"):
        print(table)


def _add_range(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("first", help="first month, YYYY-MM")
    parser.add_argument("last", help="last month, YYYY-MM")


def _add_stage_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    download = sub.add_parser("download", help="download a monthly dump")
    download.add_argument("month", help="YYYY-MM")
    download.add_argument("--workers", type=int, default=4)
    download.add_argument("--max-mb-s", type=float, help="cap the download rate (MB/s)")
    download.set_defaults(func=_cmd_download)

    extract = sub.add_parser("extract", help="extract human-vs-BOT games from a dump")
    extract.add_argument("month", help="YYYY-MM")
    extract.add_argument("--workers", type=int, default=4)
    extract.add_argument(
        "--watch-months", nargs="*", help="months whose bot players' human games are also kept"
    )
    extract.add_argument("--dump", help="dump file to read instead of the standard monthly dump")
    extract.add_argument(
        "--watch-self", action="store_true", help="also keep this month's bot players' human games"
    )
    extract.set_defaults(func=_cmd_extract)

    profiles = sub.add_parser("profiles", help="fetch bot profiles from the Lichess API")
    profiles.add_argument("month", help="YYYY-MM")
    profiles.set_defaults(func=_cmd_profiles)

    evaluate = sub.add_parser("evaluate", help="Stockfish-evaluate a month's games")
    evaluate.add_argument("month", help="YYYY-MM")
    evaluate.add_argument("--per-bot", type=int, default=400)
    evaluate.add_argument("--nodes", type=int, default=10000)
    evaluate.add_argument("--workers", type=int, default=6)
    evaluate.add_argument("--all", action="store_true", help="evaluate every game (no per-bot cap)")
    evaluate.add_argument("--limit", type=int, help="evaluate at most this many new games")
    evaluate.add_argument("--resume", action="store_true", help="add to existing evals")
    evaluate.set_defaults(func=_cmd_evaluate)

    maia = sub.add_parser("maia", help="score played moves with rating-matched Maia networks")
    maia.add_argument("month", help="YYYY-MM")
    maia.add_argument("--workers", type=int, default=6)
    maia.add_argument("--limit", type=int, help="score at most this many new games")
    maia.add_argument("--resume", action="store_true", help="add to existing Maia scores")
    maia.set_defaults(func=_cmd_maia)

    features = sub.add_parser("features", help="build the annotated player and bot tables")
    features.add_argument("month", help="YYYY-MM")
    features.set_defaults(func=_cmd_features)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lbd", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    _add_stage_commands(sub)

    run = sub.add_parser("run", help="prepare every month of a range (resumable)")
    _add_range(run)
    run.add_argument("--newest-first", action="store_true", help="process the newest month first")
    run.add_argument("--download-workers", type=int, default=3)
    run.add_argument("--extract-workers", type=int, default=4)
    run.add_argument("--engine-workers", type=int, default=6)
    run.add_argument("--eval-chunk", type=int, default=3000)
    run.add_argument("--nodes", type=int, default=10000)
    run.add_argument("--per-bot", type=int, help="evaluate a per-bot sample (default: every game)")
    run.add_argument("--no-maia", action="store_true", help="skip the Maia stage")
    run.add_argument("--keep-dump", action="store_true", help="keep raw dumps after extraction")
    run.set_defaults(func=_cmd_run)

    status = sub.add_parser("status", help="show which stages of each month are done")
    _add_range(status)
    status.set_defaults(func=_cmd_status)

    accounts = sub.add_parser("bot-accounts", help="list bot accounts, incl. untitled ones (API)")
    _add_range(accounts)
    accounts.set_defaults(func=_cmd_bot_accounts)

    panel = sub.add_parser("panel", help="stack prepared months into the census panel")
    _add_range(panel)
    panel.set_defaults(func=_cmd_panel)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Parses arguments and dispatches to the selected stage."""
    args = _build_parser().parse_args(argv)
    func: Callable[[argparse.Namespace], None] = args.func
    func(args)
