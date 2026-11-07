"""Tests for block splitting and dump extraction on a synthetic zstd dump."""

from pathlib import Path

import polars as pl
import zstandard

from lichess_bot_data.extract import DumpExtractor, is_baseline_pair, iter_blocks, process_block


def _game(gid: str, white: str, black: str, wt: str = "", bt: str = "") -> str:
    titles = (f'[WhiteTitle "{wt}"]\n' if wt else "") + (f'[BlackTitle "{bt}"]\n' if bt else "")
    return (
        f'[Event "Rated Blitz game"]\n[Site "https://lichess.org/{gid}"]\n'
        f'[White "{white}"]\n[Black "{black}"]\n[Result "1-0"]\n'
        f'[UTCDate "2026.08.01"]\n[UTCTime "00:00:01"]\n[WhiteElo "1500"]\n[BlackElo "?"]\n'
        f'{titles}[TimeControl "180+2"]\n[Termination "Normal"]\n\n'
        "1. e4 { [%clk 0:03:00] } 1... e5 { [%clk 0:03:00] } 1-0\n\n"
    )


DUMP_TEXT = (
    _game("a1", "alice", "botA", bt="BOT")
    + _game("a2", "botB", "botA", wt="BOT", bt="BOT")
    + _game("a3", "alice", "bob")
    + _game("a4", "botB", "carol", wt="BOT")
)


def test_process_block_classifies_games() -> None:
    result = process_block(DUMP_TEXT.encode(), baseline_rate_per_mille=1000)
    assert result.n_games == 4
    assert result.n_bot_vs_bot == 1
    assert result.bot_games["game_id"].to_list() == ["a1", "a4"]
    assert result.bot_games["black_elo"].to_list() == [None, None]
    assert result.bot_games["sans"].to_list()[0] == "e4 e5"
    assert result.baseline_games["sans"].to_list() == [None]
    assert result.human_game_counts == {"alice": 1, "bob": 1}
    assert result.bot_vs_bot_games["game_id"].to_list() == ["a2"]
    assert result.bot_vs_bot_games["sans"].to_list() == [None]
    assert result.watched_games.height == 0


def test_process_block_keeps_watched_users() -> None:
    result = process_block(DUMP_TEXT.encode(), 0, watch_users=frozenset({"bob"}))
    assert result.watched_games["game_id"].to_list() == ["a3"]
    assert result.watched_games["clocks"].to_list() == [None]
    assert result.baseline_games.height == 0


def test_iter_blocks_and_extractor(tmp_path: Path) -> None:
    dump = tmp_path / "dump.pgn.zst"
    dump.write_bytes(zstandard.ZstdCompressor().compress((DUMP_TEXT * 50).encode()))

    blocks = list(iter_blocks(dump, block_bytes=700))
    assert sum(b.count(b"[Event ") for b in blocks) == 200
    assert all(b.startswith(b"[Event ") for b in blocks)

    summary = DumpExtractor(
        dump, tmp_path / "out", n_workers=2, watch_users=frozenset({"alice"})
    ).run()
    assert summary.n_games == 200
    assert summary.n_human_vs_bot == 100
    assert summary.n_watched == 50
    assert pl.read_parquet(tmp_path / "out" / "bot_vs_bot_games.parquet").height == 50
    activity = pl.read_parquet(tmp_path / "out" / "user_activity.parquet")
    assert dict(zip(activity["user"], activity["n_human_games"], strict=True))["alice"] == 50


def test_extractor_watch_self_keeps_own_bot_players(tmp_path: Path) -> None:
    dump = tmp_path / "dump.pgn.zst"
    dump.write_bytes(zstandard.ZstdCompressor().compress((DUMP_TEXT * 50).encode()))
    out = tmp_path / "out"
    # a stale spool from an interrupted run must not leak into the result
    (out / "_human_headers").mkdir(parents=True)
    pl.DataFrame({"white": ["alice"], "black": ["x"]}).write_parquet(
        out / "_human_headers" / "part_stale.parquet"
    )

    summary = DumpExtractor(dump, out, n_workers=2, watch_self=True).run()
    watched = pl.read_parquet(out / "watched_human_games.parquet")
    # alice played a bot (a1), so her human game a3 is kept; carol has no human games
    assert summary.n_watched == 50
    assert set(watched["game_id"]) == {"a3"}
    assert watched["clocks"].null_count() == 50
    assert not (out / "_human_headers").exists()
    assert not list(out.glob("*.tmp"))


def test_process_block_returns_all_human_headers() -> None:
    result = process_block(DUMP_TEXT.encode(), 0, all_human_headers=True)
    assert result.human_headers is not None
    assert result.human_headers["game_id"].to_list() == ["a3"]
    assert result.watched_games.height == 0


def test_baseline_pair_is_order_independent() -> None:
    assert is_baseline_pair("A", "b", 500) == is_baseline_pair("b", "a", 500)
