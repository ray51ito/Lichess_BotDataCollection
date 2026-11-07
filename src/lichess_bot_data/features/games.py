"""Builds player-perspective game tables (one row per focal player per game)."""

from __future__ import annotations

import statistics
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import polars as pl

from lichess_bot_data.extract import BOT_TITLE
from lichess_bot_data.features.game_metrics import (
    EndType,
    elo_expected_score,
    end_type,
    eval_metrics,
    game_duration_s,
    move_times,
    player_score,
)
from lichess_bot_data.pgn import parse_time_control

FAST_MOVE_S: float = 1.0
"""Moves taking at most this many seconds count as 'fast' (clock resolution is 1 s)."""

OPENING_PLIES: int = 6
"""Number of plies kept as the opening signature."""

LINE_PLIES: int = 16
"""Number of plies kept as the line signature used to detect repeated games."""


class Perspective(StrEnum):
    """Which side(s) of a game become focal-player rows."""

    HUMAN_VS_BOT = "human_vs_bot"
    BOTH_SIDES = "both_sides"


SPEEDS: tuple[str, ...] = ("ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence")
"""Lichess speed names that appear as the second word of standard ``Event`` tags."""


def speed_from_time_control(base_s: int | None, inc_s: int | None) -> str:
    """Lichess speed category from the estimated duration ``base + 40 * increment``."""
    if base_s is None:
        return "correspondence"
    total = base_s + 40 * (inc_s or 0)
    for limit, name in ((29, "ultrabullet"), (179, "bullet"), (479, "blitz"), (1499, "rapid")):
        if total <= limit:
            return name
    return "classical"


def _speed(event: str | None, base_s: int | None = None, inc_s: int | None = None) -> str:
    # variant events ("Rated Chess960 game") carry no speed word: derive it from the clock
    words = (event or "").split()
    word = words[1].lower() if len(words) > 1 else ""
    return word if word in SPEEDS else speed_from_time_control(base_s, inc_s)


def _outcome(score: float | None) -> str | None:
    return {1.0: "win", 0.5: "draw", 0.0: "loss"}.get(score) if score is not None else None


def _time_stats(times: Sequence[float | None]) -> dict[str, float | int | None]:
    measured = [t for t in times if t is not None]
    if not measured:
        return {"mean": None, "median": None, "cv": None, "frac_fast": None, "n": 0}
    mean = statistics.fmean(measured)
    sd = statistics.pstdev(measured) if len(measured) > 1 else 0.0
    return {
        "mean": mean,
        "median": statistics.median(measured),
        "cv": sd / mean if mean > 0 else None,
        "frac_fast": sum(t <= FAST_MOVE_S for t in measured) / len(measured),
        "n": len(measured),
    }


def _loser(score: float | None) -> str | None:
    return {1.0: "opponent", 0.0: "player"}.get(score) if score is not None else None


def player_row(game: dict[str, Any], player_is_white: bool) -> dict[str, Any]:
    """Converts one extracted game into a row from the focal player's perspective.

    Args:
        game: A row of the extracted game table (see ``extract.GAME_SCHEMA``).
        player_is_white: Whether the focal player had White.
    """
    side, other = ("white", "black") if player_is_white else ("black", "white")
    base, inc = parse_time_control(game["time_control"] or "")
    start = datetime.strptime(f"{game['utc_date']} {game['utc_time']}", "%Y.%m.%d %H:%M:%S")
    start = start.replace(tzinfo=UTC)

    clocks: list[int | None] = game["clocks"] or []
    white_times, black_times = move_times(clocks, base or 0, inc or 0)
    duration = game_duration_s(white_times, black_times)
    player_times, opp_times = (
        (white_times, black_times) if player_is_white else (black_times, white_times)
    )

    sans: list[str] = (game["sans"] or "").split()
    score = player_score(game["result"], opponent_is_white=not player_is_white)
    kind = end_type(game["termination"], game["result"], sans[-1] if sans else None)
    player_elo, opp_elo = game[f"{side}_elo"], game[f"{other}_elo"]
    if kind == EndType.TIMEOUT:
        duration += flag_time_s(clocks)

    row: dict[str, Any] = {
        "game_id": game["game_id"],
        "start": start,
        "end": start + timedelta(seconds=duration),
        "duration_s": duration,
        "speed": _speed(game["event"], base, inc),
        "variant": "chess960" if "chess960" in (game["event"] or "").lower() else "standard",
        "is_tournament": "tournament" in (game["event"] or "").lower()
        or "swiss" in (game["event"] or "").lower(),
        "base_s": base,
        "inc_s": inc,
        "player": game[side],
        "opponent": game[other],
        "player_is_white": player_is_white,
        "opponent_is_bot": game[f"{other}_title"] == BOT_TITLE,
        "player_elo": player_elo,
        "opponent_elo": opp_elo,
        "elo_gap": player_elo - opp_elo if player_elo and opp_elo else None,
        "expected_score": elo_expected_score(player_elo, opp_elo)
        if player_elo and opp_elo
        else None,
        "player_score": score,
        "outcome": _outcome(score),
        "player_rating_diff": game[f"{side}_rating_diff"],
        "end_type": str(kind),
        "loser": _loser(score) if kind != EndType.DRAW else None,
        "n_plies": len(sans) if sans else len(clocks),
        "opening": " ".join(sans[:OPENING_PLIES]) if sans else None,
        "line": " ".join(sans[:LINE_PLIES]) if len(sans) >= LINE_PLIES else None,
        "eco": game["eco"],
        "opening_name": game["opening"],
        "player_final_clock_s": _final_clock(clocks, player_is_white),
        "opponent_final_clock_s": _final_clock(clocks, not player_is_white),
    }
    for prefix, times in (("player", player_times), ("opponent", opp_times)):
        for key, value in _time_stats(times).items():
            row[f"{prefix}_time_{key}"] = value

    evals: list[float | None] | None = game["evals"]
    metrics = eval_metrics(evals, opponent_is_white=not player_is_white) if evals else None
    row["has_evals"] = metrics is not None
    for field in _EVAL_FIELDS:
        row[field] = getattr(metrics, field) if metrics is not None else None
    return row


_EVAL_FIELDS: tuple[str, ...] = (
    "opponent_mean_loss",
    "player_mean_loss",
    "opponent_blunders",
    "player_blunders",
    "opponent_mistakes",
    "lead_changes",
    "player_max_wp",
    "player_min_wp",
    "surprise",
    "uncertainty",
    "opponent_conversion_plies",
    "player_conversion_plies",
    "final_player_wp",
)


def flag_time_s(clocks: Sequence[int | None]) -> float:
    """Seconds the side to move spent before its flag fell (its last recorded clock).

    Move times cover only the moves that were played; in a time forfeit the side to move
    then used up its remaining clock, which belongs to the game's duration too.
    """
    to_move_is_white = len(clocks) % 2 == 0
    remaining = _final_clock(clocks, to_move_is_white)
    return float(remaining) if remaining is not None else 0.0


def _final_clock(clocks: Sequence[int | None], white: bool) -> int | None:
    parity = 0 if white else 1
    side_clocks = [c for i, c in enumerate(clocks) if i % 2 == parity and c is not None]
    return side_clocks[-1] if side_clocks else None


def _focal_sides(game: dict[str, Any], perspective: Perspective) -> Iterator[bool]:
    if perspective is Perspective.BOTH_SIDES:
        yield True
        yield False
        return
    # human-vs-bot: the focal player is the side without the BOT title
    yield game["white_title"] != BOT_TITLE


def build_player_table(games: pl.DataFrame, perspective: Perspective) -> pl.DataFrame:
    """Builds the player-perspective table, sorted by player and start time.

    Args:
        games: Extracted games (``bot_games`` or ``baseline_games`` Parquet).
        perspective: Which sides become focal-player rows.
    """
    rows = [
        player_row(game, player_is_white)
        for game in games.iter_rows(named=True)
        for player_is_white in _focal_sides(game, perspective)
    ]
    return pl.DataFrame(rows, infer_schema_length=None).sort(["player", "start"])
