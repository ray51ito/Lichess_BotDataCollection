"""Stacks every census month into one human-vs-bot panel with sequences rebuilt across months.

Single months censor the 7-day return in their last week and restart pair histories on the
first of the month. The panel rebuilds rematches, sessions and returns over the joint
timeline, adds same-bot and any-bot returns at 7, 28 and 91 days, and keeps each player's
human-game counts per month. It is written as an interim folder (``census-panel``) that
analyses load like a month.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import polars as pl

from lichess_bot_data.features.identity import activity_by_id, canonicalise
from lichess_bot_data.features.sequences import SequenceConfig, annotate_sequences
from lichess_bot_data.pipeline import MonthPaths

PANEL_NAME: str = "census-panel"
"""Interim folder name of the stacked panel."""

RETURN_WINDOWS_D: tuple[int, ...] = (7, 28, 91)
"""Return horizons in days."""

SEQUENCE_COLUMNS: tuple[str, ...] = (
    "next_opponent",
    "next_opponent_elo",
    "player_game_index",
    "pair_game_index",
    "gap_next_s",
    "gap_pair_next_s",
    "rematch",
    "continue_session",
    "pair_session_id",
    "switch",
    "session_game_index",
    "session_length",
    "switch_elo_delta",
    "session_last",
    "return_7d",
)
"""Columns ``annotate_sequences`` derives; they are rebuilt over the whole panel."""

UNUSED_COLUMNS: tuple[str, ...] = ("line", "opening_name")
"""Long text columns the panel analyses do not need (dropped to save memory)."""


MIN_UNCENSORED_SHARE: float = 0.5
"""Share of a month's session ends a return rate needs uncensored to be reported."""


def uncensored_sessions(games: pl.DataFrame, outcome: str) -> pl.DataFrame:
    """Session-ending rows with a known ``outcome``, in months where most are known.

    In the last months of the panel most long-horizon returns are censored, and the few
    known ones come only from the month's first days; such months get no return rate.
    """
    ends = games.filter(pl.col("session_last"))
    known = ends.group_by("month").agg(pl.col(outcome).is_not_null().mean().alias("share"))
    months = known.filter(pl.col("share") >= MIN_UNCENSORED_SHARE)["month"].implode()
    return ends.filter(pl.col(outcome).is_not_null() & pl.col("month").is_in(months))


def is_panel(paths: MonthPaths | None) -> bool:
    """Whether ``paths`` point at the stacked census panel."""
    return paths is not None and paths.root.name == PANEL_NAME


def month_index(month: pl.Expr) -> pl.Expr:
    """Months since August 2022 (the first census month) of a ``YYYY-MM`` column."""
    year = month.str.slice(0, 4).cast(pl.Int32)
    return (year - 2022) * 12 + month.str.slice(5, 2).cast(pl.Int32) - 8


def month_number(month: str) -> int:
    """Month index of one ``YYYY-MM`` label (as ``month_index``)."""
    return (int(month[:4]) - 2022) * 12 + int(month[5:7]) - 8


def month_label(index: int) -> str:
    """``YYYY-MM`` of a month index (inverse of ``month_index``)."""
    year, month = divmod(index + 7, 12)
    return f"{2022 + year}-{month + 1:02d}"


def stack_months(interim_dir: Path, months: Sequence[str]) -> pl.DataFrame:
    """Concatenates the months' player tables without their sequence columns.

    Args:
        interim_dir: Folder with one subfolder per month.
        months: Months to stack.
    """
    parts = [
        pl.read_parquet(MonthPaths(interim_dir / month).player_games)
        .drop([*SEQUENCE_COLUMNS, *UNUSED_COLUMNS], strict=False)
        .with_columns(pl.lit(month).alias("month"))
        for month in months
    ]
    # a game near a month boundary can appear in both dumps; keep its first copy
    stacked = pl.concat(parts, how="diagonal_relaxed").unique("game_id", keep="first")
    # accounts keep one spelling over the four years (case varies across dumps)
    return canonicalise(stacked, ["player", "opponent"])


def add_long_returns(games: pl.DataFrame, cfg: SequenceConfig | None = None) -> pl.DataFrame:
    """Adds same-bot (``return_<d>d``) and any-bot (``any_return_<d>d``) returns.

    Same-bot returns are meaningful on ``session_last`` rows, any-bot returns on
    ``player_session_last`` rows (no bot game within the session gap); both are null when
    the window runs past the end of the data.

    Args:
        games: Output of ``annotate_sequences`` over the whole panel.
        cfg: Session gap used to tell a return from a continuation.
    """
    cfg = cfg or SequenceConfig()
    data_end = games["start"].max()
    gap_pair = pl.col("gap_pair_next_s")
    gap_any = pl.col("gap_next_s")
    columns = [
        (gap_any.is_null() | (gap_any > cfg.session_gap_s)).alias("player_session_last"),
    ]
    for days in RETURN_WINDOWS_D:
        window = days * 86400.0
        censored = pl.col("end") > data_end - pl.duration(seconds=window)
        same = (gap_pair > cfg.session_gap_s) & (gap_pair <= window)
        anyb = (gap_any > cfg.session_gap_s) & (gap_any <= window)
        columns += [
            pl.when(censored).then(None).otherwise(same.fill_null(False)).alias(f"return_{days}d"),
            pl.when(censored)
            .then(None)
            .otherwise(anyb.fill_null(False))
            .alias(f"any_return_{days}d"),
        ]
    return games.with_columns(columns)


def monthly_human_games(
    interim_dir: Path, months: Sequence[str], players: pl.Series
) -> pl.DataFrame:
    """Human-game counts per panel player and month (``user``, ``month``, ``n_human_games``).

    Counts are summed over the spellings of an account and reported under the panel's
    spelling of the player.
    """
    names = players.unique()
    ids = names.to_frame("user").with_columns(pl.col("user").str.to_lowercase().alias("id"))
    keep = ids["id"].implode()
    parts = []
    for month in months:
        counts = (
            pl.scan_parquet(MonthPaths(interim_dir / month).user_activity)
            .filter(pl.col("user").str.to_lowercase().is_in(keep))
            .collect()
        )
        parts.append(
            activity_by_id(counts)
            .join(ids, on="id")
            .select("user", pl.col("n_human_games").cast(pl.Int32), pl.lit(month).alias("month"))
        )
    return pl.concat(parts)


def build_panel(interim_dir: Path, months: Sequence[str]) -> MonthPaths:
    """Writes the stacked panel into ``<interim_dir>/census-panel`` and returns its paths.

    Args:
        interim_dir: Census interim folder.
        months: Months in chronological order.
    """
    target = MonthPaths(interim_dir / PANEL_NAME)
    target.root.mkdir(parents=True, exist_ok=True)
    games = add_long_returns(annotate_sequences(stack_months(interim_dir, months)))
    games.write_parquet(target.player_games)
    # the panel has no human baseline; an empty table keeps month loaders working
    games.head(0).write_parquet(target.baseline_player_games)
    monthly_human_games(interim_dir, months, games["player"]).write_parquet(
        target.user_activity_monthly
    )
    latest = MonthPaths(interim_dir / months[-1]).bot_profiles
    if latest.exists():
        pl.read_parquet(latest).write_parquet(target.bot_profiles)
    return target
