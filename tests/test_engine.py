"""Tests for the Stockfish evaluator (skipped when no binary is installed)."""

import polars as pl
import pytest

from lichess_bot_data import config
from lichess_bot_data.engine import EngineSettings, StockfishEvaluator
from lichess_bot_data.pgn import MATE_CP

BINARY = config.STOCKFISH_PATH


@pytest.mark.skipif(not BINARY.exists(), reason="Stockfish binary not installed")
def test_evaluates_fools_mate() -> None:
    games = pl.DataFrame({"game_id": ["g"], "sans": ["f3 e5 g4 Qh4#"]})
    out = StockfishEvaluator(EngineSettings(BINARY, nodes=2000), n_workers=1).evaluate(games)
    evals = out["sf_evals"].to_list()[0]
    assert len(evals) == 4
    assert evals[-1] == -MATE_CP
    assert evals[2] < -1000
