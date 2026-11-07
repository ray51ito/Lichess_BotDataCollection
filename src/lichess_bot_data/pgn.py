"""Fast, dependency-free parsing of Lichess dump PGN text (headers, moves, clocks, evals)."""

from __future__ import annotations

import re
from dataclasses import dataclass

MATE_CP: float = 10000.0
"""Centipawn value used to encode a forced mate (sign = side that mates)."""

_HEADER_RE = re.compile(r'^\[(\w+) "(.*)"\]$', re.MULTILINE)
_TOKEN_RE = re.compile(r"\{[^}]*\}|\S+")
_CLK_RE = re.compile(r"\[%clk (\d+):(\d{2}):(\d{2})(?:\.\d+)?\]")
_EVAL_RE = re.compile(r"\[%eval (#?)(-?[\d.]+)\]")
_MOVE_NUMBER_RE = re.compile(r"^\d+\.(\.\.)?$")
_RESULTS = frozenset({"1-0", "0-1", "1/2-1/2", "*"})


@dataclass(frozen=True)
class Movetext:
    """Per-ply data parsed from a PGN movetext section.

    Attributes:
        sans: SAN moves without annotation glyphs.
        clocks: Remaining clock (seconds) after each ply, or None if absent.
        evals: White-perspective evaluation in centipawns after each ply, or None.
    """

    sans: list[str]
    clocks: list[int | None]
    evals: list[float | None]

    @property
    def has_clocks(self) -> bool:
        """Whether every ply carries a clock annotation."""
        return bool(self.clocks) and all(c is not None for c in self.clocks)

    @property
    def has_evals(self) -> bool:
        """Whether at least one ply carries an eval annotation."""
        return any(e is not None for e in self.evals)


def parse_headers(text: str) -> dict[str, str]:
    """Parses PGN tag pairs into a dict.

    Args:
        text: The header section of one game (lines like ``[Key "Value"]``).
    """
    return dict(_HEADER_RE.findall(text))


def parse_movetext(text: str) -> Movetext:
    """Parses moves and their ``%clk`` / ``%eval`` comments.

    Args:
        text: The movetext section of one game, as written in Lichess dumps.
    """
    sans: list[str] = []
    clocks: list[int | None] = []
    evals: list[float | None] = []

    for token in _TOKEN_RE.findall(text):
        # comments annotate the preceding ply
        if token.startswith("{"):
            if sans:
                clocks[-1] = _parse_clock(token)
                evals[-1] = _parse_eval(token)
            continue
        if _MOVE_NUMBER_RE.match(token):
            continue
        if token in _RESULTS:
            break
        sans.append(token.rstrip("?!"))
        clocks.append(None)
        evals.append(None)

    return Movetext(sans, clocks, evals)


def _parse_clock(comment: str) -> int | None:
    match = _CLK_RE.search(comment)
    if match is None:
        return None
    hours, minutes, seconds = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _parse_eval(comment: str) -> float | None:
    match = _EVAL_RE.search(comment)
    if match is None:
        return None
    is_mate, value = match.groups()
    number = float(value)
    if is_mate:
        return MATE_CP if number > 0 else -MATE_CP
    return number * 100.0


def parse_time_control(value: str) -> tuple[int | None, int | None]:
    """Splits a ``TimeControl`` tag such as ``300+3`` into (base, increment) seconds.

    Returns (None, None) for correspondence games (``-``) or malformed values.
    """
    base, sep, inc = value.partition("+")
    if not sep or not base.isdigit() or not inc.isdigit():
        return None, None
    return int(base), int(inc)


def split_game(game: str) -> tuple[str, str]:
    """Splits one game's text into (header section, movetext section)."""
    head, _, moves = game.partition("\n\n")
    return head, moves.strip()
