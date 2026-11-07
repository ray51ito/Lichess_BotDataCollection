"""Fetches BOT account profiles from the Lichess API and classifies their engine family."""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from lichess_bot_data.api import USERS_BATCH, LichessApi
from lichess_bot_data.io import write_parquet_atomic

"""Bulk user-profile endpoint (POST, comma-separated usernames, max 300)."""


class EngineFamily(StrEnum):
    """Coarse engine family declared by a bot's name or profile text."""

    MAIA = "maia"
    HUMANLIKE = "humanlike"
    LEELA = "leela"
    STOCKFISH = "stockfish"
    RETRO = "retro"
    WEAK_NOVELTY = "weak_novelty"
    HOMEMADE = "homemade"
    UNKNOWN = "unknown"


# ordered: the first matching family wins
_FAMILY_PATTERNS: list[tuple[EngineFamily, re.Pattern[str]]] = [
    (EngineFamily.MAIA, re.compile(r"\bmaia", re.IGNORECASE)),
    (
        EngineFamily.HUMANLIKE,
        re.compile(
            r"human[- ]?like|human style|plays like a human|imitat|trained on (?:human|lichess)"
            r"|human games|allie\b|humanlike",
            re.IGNORECASE,
        ),
    ),
    (EngineFamily.LEELA, re.compile(r"\blc0\b|leela|lczero", re.IGNORECASE)),
    (EngineFamily.STOCKFISH, re.compile(r"stockfish|\bsf ?\d|\bsf\b|fairy-?sf", re.IGNORECASE)),
    (
        EngineFamily.WEAK_NOVELTY,
        re.compile(
            r"random|worstfish|patzer|suicid|blunder|\bworst\b|\bdumb|silly|weakest",
            re.IGNORECASE,
        ),
    ),
    (
        EngineFamily.HOMEMADE,
        re.compile(
            r"my (?:own )?engine|homemade|home-made|written in|engine (?:written|made|coded)"
            r"|\bin (?:rust|c\+\+|python|java|go|c#|zig)\b|alpha-?beta|negamax|minimax|nnue",
            re.IGNORECASE,
        ),
    ),
]


def classify_engine(username: str, bio: str | None, real_name: str | None) -> EngineFamily:
    """Classifies a bot by keywords in its username, real name and bio.

    Args:
        username: Lichess username.
        bio: Profile bio text, if any.
        real_name: Profile "real name" field, if any.
    """
    text = " ".join(part for part in (username, real_name, bio) if part)
    for family, pattern in _FAMILY_PATTERNS:
        if pattern.search(text):
            return family
    return EngineFamily.UNKNOWN


def _profile_row(user: dict[str, Any]) -> dict[str, Any]:
    profile: dict[str, Any] = user.get("profile", {})
    play_time: dict[str, Any] = user.get("playTime", {})
    bio = profile.get("bio")
    real_name = profile.get("realName")
    return {
        "bot": user["username"],
        "bot_id": user["id"],
        "title": user.get("title"),
        "created_at_ms": user.get("createdAt"),
        "seen_at_ms": user.get("seenAt"),
        "verified": bool(user.get("verified", False)),
        "disabled": bool(user.get("disabled", False)),
        "tos_violation": bool(user.get("tosViolation", False)),
        "play_time_total_s": play_time.get("total"),
        "play_time_human_s": play_time.get("human"),
        "real_name": real_name,
        "bio": bio,
        "engine_family": str(classify_engine(user["username"], bio, real_name)),
    }


class BotProfileCollector:
    """Downloads profiles for a list of bot usernames and stores them as Parquet."""

    def __init__(self, client: httpx.Client | None = None, pause_s: float = 1.0) -> None:
        """Creates a collector.

        Args:
            client: HTTP client to use (a default one is created when None).
            pause_s: Delay between batched requests, to respect API rate limits.
        """
        self._api = LichessApi(client, pause_s)

    def fetch(self, usernames: Iterable[str]) -> pl.DataFrame:
        """Fetches profiles in batches; usernames that no longer exist are omitted."""
        names = sorted(set(usernames))
        rows: list[dict[str, Any]] = []
        for start in range(0, len(names), USERS_BATCH):
            rows.extend(
                _profile_row(u) for u in self._api.users(names[start : start + USERS_BATCH])
            )
        return pl.DataFrame(rows, infer_schema_length=None)

    def collect(self, usernames: Iterable[str], out_path: Path) -> pl.DataFrame:
        """Fetches profiles and writes them to ``out_path``."""
        frame = self.fetch(usernames)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_parquet_atomic(frame, out_path)
        return frame


def load_codebook(path: Path) -> pl.DataFrame:
    """Loads the hand-coded bot codebook (columns: bot, engine_family, basis).

    Raises:
        ValueError: If a row uses a family that is not an ``EngineFamily`` value.
    """
    codebook = pl.read_csv(path, schema_overrides={"bot": pl.Utf8, "engine_family": pl.Utf8})
    unknown = set(codebook["engine_family"]) - {str(f) for f in EngineFamily}
    if unknown:
        raise ValueError(f"unknown engine families in codebook: {sorted(unknown)}")
    return codebook


def apply_codebook(profiles: pl.DataFrame, codebook: pl.DataFrame) -> pl.DataFrame:
    """Overrides keyword families with codebook families (case-insensitive bot match).

    Adds ``family_source`` = ``codebook`` or ``keyword``.
    """
    coded = codebook.select(
        pl.col("bot").str.to_lowercase().alias("_key"),
        pl.col("engine_family").alias("_coded"),
    )
    return (
        profiles.with_columns(pl.col("bot").str.to_lowercase().alias("_key"))
        .join(coded, on="_key", how="left")
        .with_columns(
            pl.when(pl.col("_coded").is_not_null())
            .then(pl.lit("codebook"))
            .otherwise(pl.lit("keyword"))
            .alias("family_source"),
            pl.coalesce("_coded", "engine_family").alias("engine_family"),
        )
        .drop("_key", "_coded")
    )
