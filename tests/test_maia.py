"""Tests for Maia rating matching, move conversion and (when lc0 is installed) live scoring."""

import pytest

from lichess_bot_data import config
from lichess_bot_data.maia import (
    _STAT_RE,
    MaiaPolicy,
    MaiaSettings,
    MoveScore,
    _interleave,
    maia_rating,
    score_side,
    to_uci,
)


def test_maia_rating_rounds_and_clips() -> None:
    assert maia_rating(1449) == 1400
    assert maia_rating(1451) == 1500
    assert maia_rating(800) == 1100
    assert maia_rating(2600) == 1900
    assert maia_rating(None) == 1500


def test_to_uci_stops_at_illegal_move() -> None:
    assert to_uci(["e4", "e5", "O-O", "Nf3"]) == ["e2e4", "e7e5"]
    assert to_uci(["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6", "O-O"])[-1] == "e1g1"


def test_stat_line_parsing() -> None:
    line = "info string b8c6  (36  ) N:       0 (+ 0) (P: 49.95%) (WL:  -.-----) (Q: -0.05)"
    match = _STAT_RE.match(line)
    assert match is not None
    assert match.group(1) == "b8c6"
    assert float(match.group(2)) == pytest.approx(49.95)


def test_interleave_restores_ply_order() -> None:
    w = [MoveScore(0.1, 0.5, False), MoveScore(0.2, 0.5, False)]
    b = [MoveScore(0.3, 0.5, True)]
    assert [s.prob if s else None for s in _interleave(w, b)] == [0.1, 0.3, 0.2]


@pytest.mark.skipif(not config.LC0_PATH.exists(), reason="lc0 not installed")
def test_live_policy_scores_common_reply() -> None:
    policy = MaiaPolicy(MaiaSettings(config.LC0_PATH, config.MAIA_WEIGHTS_DIR), 1500)
    try:
        probs = policy.probabilities(["e2e4"])
        assert sum(probs.values()) == pytest.approx(1.0, abs=0.02)
        scores = score_side(policy, to_uci(["e4", "e5", "Nf3", "Nc6"]), white=False)
    finally:
        policy.close()
    assert len(scores) == 2
    assert scores[0].prob > 0.1
    assert 0.0 < scores[0].entropy < 5.0
