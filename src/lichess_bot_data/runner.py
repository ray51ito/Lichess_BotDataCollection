"""Prepares a range of months stage by stage, resumably, on one computer.

Each month runs the stages download+extract, profiles, evaluate, maia and features in
order. A finished stage leaves ``.<stage>_done`` in the month folder (the marker names of
the original census driver), so a stopped run continues where it left off. The dump is
deleted only after ``bot_games.parquet`` exists.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import polars as pl

from lichess_bot_data import config
from lichess_bot_data.download import RangeDownloader
from lichess_bot_data.extract import DumpExtractor
from lichess_bot_data.pipeline import (
    MonthPaths,
    bot_players,
    build_tables,
    collect_profiles,
    evaluate_sample,
    score_maia,
)

STAGES: tuple[str, ...] = ("extract", "profiles", "evaluate", "maia", "features")
"""Per-month stages in run order; each leaves ``.<stage>_done`` in the month folder."""

EVERY_GAME: int = 10**9
"""Per-bot cap that evaluates every game."""


def month_range(first: str, last: str) -> Iterator[str]:
    """Yields ``YYYY-MM`` months from ``first`` to ``last`` inclusive."""
    year, month = (int(p) for p in first.split("-"))
    while f"{year:04d}-{month:02d}" <= last:
        yield f"{year:04d}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def next_month(month: str) -> str:
    """The ``YYYY-MM`` month after ``month``."""
    year, mon = (int(p) for p in month.split("-"))
    return f"{year + 1:04d}-01" if mon == 12 else f"{year:04d}-{mon + 1:02d}"


class MonthState:
    """Marker files that record which stages of one month are complete."""

    def __init__(self, folder: Path) -> None:
        """Wraps a month folder (created on demand)."""
        self.folder = folder

    def done(self, stage: str) -> bool:
        """Whether ``stage`` has completed."""
        return (self.folder / f".{stage}_done").exists()

    def mark(self, stage: str) -> None:
        """Records ``stage`` as complete."""
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f".{stage}_done").touch()

    @property
    def empty(self) -> bool:
        """Whether the month had no human-vs-bot games (nothing after extraction to do)."""
        return (self.folder / ".empty").exists()

    def mark_empty(self) -> None:
        """Records that the month has no human-vs-bot games."""
        (self.folder / ".empty").touch()

    def complete(self) -> bool:
        """Whether nothing is left to do for the month."""
        return self.done("extract") and (self.empty or all(self.done(s) for s in STAGES))


@dataclass(frozen=True)
class RunSettings:
    """Worker counts and engine budgets of a run (defaults: the published census).

    Attributes:
        download_workers: Parallel HTTP range connections (Lichess throttles more than ~4).
        extract_workers: Parser processes during extraction.
        engine_workers: Stockfish / lc0 processes.
        eval_chunk: Games per checkpointed evaluation or Maia step.
        nodes: Stockfish node budget per position.
        per_bot: Games evaluated per bot (None: every game, as in the census).
        maia: Whether to score moves with Maia (needs lc0 and the Maia-1 weights).
        keep_dump: Keep the raw dump after extraction.
    """

    download_workers: int = 3
    extract_workers: int = 4
    engine_workers: int = 6
    eval_chunk: int = 3000
    nodes: int = 10000
    per_bot: int | None = None
    maia: bool = True
    keep_dump: bool = False


class MonthRunner:
    """Runs every pending stage of each requested month, one month at a time."""

    def __init__(self, settings: RunSettings, interim_dir: Path | None = None) -> None:
        """Prepares a run.

        Args:
            settings: Worker counts and engine budgets.
            interim_dir: Folder with one subfolder per month (default ``config.INTERIM_DIR``).
        """
        self._settings = settings
        self._interim = interim_dir or config.INTERIM_DIR

    def paths(self, month: str) -> MonthPaths:
        """Table locations of ``month``."""
        return MonthPaths(self._interim / month)

    def run(self, months: Sequence[str]) -> None:
        """Prepares ``months`` in the given order under an exclusive lock."""
        self._interim.mkdir(parents=True, exist_ok=True)
        lock = self._interim / ".lbd.lock"
        # a second runner on the same folder would duplicate extracts and engine work
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"{lock} exists: another run is active (delete it if not)") from exc
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            for month in months:
                self.run_month(month)
        finally:
            lock.unlink(missing_ok=True)

    def run_month(self, month: str) -> None:
        """Runs the pending stages of one month."""
        state = MonthState(self.paths(month).root)
        for stage in STAGES:
            if state.done(stage) or (stage != "extract" and state.empty):
                continue
            if stage == "maia" and not self._settings.maia:
                continue
            print(f"{month} {stage} start", flush=True)
            getattr(self, f"_{stage}")(month, state)
            if stage != "extract":
                state.mark(stage)
            print(f"{month} {stage} done", flush=True)

    def _extract(self, month: str, state: MonthState) -> None:
        dump = config.dump_path(month)
        if not dump.exists() or dump.with_suffix(dump.suffix + ".progress.json").exists():
            RangeDownloader(config.dump_url(month), dump, self._settings.download_workers).run()
        # the next month's bot players are watched too (their human games in this month)
        following = self.paths(next_month(month))
        watch = bot_players(following) if MonthState(following.root).done("extract") else set()
        paths = self.paths(month)
        DumpExtractor(
            dump,
            paths.root,
            self._settings.extract_workers,
            watch_users=frozenset(watch),
            watch_self=True,
        ).run()
        if not paths.bot_games.exists():
            raise RuntimeError(f"{month}: extraction wrote no bot_games.parquet; dump kept")
        n_games = pl.read_parquet(paths.bot_games, columns=["game_id"]).height
        state.mark("extract")
        if not self._settings.keep_dump:
            dump.unlink(missing_ok=True)
        if n_games == 0:
            state.mark_empty()

    def _profiles(self, month: str, state: MonthState) -> None:
        try:
            collect_profiles(self.paths(month))
        except (httpx.HTTPError, RuntimeError) as exc:
            # bot families are optional for the feature tables: record the gap and go on
            (state.folder / ".profiles_missing").touch()
            print(f"{month} profiles failed ({exc}); continuing without bot families")

    def _evaluate(self, month: str, state: MonthState) -> None:
        del state
        paths = self.paths(month)
        per_bot = self._settings.per_bot or EVERY_GAME
        while True:
            before = _rows(paths.sf_evals)
            evaluate_sample(
                paths,
                per_bot,
                self._settings.nodes,
                self._settings.engine_workers,
                limit=self._settings.eval_chunk,
                resume=True,
            )
            if _rows(paths.sf_evals) == before:
                return

    def _maia(self, month: str, state: MonthState) -> None:
        del state
        paths = self.paths(month)
        while True:
            before = _rows(paths.maia_evals)
            score_maia(paths, self._settings.engine_workers, self._settings.eval_chunk, True)
            if _rows(paths.maia_evals) == before:
                return

    def _features(self, month: str, state: MonthState) -> None:
        del state
        build_tables(self.paths(month))


def _rows(path: Path) -> int:
    if not path.exists():
        return -1
    return int(pl.scan_parquet(path).select(pl.len()).collect().item())


def status_table(interim_dir: Path, months: Sequence[str]) -> pl.DataFrame:
    """One row per month with its completed stages."""
    rows: list[dict[str, object]] = []
    for month in months:
        state = MonthState(interim_dir / month)
        row: dict[str, object] = {"month": month, "empty": state.empty}
        row.update({stage: state.done(stage) for stage in STAGES})
        rows.append(row)
    return pl.DataFrame(rows)
