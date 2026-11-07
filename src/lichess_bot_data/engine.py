"""Evaluates game positions with a local Stockfish binary in a process pool."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine
import polars as pl

from lichess_bot_data.pgn import MATE_CP

NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)
"""Process flag that keeps engine consoles hidden on Windows (0 elsewhere)."""


@dataclass(frozen=True)
class EngineSettings:
    """Stockfish search settings.

    Attributes:
        binary: Path of the Stockfish executable.
        nodes: Node budget per position.
        hash_mb: Transposition table size per engine process.
    """

    binary: Path
    nodes: int = 20000
    hash_mb: int = 16


def _score_cp(info: chess.engine.InfoDict) -> float:
    score = info["score"].white()
    mate = score.mate()
    if mate is not None:
        return MATE_CP if mate > 0 else -MATE_CP
    cp = score.score()
    return float(cp) if cp is not None else 0.0


def evaluate_game(
    engine: chess.engine.SimpleEngine, sans: Sequence[str], nodes: int
) -> list[float]:
    """Returns White-perspective centipawn evals after each ply of a game.

    Illegal or unparsable moves truncate the result at that ply.

    Args:
        engine: Running UCI engine.
        sans: SAN moves from the initial position.
        nodes: Node budget per position.
    """
    board = chess.Board()
    evals: list[float] = []
    for san in sans:
        try:
            board.push_san(san)
        except ValueError:
            break
        if board.is_checkmate():
            evals.append(-MATE_CP if board.turn == chess.WHITE else MATE_CP)
            break
        if board.is_game_over():
            evals.append(0.0)
            break
        evals.append(_score_cp(engine.analyse(board, chess.engine.Limit(nodes=nodes))))
    return evals


def _evaluate_batch(
    batch: list[tuple[str, str]], settings: EngineSettings
) -> list[tuple[str, list[float]]]:
    # the engine is quit inside the task: its background thread would block worker exit
    engine = chess.engine.SimpleEngine.popen_uci(
        str(settings.binary), timeout=300, creationflags=NO_WINDOW
    )
    try:
        engine.configure({"Threads": 1, "Hash": settings.hash_mb})
        return [(gid, evaluate_game(engine, sans.split(), settings.nodes)) for gid, sans in batch]
    finally:
        engine.quit()


class StockfishEvaluator:
    """Evaluates many games in parallel, starting one Stockfish process per batch."""

    def __init__(self, settings: EngineSettings, n_workers: int = 20, batch_size: int = 200):
        """Configures the evaluator.

        Args:
            settings: Engine binary and search budget.
            n_workers: Number of parallel engine processes.
            batch_size: Games per worker task.
        """
        self._settings = settings
        self._n_workers = n_workers
        self._batch_size = batch_size

    def _batches(self, games: pl.DataFrame) -> Iterator[list[tuple[str, str]]]:
        pairs = list(zip(games["game_id"], games["sans"], strict=True))
        for start in range(0, len(pairs), self._batch_size):
            yield pairs[start : start + self._batch_size]

    def evaluate(self, games: pl.DataFrame) -> pl.DataFrame:
        """Returns a table of ``game_id`` and ``sf_evals`` (White cp after each ply).

        Args:
            games: Table with ``game_id`` and space-separated ``sans`` columns.
        """
        ids: list[str] = []
        evals: list[list[float]] = []
        with ProcessPoolExecutor(self._n_workers) as pool:
            futures = [
                pool.submit(_evaluate_batch, batch, self._settings)
                for batch in self._batches(games)
            ]
            for done, future in enumerate(futures, start=1):
                for gid, game_evals in future.result():
                    ids.append(gid)
                    evals.append(game_evals)
                if done % 20 == 0:
                    print(f"evaluated {done}/{len(futures)} batches", flush=True)
        return pl.DataFrame(
            {"game_id": ids, "sf_evals": evals},
            schema={"game_id": pl.Utf8, "sf_evals": pl.List(pl.Float32)},
        )
