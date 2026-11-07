"""Tests for bot engine-family classification and profile parsing."""

from pathlib import Path

import httpx
import polars as pl

from lichess_bot_data.bots import (
    BotProfileCollector,
    EngineFamily,
    apply_codebook,
    classify_engine,
    load_codebook,
)


def test_classify_engine_families() -> None:
    assert classify_engine("maia5", "human-like neural network", None) == EngineFamily.MAIA
    assert classify_engine("x", "A bot that plays like a human", None) == EngineFamily.HUMANLIKE
    assert classify_engine("LeelaFan", None, None) == EngineFamily.LEELA
    assert classify_engine("bot1", "Running Stockfish 17", None) == EngineFamily.STOCKFISH
    assert classify_engine("RandomMover", None, None) == EngineFamily.WEAK_NOVELTY
    assert classify_engine("b", "My own engine written in Rust", None) == EngineFamily.HOMEMADE
    assert classify_engine("b", "hello", None) == EngineFamily.UNKNOWN


def test_collector_parses_profiles() -> None:
    payload = [
        {
            "id": "maia5",
            "username": "maia5",
            "title": "BOT",
            "createdAt": 1,
            "profile": {"bio": "Maia is human-like"},
            "playTime": {"total": 10, "human": 7},
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.content == b"maia5"
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    frame = BotProfileCollector(client, pause_s=0).fetch(["maia5"])
    assert frame["engine_family"].to_list() == ["maia"]
    assert frame["play_time_human_s"].to_list() == [7]


def test_apply_codebook_overrides_case_insensitively(tmp_path: Path) -> None:
    path = tmp_path / "codebook.csv"
    path.write_text("bot,engine_family,basis\nleelaalien,leela,bio says Lc0\n", encoding="utf-8")
    profiles = pl.DataFrame({"bot": ["LeelaAlien", "maia5"], "engine_family": ["maia", "maia"]})
    out = apply_codebook(profiles, load_codebook(path))
    assert out["engine_family"].to_list() == ["leela", "maia"]
    assert out["family_source"].to_list() == ["codebook", "keyword"]
