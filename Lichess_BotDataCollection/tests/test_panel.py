"""Tests for the stacked census panel."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from lichess_bot_data.panel import (
    PANEL_NAME,
    build_panel,
    is_panel,
    uncensored_sessions,
)
from lichess_bot_data.pipeline import MonthPaths


def _game(gid: str, player: str, opponent: str, start: datetime) -> dict[str, object]:
    return {
        "game_id": gid,
        "player": player,
        "opponent": opponent,
        "start": start,
        "end": start + timedelta(minutes=5),
        "opponent_elo": 1500,
        "line": "e4 e5",
        "rematch": False,
        "return_7d": None,
    }


def _write_month(root: Path, month: str, games: list[dict[str, object]]) -> None:
    paths = MonthPaths(root / month)
    paths.root.mkdir(parents=True)
    pl.DataFrame(games).write_parquet(paths.player_games)
    pl.DataFrame({"user": ["a", "x"], "n_human_games": [3, 9]}).write_parquet(paths.user_activity)


def test_panel_follows_players_across_month_boundaries(tmp_path: Path) -> None:
    end_aug = datetime(2026, 8, 31, 23, 50, tzinfo=UTC)
    _write_month(
        tmp_path,
        "2026-08",
        [
            _game("g1", "a", "bot1", datetime(2026, 8, 30, tzinfo=UTC)),
            _game("g2", "a", "bot1", end_aug),
        ],
    )
    _write_month(
        tmp_path,
        "2026-09",
        [
            # rematch one minute after g2 ended, in the next month's dump
            _game("g3", "a", "bot1", end_aug + timedelta(minutes=6)),
            _game("g2", "a", "bot1", end_aug),
            _game("g4", "a", "bot2", datetime(2026, 12, 31, tzinfo=UTC)),
        ],
    )
    paths = build_panel(tmp_path, ["2026-08", "2026-09"])
    assert is_panel(paths) and paths.root.name == PANEL_NAME
    games = pl.read_parquet(paths.player_games).sort("start")
    assert games["game_id"].to_list() == ["g1", "g2", "g3", "g4"]
    assert games["rematch"].to_list() == [False, True, False, False]
    assert games["pair_game_index"].to_list() == [0, 1, 2, 0]
    # g1 comes back to bot1 within 7 days, g3 never returns to bot1 but plays bot2 later
    assert games["return_7d"].to_list()[0] is True
    g3 = games.row(2, named=True)
    assert (g3["return_28d"], g3["return_91d"]) == (False, False)
    assert (g3["any_return_91d"], g3["player_session_last"]) == (False, True)
    assert games["return_91d"].to_list()[3] is None
    assert "line" not in games.columns
    monthly = pl.read_parquet(paths.user_activity_monthly)
    assert monthly.sort("month")["n_human_games"].to_list() == [3, 3]
    assert pl.read_parquet(paths.baseline_player_games).height == 0


def test_uncensored_sessions_drop_mostly_censored_months() -> None:
    games = pl.DataFrame(
        {
            "month": ["2026-07"] * 2 + ["2026-08"] * 4,
            "session_last": [True, True, True, True, True, False],
            "return_28d": [True, False, True, None, None, None],
        }
    )
    out = uncensored_sessions(games, "return_28d")
    # August has one known return out of three session ends: no rate for August
    assert out["month"].to_list() == ["2026-07", "2026-07"]
