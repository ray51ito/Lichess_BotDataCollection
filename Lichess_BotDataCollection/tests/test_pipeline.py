"""Tests for merging months into one folder."""

from pathlib import Path

import polars as pl
import pytest

from lichess_bot_data import config
from lichess_bot_data.pipeline import MonthPaths, merge_months


def test_merge_months_stacks_tables_and_keeps_monthly_activity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "INTERIM_DIR", tmp_path)
    for month, gids in (("2026-07", ["a", "b"]), ("2026-08", ["b", "c"])):
        paths = MonthPaths.for_month(month)
        paths.root.mkdir(parents=True)
        pl.DataFrame({"game_id": gids}).write_parquet(paths.bot_games)
        pl.DataFrame({"user": ["u"], "n_human_games": [3]}).write_parquet(paths.user_activity)
    target = MonthPaths.for_month("panel")
    merge_months(["2026-07", "2026-08"], target)

    assert sorted(pl.read_parquet(target.bot_games)["game_id"].to_list()) == ["a", "b", "c"]
    assert pl.read_parquet(target.user_activity)["n_human_games"].to_list() == [6]
    monthly = pl.read_parquet(target.user_activity_monthly)
    assert monthly["month"].to_list() == ["2026-07", "2026-08"]
    assert not target.sf_evals.exists()
