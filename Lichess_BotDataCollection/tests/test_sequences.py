"""Tests for sequence-based outcome annotation."""

from datetime import UTC, datetime, timedelta

import polars as pl

from lichess_bot_data.features.sequences import annotate_sequences

T0 = datetime(2026, 8, 1, tzinfo=UTC)


def _game(player: str, opponent: str, start_min: float, elo: int = 1500) -> dict[str, object]:
    start = T0 + timedelta(minutes=start_min)
    return {
        "player": player,
        "opponent": opponent,
        "start": start,
        "end": start + timedelta(minutes=5),
        "opponent_elo": elo,
    }


def test_rematch_switch_and_return() -> None:
    table = pl.DataFrame(
        [
            _game("a", "bot1", 0),  # rematch: next starts 1 min after end
            _game("a", "bot1", 6),  # switch to stronger bot2 within session gap
            _game("a", "bot2", 20, elo=1700),  # quits
            _game("a", "bot1", 60 * 24),  # returns to bot1 a day later
            _game("a", "bot1", 60 * 24 * 30),  # far later: keeps the data end late
        ]
    )
    out = annotate_sequences(table).sort("start")
    assert out["rematch"].to_list() == [True, False, False, False, False]
    assert out["switch"].to_list() == [False, True, False, False, False]
    assert out["switch_elo_delta"].to_list()[1] == 200
    assert out["session_length"].to_list() == [2, 2, 1, 1, 1]
    assert out["session_last"].to_list() == [False, True, True, True, True]
    assert out["return_7d"].to_list() == [False, True, False, False, None]
    assert out["pair_game_index"].to_list() == [0, 1, 0, 2, 3]
