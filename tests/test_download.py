"""Tests for the download plan's chunk bookkeeping and sparse presizing."""

import sys
from pathlib import Path

import pytest

from lichess_bot_data.download import DownloadPlan, RangeDownloader, make_sparse


def test_rechunked_keeps_finished_bytes() -> None:
    plan = DownloadPlan("u", total_size=100, chunk_size=40, done={0, 2})
    small = plan.rechunked(20)
    # chunk 0 = bytes 0-39 -> small 0,1; chunk 2 = bytes 80-99 -> small 4 only
    assert small.chunk_size == 20
    assert small.done == {0, 1, 4}
    assert small.pending() == [2, 3]


def test_rechunked_ignores_non_divisors_and_larger_sizes() -> None:
    plan = DownloadPlan("u", total_size=100, chunk_size=40, done={1})
    assert plan.rechunked(30) is plan
    assert plan.rechunked(80) is plan


def test_throttle_sleeps_when_ahead_of_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("lichess_bot_data.download.time.sleep", sleeps.append)
    downloader = RangeDownloader("u", tmp_path / "f", max_mb_s=1.0)
    downloader._throttle(3_000_000)
    # 3 MB at 1 MB/s should take ~3 s; almost no time has passed
    assert sleeps and sleeps[0] == pytest.approx(3.0, abs=0.5)
    uncapped = RangeDownloader("u", tmp_path / "g")
    sleeps.clear()
    uncapped._throttle(3_000_000)
    assert sleeps == []


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS sparse files")
def test_make_sparse_marks_file(tmp_path: Path) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"")
    assert make_sparse(target)
