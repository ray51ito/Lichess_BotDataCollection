"""Derives revealed-preference outcomes (rematch, switching, return) from play order."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class SequenceConfig:
    """Time thresholds that define the behavioural outcomes.

    Attributes:
        rematch_s: Max gap (s) between a game's end and the next game's start for a rematch.
        session_gap_s: Gap (s) above which a new session starts.
        return_window_s: Window (s) after a session in which a return counts.
    """

    rematch_s: float = 120.0
    session_gap_s: float = 1800.0
    return_window_s: float = 7 * 86400.0


def annotate_sequences(table: pl.DataFrame, cfg: SequenceConfig | None = None) -> pl.DataFrame:
    """Adds sequence-based outcome columns to a player-perspective table.

    Added columns: ``gap_next_s``, ``next_opponent``, ``next_opponent_elo``,
    ``rematch``, ``continue_session``, ``switch``, ``switch_elo_delta``,
    ``pair_game_index``, ``player_game_index``, ``pair_session_id``,
    ``session_game_index``, ``session_last``, ``session_length``, ``gap_pair_next_s``,
    ``return_7d`` (meaningful on ``session_last`` rows; null when censored by the data end).

    Args:
        table: Output of ``build_player_table`` (needs player, opponent, start, end).
        cfg: Outcome thresholds; defaults to ``SequenceConfig()``.
    """
    cfg = cfg or SequenceConfig()
    data_end = table["start"].max()
    gap = (pl.col("next_start") - pl.col("end")).dt.total_milliseconds() / 1000.0
    pair_gap = (pl.col("pair_next_start") - pl.col("end")).dt.total_milliseconds() / 1000.0
    prev_pair_gap = (pl.col("start") - pl.col("pair_prev_end")).dt.total_milliseconds() / 1000.0
    censored = pl.col("end") > data_end - pl.duration(seconds=cfg.return_window_s)
    returned = (pl.col("gap_pair_next_s") > cfg.session_gap_s) & (
        pl.col("gap_pair_next_s") <= cfg.return_window_s
    )

    out = (
        table.sort(["player", "start"])
        .with_columns(
            pl.col("start").shift(-1).over("player").alias("next_start"),
            pl.col("opponent").shift(-1).over("player").alias("next_opponent"),
            pl.col("opponent_elo").shift(-1).over("player").alias("next_opponent_elo"),
            pl.int_range(pl.len()).over("player").alias("player_game_index"),
            pl.col("start").shift(-1).over(["player", "opponent"]).alias("pair_next_start"),
            pl.col("end").shift(1).over(["player", "opponent"]).alias("pair_prev_end"),
            pl.int_range(pl.len()).over(["player", "opponent"]).alias("pair_game_index"),
        )
        .with_columns(
            gap.alias("gap_next_s"),
            pair_gap.alias("gap_pair_next_s"),
            (prev_pair_gap.is_null() | (prev_pair_gap > cfg.session_gap_s)).alias("_new_session"),
        )
        .with_columns(
            (
                (pl.col("next_opponent") == pl.col("opponent"))
                & (pl.col("gap_next_s") <= cfg.rematch_s)
            )
            .fill_null(False)
            .alias("rematch"),
            (pl.col("gap_next_s") <= cfg.session_gap_s).fill_null(False).alias("continue_session"),
            pl.col("_new_session")
            .cast(pl.Int32)
            .cum_sum()
            .over(["player", "opponent"])
            .alias("pair_session_id"),
        )
        .with_columns(
            (pl.col("continue_session") & (pl.col("next_opponent") != pl.col("opponent"))).alias(
                "switch"
            ),
            pl.int_range(pl.len())
            .over(["player", "opponent", "pair_session_id"])
            .alias("session_game_index"),
            pl.len().over(["player", "opponent", "pair_session_id"]).alias("session_length"),
        )
        .with_columns(
            pl.when(pl.col("switch"))
            .then(pl.col("next_opponent_elo") - pl.col("opponent_elo"))
            .otherwise(None)
            .alias("switch_elo_delta"),
            (pl.col("session_game_index") == pl.col("session_length") - 1).alias("session_last"),
        )
        .with_columns(
            pl.when(censored).then(None).otherwise(returned.fill_null(False)).alias("return_7d"),
        )
        .drop(["next_start", "pair_next_start", "pair_prev_end", "_new_session"])
    )
    return out
