"""Tests for finding bot accounts that dumps show without their BOT title."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import polars as pl

from lichess_bot_data.features.bot_accounts import (
    build_bot_accounts,
    human_players,
    load_bot_accounts,
)
from lichess_bot_data.pipeline import MonthPaths


class FakeApi:
    """Answers ``users`` from a fixed title table."""

    def __init__(self, titles: dict[str, str | None]) -> None:
        self.titles = titles

    def users(self, names: Sequence[str]) -> list[dict[str, Any]]:
        return [
            {"id": n.lower(), "username": n, "title": self.titles.get(n.lower())} for n in names
        ]


def _month(root: Path) -> None:
    paths = MonthPaths(root / "2024-01")
    paths.root.mkdir(parents=True)
    pl.DataFrame(
        {
            "white": ["Alice", "torombot", "BotX"],
            "black": ["BotX", "BotY", "bob"],
            "white_title": [None, None, "BOT"],
            "black_title": ["BOT", "BOT", None],
        }
    ).write_parquet(paths.bot_games)
    # an untitled account that met many bots, and a human who met few
    rows = [{"player": "torombot", "opponent": f"bot{i}"} for i in range(12)]
    rows += [{"player": "Alice", "opponent": "BotX"}, {"player": "zeekat", "opponent": "BotY"}]
    pl.DataFrame(rows).write_parquet(paths.player_games)


def test_bot_accounts_combine_titles_and_api_checks(tmp_path: Path) -> None:
    _month(tmp_path)
    api = FakeApi({"torombot": "BOT", "alice": None})
    table = build_bot_accounts(tmp_path, ["2024-01"], api)  # type: ignore[arg-type]
    rows = dict(zip(table["user"].to_list(), table["source"].to_list(), strict=True))
    assert rows == {"botx": "titled", "boty": "titled", "torombot": "api"}
    path = tmp_path / "bots.parquet"
    table.write_parquet(path)
    assert load_bot_accounts(path) == {"botx", "boty", "torombot"}
    assert load_bot_accounts(tmp_path / "missing.parquet") == set()


def test_bot_accounts_are_dropped_case_insensitively() -> None:
    games = pl.DataFrame(
        {
            "player": ["ToromBot", "alice", "carol"],
            "opponent": ["BotX", "BotX", "torombot"],
            "speed": ["blitz"] * 3,
            "is_tournament": [False] * 3,
            "player_elo": [1500] * 3,
            "opponent_elo": [1500] * 3,
            "player_score": [1.0] * 3,
        }
    )
    bots = {"torombot", "botx"}
    assert human_players(games, bots)["player"].to_list() == ["alice", "carol"]
