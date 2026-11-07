"""Pure per-game metrics: move times, win probabilities, error, suspense and end type."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

LICHESS_WP_SCALE: float = 0.00368208
"""Logistic scale of Lichess' centipawn-to-win-probability conversion."""

BLUNDER_DROP: float = 0.15
"""Win-probability drop (0-1 scale) Lichess labels a blunder (0.3 on its -1..1 scale)."""

MISTAKE_DROP: float = 0.10
"""Win-probability drop (0-1 scale) Lichess labels a mistake."""

START_EVAL_CP: float = 20.0
"""Assumed White advantage (cp) before the first move."""


class EndType(StrEnum):
    """How a game finished."""

    CHECKMATE = "checkmate"
    RESIGN = "resign"
    TIMEOUT = "timeout"
    DRAW = "draw"
    ABANDONED = "abandoned"
    OTHER = "other"


def win_probability(cp: float) -> float:
    """Converts a White-perspective centipawn eval into White's win probability."""
    return 1.0 / (1.0 + math.exp(-LICHESS_WP_SCALE * cp))


def move_times(
    clocks: Sequence[int | None], base_s: int, inc_s: int
) -> tuple[list[float | None], list[float | None]]:
    """Returns seconds spent per move for (white, black).

    The first move of each side is untimed on Lichess and returned as None.

    Args:
        clocks: Remaining clock after each ply (seconds).
        base_s: Initial clock (seconds).
        inc_s: Increment per move (seconds).
    """
    spent: tuple[list[float | None], list[float | None]] = ([], [])
    previous: list[int | None] = [None, None]
    for ply, clock in enumerate(clocks):
        side = ply % 2
        prev = previous[side]
        if ply < 2 or clock is None or prev is None:
            spent[side].append(None)
        else:
            spent[side].append(float(max(prev - clock + inc_s, 0)))
        previous[side] = clock if clock is not None else prev
    del base_s  # the first clock already reflects the base time
    return spent


def game_duration_s(
    white_times: Sequence[float | None], black_times: Sequence[float | None]
) -> float:
    """Estimates wall-clock game duration as the total measured thinking time."""
    return sum(t for t in (*white_times, *black_times) if t is not None)


@dataclass(frozen=True)
class EvalMetrics:
    """Eval-derived metrics of one game, from the focal player's perspective.

    Attributes:
        opponent_mean_loss: Mean win-probability loss per opponent move.
        player_mean_loss: Mean win-probability loss per player move.
        opponent_blunders: Opponent moves losing >= BLUNDER_DROP win probability.
        player_blunders: Player moves losing >= BLUNDER_DROP win probability.
        opponent_mistakes: Opponent moves losing >= MISTAKE_DROP win probability.
        lead_changes: Crossings between player advantage (>0.6) and disadvantage (<0.4).
        player_max_wp: Highest player win probability reached.
        player_min_wp: Lowest player win probability reached.
        surprise: Sum of absolute win-probability changes (belief movement).
        uncertainty: Mean of wp * (1 - wp) across plies (outcome uncertainty).
        opponent_conversion_plies: Plies from the opponent first reaching wp >= 0.95 to the end,
            or None if never reached.
        player_conversion_plies: Plies from the player first reaching wp >= 0.95 to the end,
            or None if never reached.
        final_player_wp: Player win probability after the last evaluated ply.
    """

    opponent_mean_loss: float
    player_mean_loss: float
    opponent_blunders: int
    player_blunders: int
    opponent_mistakes: int
    lead_changes: int
    player_max_wp: float
    player_min_wp: float
    surprise: float
    uncertainty: float
    opponent_conversion_plies: int | None
    player_conversion_plies: int | None
    final_player_wp: float


def eval_metrics(evals: Sequence[float | None], opponent_is_white: bool) -> EvalMetrics | None:
    """Computes eval-derived metrics; returns None when no ply is evaluated.

    Missing evals are carried forward from the previous ply.

    Args:
        evals: White-perspective centipawn eval after each ply.
        opponent_is_white: Whether the opponent played White.
    """
    if not any(e is not None for e in evals):
        return None

    # player-perspective win probability before the first move and after each ply
    sign = -1.0 if opponent_is_white else 1.0
    wp_player = [win_probability(sign * START_EVAL_CP)]
    last = START_EVAL_CP
    for e in evals:
        last = e if e is not None else last
        wp_player.append(win_probability(sign * last))

    opponent_losses: list[float] = []
    player_losses: list[float] = []
    for ply in range(len(evals)):
        mover_is_white = ply % 2 == 0
        delta = wp_player[ply + 1] - wp_player[ply]
        if mover_is_white == opponent_is_white:
            opponent_losses.append(max(delta, 0.0))
        else:
            player_losses.append(max(-delta, 0.0))

    return EvalMetrics(
        opponent_mean_loss=_mean(opponent_losses),
        player_mean_loss=_mean(player_losses),
        opponent_blunders=sum(loss >= BLUNDER_DROP for loss in opponent_losses),
        player_blunders=sum(loss >= BLUNDER_DROP for loss in player_losses),
        opponent_mistakes=sum(loss >= MISTAKE_DROP for loss in opponent_losses),
        lead_changes=_lead_changes(wp_player),
        player_max_wp=max(wp_player),
        player_min_wp=min(wp_player),
        surprise=sum(abs(b - a) for a, b in pairwise(wp_player)),
        uncertainty=_mean([p * (1.0 - p) for p in wp_player]),
        opponent_conversion_plies=_conversion_plies([1.0 - p for p in wp_player]),
        player_conversion_plies=_conversion_plies(wp_player),
        final_player_wp=wp_player[-1],
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _lead_changes(wp_player: Sequence[float], high: float = 0.6, low: float = 0.4) -> int:
    state = 0
    changes = 0
    for p in wp_player:
        new_state = 1 if p > high else -1 if p < low else state
        if state not in (0, new_state):
            changes += 1
        state = new_state
    return changes


def _conversion_plies(wp_side: Sequence[float], threshold: float = 0.95) -> int | None:
    for index, p in enumerate(wp_side):
        if p >= threshold:
            return len(wp_side) - 1 - index
    return None


def end_type(termination: str | None, result: str | None, last_san: str | None) -> EndType:
    """Classifies how a game ended from its Termination/Result tags and final move.

    Args:
        termination: Lichess ``Termination`` tag (``Normal``, ``Time forfeit``, ...).
        result: PGN result (``1-0``, ``0-1``, ``1/2-1/2``).
        last_san: Final SAN move, used to detect checkmate.
    """
    if result == "1/2-1/2":
        return EndType.DRAW
    if termination == "Time forfeit":
        return EndType.TIMEOUT
    if termination == "Abandoned":
        return EndType.ABANDONED
    if termination == "Normal":
        if last_san is not None and last_san.endswith("#"):
            return EndType.CHECKMATE
        return EndType.RESIGN
    return EndType.OTHER


def player_score(result: str | None, opponent_is_white: bool) -> float | None:
    """Returns the focal player's score (1, 0.5, 0) from a PGN result, or None if unknown."""
    white_score = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(result or "")
    if white_score is None:
        return None
    return 1.0 - white_score if opponent_is_white else white_score


def elo_expected_score(own_elo: float, opponent_elo: float) -> float:
    """Elo expected score of a player against an opponent."""
    return 1.0 / (1.0 + math.pow(10.0, (opponent_elo - own_elo) / 400.0))
