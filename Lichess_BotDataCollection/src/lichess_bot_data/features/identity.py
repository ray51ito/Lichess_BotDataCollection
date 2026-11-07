"""Canonical account names: one spelling per Lichess account.

Lichess ids are case-insensitive, but the dumps of December 2023 to September 2024 write many
human names in a different case game by game (``PaulBonomi`` / ``paulbonomi``), and accounts
can change the case of their name over the years. Grouping on the raw name then splits one
person into two timelines. Every name is therefore mapped to one spelling per lowercase id:
the spelling used most often (ties: the alphabetically first).
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl


def canonical_spellings(names: pl.Series) -> pl.DataFrame:
    """Most frequent spelling per lowercase id (columns ``id`` and ``canonical``).

    Args:
        names: Every occurrence of a name (one entry per row that uses it).
    """
    counts = names.drop_nulls().to_frame("name").group_by("name").agg(pl.len().alias("n"))
    return (
        counts.with_columns(pl.col("name").str.to_lowercase().alias("id"))
        .sort(["id", "n", "name"], descending=[False, True, False])
        .group_by("id", maintain_order=True)
        .first()
        .select("id", pl.col("name").alias("canonical"))
    )


def canonicalise(table: pl.DataFrame, columns: Sequence[str]) -> pl.DataFrame:
    """Replaces each name column by its canonical spelling (computed over ``table`` itself)."""
    out = table
    for column in columns:
        spellings = canonical_spellings(table[column])
        out = (
            out.with_columns(pl.col(column).str.to_lowercase().alias("_id"))
            .join(spellings, left_on="_id", right_on="id", how="left")
            .with_columns(pl.coalesce("canonical", column).alias(column))
            .drop("_id", "canonical")
        )
    return out


def align_names(table: pl.DataFrame, columns: Sequence[str], reference: pl.Series) -> pl.DataFrame:
    """Rewrites names in ``columns`` to the spelling used in ``reference`` (case-insensitive).

    Names without a case-insensitive match in ``reference`` are left unchanged.

    Args:
        table: Table whose name columns are rewritten (e.g. watched human games).
        columns: Name columns to rewrite.
        reference: Canonical names to align to (e.g. the analysis table's players).
    """
    spellings = canonical_spellings(reference.unique())
    out = table
    for column in columns:
        out = (
            out.with_columns(pl.col(column).str.to_lowercase().alias("_id"))
            .join(spellings, left_on="_id", right_on="id", how="left")
            .with_columns(pl.coalesce("canonical", column).alias(column))
            .drop("_id", "canonical")
        )
    return out


def activity_by_id(activity: pl.DataFrame, user: str = "user") -> pl.DataFrame:
    """Human-game counts summed over spellings (columns ``id`` and ``n_human_games``)."""
    return activity.group_by(pl.col(user).str.to_lowercase().alias("id")).agg(
        pl.col("n_human_games").sum()
    )
