"""Extracts human-vs-BOT games (plus bot-vs-bot, a human baseline and watched users) to Parquet."""

from __future__ import annotations

import re
import shutil
import zlib
from collections import Counter, deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
import zstandard

from lichess_bot_data.io import write_parquet_atomic
from lichess_bot_data.pgn import parse_headers, parse_movetext, split_game

BOT_TITLE: str = "BOT"
"""Value of the ``WhiteTitle``/``BlackTitle`` tag for bot accounts."""

_GAME_SPLIT_RE = re.compile(r"\n\n(?=\[Event )")
_GAME_START = b"\n\n[Event "

GAME_SCHEMA: dict[str, Any] = {
    "game_id": pl.Utf8,
    "event": pl.Utf8,
    "utc_date": pl.Utf8,
    "utc_time": pl.Utf8,
    "white": pl.Utf8,
    "black": pl.Utf8,
    "white_elo": pl.Int32,
    "black_elo": pl.Int32,
    "white_rating_diff": pl.Int32,
    "black_rating_diff": pl.Int32,
    "white_title": pl.Utf8,
    "black_title": pl.Utf8,
    "result": pl.Utf8,
    "termination": pl.Utf8,
    "eco": pl.Utf8,
    "opening": pl.Utf8,
    "time_control": pl.Utf8,
    "sans": pl.Utf8,
    "clocks": pl.List(pl.Int32),
    "evals": pl.List(pl.Float32),
}
"""Column schema of the extracted game tables."""


@dataclass
class BlockResult:
    """Output of parsing one block of games.

    Attributes:
        bot_games: Human-vs-BOT games with full movetext.
        baseline_games: Sampled human-vs-human games (no SAN moves).
        bot_vs_bot_games: Bot-vs-bot games (headers and clocks only; used for bot availability).
        watched_games: Human-vs-human games involving a watched user (headers only).
        human_headers: Headers of every human-vs-human game (only in ``watch_self`` mode).
        human_game_counts: Number of human-vs-human games per username.
        n_games: Total games in the block.
        n_bot_vs_bot: Games where both sides are bots.
    """

    bot_games: pl.DataFrame
    baseline_games: pl.DataFrame
    bot_vs_bot_games: pl.DataFrame
    watched_games: pl.DataFrame
    human_headers: pl.DataFrame | None = None
    human_game_counts: dict[str, int] = field(default_factory=dict)
    n_games: int = 0
    n_bot_vs_bot: int = 0


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _header_record(headers: dict[str, str]) -> dict[str, Any]:
    return {
        "game_id": headers.get("Site", "").rsplit("/", 1)[-1],
        "event": headers.get("Event"),
        "utc_date": headers.get("UTCDate"),
        "utc_time": headers.get("UTCTime"),
        "white": headers.get("White"),
        "black": headers.get("Black"),
        "white_elo": _to_int(headers.get("WhiteElo")),
        "black_elo": _to_int(headers.get("BlackElo")),
        "white_rating_diff": _to_int(headers.get("WhiteRatingDiff")),
        "black_rating_diff": _to_int(headers.get("BlackRatingDiff")),
        "white_title": headers.get("WhiteTitle"),
        "black_title": headers.get("BlackTitle"),
        "result": headers.get("Result"),
        "termination": headers.get("Termination"),
        "eco": headers.get("ECO"),
        "opening": headers.get("Opening"),
        "time_control": headers.get("TimeControl"),
        "sans": None,
        "clocks": None,
        "evals": None,
    }


def _record(
    headers: dict[str, str], movetext: str, keep_sans: bool, keep_clocks: bool = True
) -> dict[str, Any]:
    parsed = parse_movetext(movetext)
    return {
        "game_id": headers.get("Site", "").rsplit("/", 1)[-1],
        "event": headers.get("Event"),
        "utc_date": headers.get("UTCDate"),
        "utc_time": headers.get("UTCTime"),
        "white": headers.get("White"),
        "black": headers.get("Black"),
        "white_elo": _to_int(headers.get("WhiteElo")),
        "black_elo": _to_int(headers.get("BlackElo")),
        "white_rating_diff": _to_int(headers.get("WhiteRatingDiff")),
        "black_rating_diff": _to_int(headers.get("BlackRatingDiff")),
        "white_title": headers.get("WhiteTitle"),
        "black_title": headers.get("BlackTitle"),
        "result": headers.get("Result"),
        "termination": headers.get("Termination"),
        "eco": headers.get("ECO"),
        "opening": headers.get("Opening"),
        "time_control": headers.get("TimeControl"),
        "sans": " ".join(parsed.sans) if keep_sans else None,
        "clocks": parsed.clocks if keep_clocks else None,
        "evals": parsed.evals if parsed.has_evals and keep_clocks else None,
    }


def is_baseline_pair(white: str, black: str, rate_per_mille: int) -> bool:
    """Deterministically samples player pairs (order-independent) for the human baseline.

    Args:
        white: White username.
        black: Black username.
        rate_per_mille: Sampling rate in 1/1000 units.
    """
    key = "\0".join(sorted((white.lower(), black.lower()))).encode()
    return zlib.crc32(key) % 1000 < rate_per_mille


def process_block(
    block: bytes,
    baseline_rate_per_mille: int,
    watch_users: frozenset[str] = frozenset(),
    all_human_headers: bool = False,
) -> BlockResult:
    """Parses one game-aligned block of decompressed PGN text.

    Args:
        block: UTF-8 PGN text that starts at a game boundary and ends after a full game.
        baseline_rate_per_mille: Sampling rate of human-vs-human pairs for the baseline.
        watch_users: Usernames whose human-vs-human games are all kept (headers only).
        all_human_headers: Also return the headers of every human-vs-human game.
    """
    bot_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    bvb_rows: list[dict[str, Any]] = []
    watched_rows: list[dict[str, Any]] = []
    header_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    n_games = 0
    n_bot_vs_bot = 0

    for game in _GAME_SPLIT_RE.split(block.decode("utf-8", errors="replace")):
        head, moves = split_game(game.strip("\n"))
        if not head:
            continue
        n_games += 1
        headers = parse_headers(head)
        white_bot = headers.get("WhiteTitle") == BOT_TITLE
        black_bot = headers.get("BlackTitle") == BOT_TITLE

        # bot games: keep human-vs-bot fully, bot-vs-bot without moves
        if white_bot and black_bot:
            n_bot_vs_bot += 1
            bvb_rows.append(_record(headers, moves, keep_sans=False))
        elif white_bot or black_bot:
            bot_rows.append(_record(headers, moves, keep_sans=True))
        else:
            white, black = headers.get("White", ""), headers.get("Black", "")
            counts[white] += 1
            counts[black] += 1
            if is_baseline_pair(white, black, baseline_rate_per_mille):
                baseline_rows.append(_record(headers, moves, keep_sans=False))
            if all_human_headers:
                header_rows.append(_header_record(headers))
            elif white in watch_users or black in watch_users:
                watched_rows.append(_header_record(headers))

    return BlockResult(
        pl.DataFrame(bot_rows, schema=GAME_SCHEMA),
        pl.DataFrame(baseline_rows, schema=GAME_SCHEMA),
        pl.DataFrame(bvb_rows, schema=GAME_SCHEMA),
        pl.DataFrame(watched_rows, schema=GAME_SCHEMA),
        pl.DataFrame(header_rows, schema=GAME_SCHEMA) if all_human_headers else None,
        dict(counts),
        n_games,
        n_bot_vs_bot,
    )


def iter_blocks(dump: Path, block_bytes: int = 64 * 1024 * 1024) -> Iterator[bytes]:
    """Yields game-aligned blocks of decompressed text from a ``.pgn.zst`` dump.

    Args:
        dump: Path of the zstd-compressed PGN dump.
        block_bytes: Approximate decompressed size of each block.
    """
    dctx = zstandard.ZstdDecompressor(max_window_size=2**31)
    with dump.open("rb") as fh, dctx.stream_reader(fh, read_size=1 << 22) as reader:
        carry = b""
        while True:
            chunk = reader.read(block_bytes)
            if not chunk:
                break
            buffer = carry + chunk
            cut = buffer.rfind(_GAME_START)
            if cut <= 0:
                carry = buffer
                continue
            yield buffer[:cut]
            carry = buffer[cut + 2 :]
        if carry.strip():
            yield carry


def ordered_parallel_map(
    blocks: Iterable[bytes],
    rate_per_mille: int,
    n_workers: int,
    watch_users: frozenset[str] = frozenset(),
    all_human_headers: bool = False,
) -> Iterator[BlockResult]:
    """Maps ``process_block`` over blocks in a process pool, preserving order.

    At most ``2 * n_workers`` blocks are in flight, so memory stays bounded.

    Args:
        blocks: Game-aligned text blocks.
        rate_per_mille: Baseline sampling rate passed to ``process_block``.
        n_workers: Number of worker processes.
        watch_users: Usernames whose human-vs-human games are kept.
        all_human_headers: Passed to ``process_block``.
    """
    in_flight: deque[Future[BlockResult]] = deque()
    with ProcessPoolExecutor(n_workers) as pool:
        for block in blocks:
            in_flight.append(
                pool.submit(process_block, block, rate_per_mille, watch_users, all_human_headers)
            )
            if len(in_flight) >= 2 * n_workers:
                yield in_flight.popleft().result()
        while in_flight:
            yield in_flight.popleft().result()


@dataclass
class ExtractionSummary:
    """Counts reported after an extraction run.

    Attributes:
        n_games: Total games read.
        n_human_vs_bot: Human-vs-BOT games kept.
        n_bot_vs_bot: Bot-vs-bot games (kept without moves).
        n_baseline: Human-vs-human baseline games kept.
        n_watched: Human-vs-human games of watched users kept.
    """

    n_games: int = 0
    n_human_vs_bot: int = 0
    n_bot_vs_bot: int = 0
    n_baseline: int = 0
    n_watched: int = 0


HEADER_PART_BLOCKS: int = 25
"""Blocks of human-game headers buffered before a temporary part file is written."""


def bot_players_of(bot_games: pl.DataFrame) -> set[str]:
    """Returns the human usernames in a table of human-vs-BOT games."""
    humans = bot_games.select(
        pl.when(pl.col("white_title") == BOT_TITLE).then(pl.col("black")).otherwise(pl.col("white"))
    ).to_series()
    return set(humans.drop_nulls().to_list())


class DumpExtractor:
    """Runs the block parser over a whole dump in a process pool and writes Parquet files."""

    def __init__(
        self,
        dump: Path,
        out_dir: Path,
        n_workers: int = 20,
        baseline_rate_per_mille: int = 5,
        *,
        watch_users: frozenset[str] = frozenset(),
        watch_self: bool = False,
    ) -> None:
        """Configures an extraction run.

        Args:
            dump: Path of the ``.pgn.zst`` monthly dump.
            out_dir: Directory receiving ``bot_games``, ``baseline_games``,
                ``bot_vs_bot_games``, ``watched_human_games`` and ``user_activity`` Parquet files.
            n_workers: Number of parser processes.
            baseline_rate_per_mille: Human-vs-human pair sampling rate (1/1000).
            watch_users: Usernames whose human-vs-human games are all kept.
            watch_self: Also keep the human games of this month's own bot players. Every
                human game's headers are spooled to a temporary folder in ``out_dir`` and
                filtered once the bot players are known (one pass over the dump).
        """
        self._dump = dump
        self._out_dir = out_dir
        self._n_workers = n_workers
        self._rate = baseline_rate_per_mille
        self._watch = watch_users
        self._watch_self = watch_self

    @property
    def _spool(self) -> Path:
        return self._out_dir / "_human_headers"

    def run(self) -> ExtractionSummary:
        """Parses the dump and writes the output tables."""
        summary = ExtractionSummary()
        bot_frames: list[pl.DataFrame] = []
        baseline_frames: list[pl.DataFrame] = []
        bvb_frames: list[pl.DataFrame] = []
        watched_frames: list[pl.DataFrame] = []
        header_buffer: list[pl.DataFrame] = []
        counts: Counter[str] = Counter()

        self._out_dir.mkdir(parents=True, exist_ok=True)
        # leftovers of an interrupted run would duplicate games
        shutil.rmtree(self._spool, ignore_errors=True)
        if self._watch_self:
            self._spool.mkdir()

        results = ordered_parallel_map(
            iter_blocks(self._dump), self._rate, self._n_workers, self._watch, self._watch_self
        )
        for i, result in enumerate(results):
            bot_frames.append(result.bot_games)
            baseline_frames.append(result.baseline_games)
            bvb_frames.append(result.bot_vs_bot_games)
            watched_frames.append(result.watched_games)
            if result.human_headers is not None:
                header_buffer.append(result.human_headers)
                if len(header_buffer) >= HEADER_PART_BLOCKS:
                    pl.concat(header_buffer).write_parquet(self._spool / f"part_{i:06d}.parquet")
                    header_buffer = []
            counts.update(result.human_game_counts)
            summary.n_games += result.n_games
            summary.n_bot_vs_bot += result.n_bot_vs_bot
            if i % 100 == 0:
                print(f"block {i}: {summary.n_games:,} games", flush=True)
        if header_buffer:
            pl.concat(header_buffer).write_parquet(self._spool / "part_last.parquet")

        bot = pl.concat(bot_frames)
        baseline = pl.concat(baseline_frames)
        watched = pl.concat(watched_frames)
        if self._watch_self:
            users = list(bot_players_of(bot) | self._watch)
            watched = (
                pl.scan_parquet(self._spool / "*.parquet")
                .filter(pl.col("white").is_in(users) | pl.col("black").is_in(users))
                .collect()
            )
        write_parquet_atomic(bot, self._out_dir / "bot_games.parquet")
        write_parquet_atomic(baseline, self._out_dir / "baseline_games.parquet")
        write_parquet_atomic(pl.concat(bvb_frames), self._out_dir / "bot_vs_bot_games.parquet")
        write_parquet_atomic(watched, self._out_dir / "watched_human_games.parquet")
        write_parquet_atomic(
            pl.DataFrame(
                {"user": list(counts.keys()), "n_human_games": list(counts.values())},
                schema={"user": pl.Utf8, "n_human_games": pl.Int32},
            ),
            self._out_dir / "user_activity.parquet",
        )
        shutil.rmtree(self._spool, ignore_errors=True)

        summary.n_human_vs_bot = bot.height
        summary.n_baseline = baseline.height
        summary.n_watched = watched.height
        return summary
