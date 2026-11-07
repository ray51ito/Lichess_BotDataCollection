"""Finds bot accounts that monthly dumps show without their BOT title.

In some dumps (December 2023 to September 2024) many bot accounts lack the ``BOT`` title,
so their games against titled bots look like human-vs-bot games. An account counts as a bot
when it carries the title in any month's games, or when the Lichess API reports the title
for an untitled account that played many different bots in one month. Names are kept as
lowercase Lichess ids, because the same dumps also write some accounts in lowercase.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from lichess_bot_data import config
from lichess_bot_data.api import USERS_BATCH, LichessApi
from lichess_bot_data.pipeline import MonthPaths

BOT_ACCOUNTS_PATH: Path = config.EXTERNAL_DIR / "bot_accounts.parquet"
"""Known bot accounts (``user`` as a lowercase id, ``source``), read by the analysis context."""

SUSPECT_MIN_BOTS: int = 10
"""Distinct bot opponents in one month that make an untitled account worth checking."""

BOT_TITLE: str = "BOT"
"""Lichess title of bot accounts."""


def titled_bots(interim_dir: Path, months: Sequence[str]) -> set[str]:
    """Accounts shown with the BOT title in any month's human-vs-bot or bot-vs-bot games."""
    names: set[str] = set()
    for month in months:
        paths = MonthPaths(interim_dir / month)
        for path in (paths.bot_games, paths.bot_vs_bot_games):
            if not path.exists():
                continue
            games = pl.read_parquet(path, columns=["white", "black", "white_title", "black_title"])
            for side in ("white", "black"):
                titled = games.filter(pl.col(f"{side}_title") == BOT_TITLE)[side]
                names.update(titled.str.to_lowercase().unique().to_list())
    return names


def suspects(interim_dir: Path, months: Sequence[str], known: set[str]) -> list[str]:
    """Untitled players who faced at least ``SUSPECT_MIN_BOTS`` different bots in a month.

    Args:
        interim_dir: Folder with one subfolder per month.
        months: Months to scan.
        known: Lowercase ids already known to be bots (not checked again).
    """
    found: set[str] = set()
    for month in months:
        path = MonthPaths(interim_dir / month).player_games
        if not path.exists():
            continue
        busy = (
            pl.read_parquet(path, columns=["player", "opponent"])
            .group_by("player")
            .agg(pl.col("opponent").n_unique().alias("bots"))
            .filter(pl.col("bots") >= SUSPECT_MIN_BOTS)
        )
        found.update(busy["player"].to_list())
    return sorted(name for name in found if name.lower() not in known)


def confirmed_by_api(names: Sequence[str], api: LichessApi | None = None) -> set[str]:
    """Lowercase ids of the accounts in ``names`` whose Lichess profile has the BOT title."""
    api = api or LichessApi()
    bots: set[str] = set()
    for start in range(0, len(names), USERS_BATCH):
        for user in api.users(names[start : start + USERS_BATCH]):
            if user.get("title") == BOT_TITLE:
                bots.add(str(user.get("id") or user.get("username", "")).lower())
    return bots


def build_bot_accounts(
    interim_dir: Path, months: Sequence[str], api: LichessApi | None = None
) -> pl.DataFrame:
    """Every known bot account with how it was identified (``titled`` or ``api``)."""
    titled = titled_bots(interim_dir, months)
    checked = confirmed_by_api(suspects(interim_dir, months, titled), api)
    return pl.DataFrame(
        {
            "user": [*sorted(titled), *sorted(checked)],
            "source": ["titled"] * len(titled) + ["api"] * len(checked),
        }
    )


def load_bot_accounts(path: Path = BOT_ACCOUNTS_PATH) -> set[str]:
    """Lowercase ids of the known bot accounts (empty when the list has not been built)."""
    if not path.exists():
        warnings.warn(
            f"{path} is missing: untitled bot accounts stay on the human side "
            "(run `lbd bot-accounts`)",
            stacklevel=2,
        )
        return set()
    return set(pl.read_parquet(path, columns=["user"])["user"].to_list())


def human_players(table: pl.DataFrame, bots: set[str] | None = None) -> pl.DataFrame:
    """Rows of a player table whose ``player`` is not a known bot account."""
    known = load_bot_accounts() if bots is None else bots
    return table.filter(~pl.col("player").str.to_lowercase().is_in(known))
