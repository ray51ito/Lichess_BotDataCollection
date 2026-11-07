"""Scores how human-like each played move is with rating-matched Maia networks run by lc0."""

from __future__ import annotations

import math
import re
import subprocess
from collections import defaultdict
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import chess
import polars as pl

from lichess_bot_data.engine import NO_WINDOW

MAIA_RATINGS: tuple[int, ...] = (1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900)
"""Ratings of the published Maia-1 networks."""

MIN_PROB: float = 5e-5
"""Floor for moves lc0 prints as 0.00% (its output has 0.01% resolution)."""

_STAT_RE = re.compile(r"^info string (\S+)\s+\(\s*\d+\s*\).*?\(P:\s*([\d.]+)%\)")


def maia_rating(elo: int | None) -> int:
    """Returns the Maia network rating closest to ``elo`` (1500 when unknown)."""
    if elo is None:
        return 1500
    return min(max(round(elo / 100) * 100, MAIA_RATINGS[0]), MAIA_RATINGS[-1])


@dataclass(frozen=True)
class MaiaSettings:
    """Locations of the lc0 binary and the Maia weight files.

    Attributes:
        lc0: Path of the lc0 executable (CPU ``blas`` backend).
        weights_dir: Directory holding ``maia-<rating>.pb.gz`` files.
    """

    lc0: Path
    weights_dir: Path

    def weights(self, rating: int) -> Path:
        """Returns the weight file of one Maia network."""
        return self.weights_dir / f"maia-{rating}.pb.gz"


class MaiaPolicy:
    """A running lc0 process that returns Maia's raw move probabilities for a position."""

    def __init__(self, settings: MaiaSettings, rating: int) -> None:
        """Starts lc0 with one Maia network and a policy temperature of 1 (raw policy)."""
        args = [
            str(settings.lc0),
            f"--weights={settings.weights(rating)}",
            "--backend=blas",
            "--threads=1",
            "--policy-softmax-temp=1.0",
            "--verbose-move-stats",
        ]
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            creationflags=NO_WINDOW,
        )
        self._send("uci")
        self._read_until("uciok")
        self._send("isready")
        self._read_until("readyok")

    def _send(self, line: str) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()

    def _read_until(self, prefix: str) -> list[str]:
        assert self._proc.stdout is not None
        lines: list[str] = []
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("lc0 exited unexpectedly")
            lines.append(line)
            if line.startswith(prefix):
                return lines

    def probabilities(self, uci_moves: Sequence[str]) -> dict[str, float]:
        """Returns Maia's probability of each legal move after ``uci_moves`` from the start.

        Args:
            uci_moves: Moves played so far, in UCI notation (history matters to Maia).
        """
        self._send("position startpos" + (" moves " + " ".join(uci_moves) if uci_moves else ""))
        self._send("go nodes 1")
        probs: dict[str, float] = {}
        for line in self._read_until("bestmove"):
            match = _STAT_RE.match(line)
            if match and match.group(1) != "node":
                probs[match.group(1)] = float(match.group(2)) / 100
        return probs

    def close(self) -> None:
        """Stops the lc0 process."""
        try:
            self._send("quit")
            self._proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()


@dataclass(frozen=True)
class MoveScore:
    """Maia's view of one played move.

    Attributes:
        prob: Probability Maia gave the played move.
        top_prob: Probability of Maia's most likely move.
        is_top: Whether the played move was Maia's most likely move.
        entropy: Shannon entropy (nats) of Maia's move distribution (position ambiguity).
    """

    prob: float
    top_prob: float
    is_top: bool
    entropy: float = 0.0


def to_uci(sans: Sequence[str]) -> list[str]:
    """Converts SAN moves to UCI, stopping at the first illegal or unparsable move."""
    board = chess.Board()
    out: list[str] = []
    for san in sans:
        try:
            move = board.push_san(san)
        except ValueError:
            break
        out.append(move.uci())
    return out


def score_side(policy: MaiaPolicy, uci_moves: Sequence[str], white: bool) -> list[MoveScore]:
    """Scores every move of one side of a game, in that side's move order.

    Args:
        policy: Running Maia network.
        uci_moves: All moves of the game in UCI.
        white: Which side's moves are scored.
    """
    scores: list[MoveScore] = []
    for ply in range(0 if white else 1, len(uci_moves), 2):
        probs = policy.probabilities(uci_moves[:ply])
        if not probs:
            break
        played = probs.get(uci_moves[ply], 0.0)
        top_move = max(probs, key=lambda m: probs[m])
        entropy = -sum(p * math.log(p) for p in probs.values() if p > 0)
        scores.append(
            MoveScore(max(played, MIN_PROB), probs[top_move], uci_moves[ply] == top_move, entropy)
        )
    return scores


@dataclass(frozen=True)
class SideJob:
    """One side of one game scored with one Maia network.

    Attributes:
        game_id: Lichess game id.
        white: Whether White's moves are scored.
        sans: Space-separated SAN moves of the whole game.
    """

    game_id: str
    white: bool
    sans: str


def _score_jobs(
    rating: int, jobs: list[SideJob], settings: MaiaSettings
) -> list[tuple[str, bool, list[MoveScore]]]:
    policy = MaiaPolicy(settings, rating)
    try:
        out: list[tuple[str, bool, list[MoveScore]]] = []
        for job in jobs:
            uci = to_uci(job.sans.split())
            out.append((job.game_id, job.white, score_side(policy, uci, job.white)))
        return out
    finally:
        policy.close()


def _interleave(white: list[MoveScore], black: list[MoveScore]) -> list[MoveScore | None]:
    plies: list[MoveScore | None] = []
    for i in range(max(len(white), len(black))):
        plies.append(white[i] if i < len(white) else None)
        if i < len(black):
            plies.append(black[i])
    return plies


class MaiaScorer:
    """Scores both sides of many games in parallel, each side with its rating-matched network."""

    def __init__(self, settings: MaiaSettings, n_workers: int = 20, batch_size: int = 100):
        """Configures the scorer.

        Args:
            settings: lc0 and weight locations.
            n_workers: Number of parallel lc0 processes.
            batch_size: Game sides per worker task (all for the same network).
        """
        self._settings = settings
        self._n_workers = n_workers
        self._batch_size = batch_size

    def _tasks(self, games: pl.DataFrame) -> Iterator[tuple[int, list[SideJob]]]:
        by_rating: dict[int, list[SideJob]] = defaultdict(list)
        for row in games.iter_rows(named=True):
            for white in (True, False):
                elo = row["white_elo"] if white else row["black_elo"]
                by_rating[maia_rating(elo)].append(SideJob(row["game_id"], white, row["sans"]))
        for rating, jobs in by_rating.items():
            for start in range(0, len(jobs), self._batch_size):
                yield rating, jobs[start : start + self._batch_size]

    def score(self, games: pl.DataFrame) -> pl.DataFrame:
        """Returns per-ply Maia scores of the played moves.

        Columns: ``game_id``, ``maia_prob``, ``maia_top_prob`` (lists over plies, null
        where a side could not be scored), ``maia_is_top`` and ``maia_entropy``.

        Args:
            games: Table with ``game_id``, ``sans``, ``white_elo`` and ``black_elo``.
        """
        sides: dict[str, dict[bool, list[MoveScore]]] = defaultdict(dict)
        with ProcessPoolExecutor(self._n_workers) as pool:
            futures = [
                pool.submit(_score_jobs, rating, jobs, self._settings)
                for rating, jobs in self._tasks(games)
            ]
            for done, future in enumerate(futures, start=1):
                for gid, white, scores in future.result():
                    sides[gid][white] = scores
                if done % 50 == 0:
                    print(f"maia: {done}/{len(futures)} tasks", flush=True)
        rows = []
        for gid, by_side in sides.items():
            plies = _interleave(by_side.get(True, []), by_side.get(False, []))
            rows.append(
                {
                    "game_id": gid,
                    "maia_prob": [s.prob if s else None for s in plies],
                    "maia_top_prob": [s.top_prob if s else None for s in plies],
                    "maia_is_top": [s.is_top if s else None for s in plies],
                    "maia_entropy": [s.entropy if s else None for s in plies],
                }
            )
        return pl.DataFrame(
            rows,
            schema={
                "game_id": pl.Utf8,
                "maia_prob": pl.List(pl.Float32),
                "maia_top_prob": pl.List(pl.Float32),
                "maia_is_top": pl.List(pl.Boolean),
                "maia_entropy": pl.List(pl.Float32),
            },
        )
