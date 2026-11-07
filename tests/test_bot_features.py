"""Tests for bot-level aggregation helpers."""

import polars as pl
import pytest

from lichess_bot_data.features.bot_features import bot_own_moves, simpson_diversity


def test_bot_own_moves() -> None:
    assert bot_own_moves("e4 e5 Nf3 Nc6", bot_is_white=True) == "e4 Nf3"
    assert bot_own_moves("e4 e5 Nf3 Nc6", bot_is_white=False) == "e5 Nc6"
    assert bot_own_moves("e4", bot_is_white=False) is None


def test_simpson_diversity() -> None:
    assert simpson_diversity(pl.Series(["e4"] * 10)) == 0.0
    assert simpson_diversity(pl.Series(["e4", "d4"] * 5)) == pytest.approx(0.5)
    assert simpson_diversity(pl.Series(["e4"] * 3)) is None
