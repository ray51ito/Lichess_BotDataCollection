"""Tests for the player-perspective game table builder."""

from datetime import timedelta

from lichess_bot_data.extract import process_block
from lichess_bot_data.features.games import (
    Perspective,
    _speed,
    build_player_table,
    speed_from_time_control,
)

PGN = """[Event "Rated Blitz game"]
[Site "https://lichess.org/g1"]
[White "maia5"]
[Black "alice"]
[Result "0-1"]
[UTCDate "2026.08.01"]
[UTCTime "10:00:00"]
[WhiteElo "1600"]
[BlackElo "1400"]
[WhiteTitle "BOT"]
[TimeControl "180+2"]
[Termination "Normal"]

1. e4 { [%eval 0.2] [%clk 0:03:00] } 1... f6 { [%eval 0.9] [%clk 0:03:00] } \
2. Qh5+ { [%eval -5.0] [%clk 0:02:55] } 2... g6 { [%eval -5.0] [%clk 0:02:50] } 0-1

"""


def test_human_vs_bot_row() -> None:
    games = process_block(PGN.encode(), baseline_rate_per_mille=0).bot_games
    table = build_player_table(games, Perspective.HUMAN_VS_BOT)
    row = table.row(0, named=True)
    assert row["player"] == "alice"
    assert row["opponent"] == "maia5"
    assert row["opponent_is_bot"]
    assert not row["player_is_white"]
    assert row["outcome"] == "win"
    assert row["end_type"] == "resign"
    assert row["loser"] == "opponent"
    assert row["elo_gap"] == -200
    assert row["duration_s"] == 7 + 12
    assert row["end"] - row["start"] == timedelta(seconds=19)
    assert row["opponent_time_n"] == 1
    assert row["has_evals"]
    assert row["opponent_blunders"] == 1
    assert row["opening"] == "e4 f6 Qh5+ g6"


def test_both_sides_perspective() -> None:
    games = process_block(PGN.encode(), baseline_rate_per_mille=0).bot_games
    table = build_player_table(games, Perspective.BOTH_SIDES)
    assert table.height == 2
    assert sorted(table["player_score"].to_list()) == [0.0, 1.0]


def test_speed_from_time_control_matches_lichess_categories() -> None:
    assert speed_from_time_control(60, 1) == "bullet"
    assert speed_from_time_control(180, 2) == "blitz"
    assert speed_from_time_control(600, 0) == "rapid"
    assert speed_from_time_control(1800, 20) == "classical"
    assert _speed("Rated Blitz game") == "blitz"
    assert _speed("Rated Chess960 game", 180, 0) == "blitz"


def test_time_forfeit_duration_includes_the_flag_fall() -> None:
    pgn = PGN.replace('[Termination "Normal"]', '[Termination "Time forfeit"]')
    games = process_block(pgn.encode(), baseline_rate_per_mille=0).bot_games
    row = build_player_table(games, Perspective.HUMAN_VS_BOT).row(0, named=True)
    # four plies: White is to move and burns its last clock reading (2:55)
    assert row["end_type"] == "timeout"
    assert row["duration_s"] == 7 + 12 + 175
