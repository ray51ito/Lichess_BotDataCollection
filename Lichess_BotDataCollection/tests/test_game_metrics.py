"""Tests for per-game metric functions."""

import pytest

from lichess_bot_data.features.game_metrics import (
    EndType,
    elo_expected_score,
    end_type,
    eval_metrics,
    game_duration_s,
    move_times,
    player_score,
    win_probability,
)


def test_move_times_with_increment() -> None:
    # clocks from a 300+3 game: first moves untimed, then 2s and 1s spent
    white, black = move_times([300, 300, 301, 302, 290, 280], base_s=300, inc_s=3)
    assert white == [None, 2.0, 14.0]
    assert black == [None, 1.0, 25.0]
    assert game_duration_s(white, black) == 42.0


def test_win_probability_symmetry() -> None:
    assert win_probability(0) == pytest.approx(0.5)
    assert win_probability(300) == pytest.approx(1 - win_probability(-300))


def test_eval_metrics_blunder_and_lead_change() -> None:
    # bot (black) blunders on ply 2, then the human blunders back on ply 3
    metrics = eval_metrics([20.0, 500.0, -600.0, -600.0], opponent_is_white=False)
    assert metrics is not None
    assert metrics.opponent_blunders == 1
    assert metrics.player_blunders == 1
    assert metrics.lead_changes == 1
    assert metrics.player_max_wp > 0.8
    assert metrics.opponent_conversion_plies is None
    assert metrics.final_player_wp < 0.2
    won = eval_metrics([20.0, 800.0, 900.0, 950.0], opponent_is_white=False)
    assert won is not None
    assert won.player_conversion_plies == 2
    assert eval_metrics([None, None], opponent_is_white=True) is None


def test_end_type_and_score() -> None:
    assert end_type("Normal", "1-0", "Qh7#") == EndType.CHECKMATE
    assert end_type("Normal", "0-1", "Kf1") == EndType.RESIGN
    assert end_type("Time forfeit", "1-0", "e4") == EndType.TIMEOUT
    assert end_type("Time forfeit", "1/2-1/2", "e4") == EndType.DRAW
    assert player_score("1-0", opponent_is_white=True) == 0.0
    assert player_score("*", opponent_is_white=True) is None
    assert elo_expected_score(1500, 1500) == pytest.approx(0.5)
