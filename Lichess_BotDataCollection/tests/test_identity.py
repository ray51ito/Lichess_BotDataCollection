"""Tests for canonical account names."""

import polars as pl

from lichess_bot_data.features.identity import (
    activity_by_id,
    align_names,
    canonical_spellings,
    canonicalise,
)


def test_canonical_spelling_is_the_most_frequent() -> None:
    names = pl.Series(["PaulB", "PaulB", "paulb", "Ann", "ann"])
    spellings = dict(canonical_spellings(names).rows())
    assert spellings == {"paulb": "PaulB", "ann": "Ann"}


def test_canonicalise_merges_spellings_in_every_column() -> None:
    table = pl.DataFrame(
        {"player": ["PaulB", "paulb", "PaulB"], "opponent": ["maia1", "Maia1", "maia1"]}
    )
    out = canonicalise(table, ["player", "opponent"])
    assert out["player"].to_list() == ["PaulB"] * 3
    assert out["opponent"].to_list() == ["maia1"] * 3


def test_align_names_and_activity_by_id() -> None:
    watched = pl.DataFrame({"white": ["paulb", "Zed"], "black": ["x", "PAULB"]})
    out = align_names(watched, ["white", "black"], pl.Series(["PaulB"]))
    assert out.rows() == [("PaulB", "x"), ("Zed", "PaulB")]
    activity = pl.DataFrame({"user": ["PaulB", "paulb"], "n_human_games": [3, 4]})
    assert activity_by_id(activity).rows() == [("paulb", 7)]
