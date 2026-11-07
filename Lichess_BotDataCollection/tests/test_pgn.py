"""Tests for the PGN parsing helpers."""

from lichess_bot_data.pgn import (
    MATE_CP,
    parse_headers,
    parse_movetext,
    parse_time_control,
    split_game,
)

GAME = """[Event "Rated Blitz game"]
[Site "https://lichess.org/UbNJgOId"]
[White "pawnsaretricky"]
[Black "maia5"]
[Result "1-0"]
[BlackTitle "BOT"]
[TimeControl "300+3"]

1. e4 { [%eval 0.18] [%clk 0:05:00] } 1... e5 { [%eval 0.22] [%clk 0:05:00] } \
2. Nf3?! { [%eval #-3] [%clk 0:04:58] } 2... Qh4# { [%clk 1:00:02] } 1-0
"""


def test_split_and_headers() -> None:
    head, moves = split_game(GAME)
    headers = parse_headers(head)
    assert headers["Black"] == "maia5"
    assert headers["BlackTitle"] == "BOT"
    assert moves.startswith("1. e4")


def test_movetext_clocks_evals_and_glyphs() -> None:
    parsed = parse_movetext(split_game(GAME)[1])
    assert parsed.sans == ["e4", "e5", "Nf3", "Qh4#"]
    assert parsed.clocks == [300, 300, 298, 3602]
    assert parsed.evals == [18.0, 22.0, -MATE_CP, None]
    assert parsed.has_clocks
    assert parsed.has_evals


def test_movetext_without_comments() -> None:
    parsed = parse_movetext("1. d4 d5 2. c4 0-1")
    assert parsed.sans == ["d4", "d5", "c4"]
    assert not parsed.has_clocks
    assert not parsed.has_evals


def test_time_control() -> None:
    assert parse_time_control("300+3") == (300, 3)
    assert parse_time_control("-") == (None, None)
