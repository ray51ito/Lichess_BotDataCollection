"""Aggregates per-bot behaviour and preference metrics from human-vs-bot game rows."""

from __future__ import annotations

import polars as pl

MIN_OPENING_GAMES: int = 10
"""Minimum games needed to compute an opening-diversity component."""


def bot_own_moves(opening: str | None, bot_is_white: bool, n: int = 2) -> str | None:
    """Returns the bot's first ``n`` own moves from a space-separated opening signature.

    Args:
        opening: First plies of the game, space-separated SAN.
        bot_is_white: Whether the bot played White.
        n: Number of own moves to keep.
    """
    if not opening:
        return None
    plies = opening.split()
    own = plies[0 if bot_is_white else 1 :: 2][:n]
    return " ".join(own) if len(own) == n else None


def simpson_diversity(values: pl.Series) -> float | None:
    """Gini-Simpson diversity (1 - sum p^2) of a categorical series; None if too small."""
    values = values.drop_nulls()
    if values.len() < MIN_OPENING_GAMES:
        return None
    shares = values.value_counts(normalize=True)["proportion"]
    return 1.0 - float((shares**2).sum())


def _opening_diversity(games: pl.DataFrame) -> pl.DataFrame:
    # bot as White: its first move; bot as Black: its reply to 1.e4
    rows: list[dict[str, object]] = []
    for (bot,), group in games.group_by(["opponent"]):
        as_white = group.filter(~pl.col("player_is_white"))["opening"].map_elements(
            lambda s: s.split()[0] if s else None, return_dtype=pl.Utf8
        )
        vs_e4 = group.filter(pl.col("player_is_white") & pl.col("opening").str.starts_with("e4 "))
        reply = vs_e4["opening"].map_elements(lambda s: s.split()[1], return_dtype=pl.Utf8)
        diversities = (simpson_diversity(as_white), simpson_diversity(reply))
        parts = [d for d in diversities if d is not None]
        rows.append(
            {"opponent": bot, "opening_diversity": sum(parts) / len(parts) if parts else None}
        )
    return pl.DataFrame(rows, schema={"opponent": pl.Utf8, "opening_diversity": pl.Float64})


def aggregate_bot_features(games: pl.DataFrame) -> pl.DataFrame:
    """Builds one row per bot with behaviour, strength, ending and preference metrics.

    Args:
        games: Annotated human-vs-bot player table (``annotate_sequences`` output),
            optionally with Stockfish-based eval columns.
    """
    bot_lost = pl.col("loser") == "opponent"
    bot_won = pl.col("loser") == "player"
    last = pl.col("session_last")

    def share(cond: pl.Expr, among: pl.Expr) -> pl.Expr:
        return cond.filter(among).mean()

    agg = games.group_by("opponent").agg(
        pl.len().alias("n_games"),
        pl.col("player").n_unique().alias("n_players"),
        pl.col("opponent_elo").median().alias("bot_elo_median"),
        pl.col("speed").mode().first().alias("main_speed"),
        pl.col("player_elo").median().alias("player_elo_median"),
        pl.col("player_score").mean().alias("player_score_mean"),
        pl.col("expected_score").mean().alias("expected_score_mean"),
        pl.col("opponent_time_median").median().alias("think_median_s"),
        pl.col("opponent_time_cv").median().alias("think_cv"),
        pl.col("opponent_time_frac_fast").median().alias("think_frac_fast"),
        share(pl.col("end_type") == "resign", bot_lost).alias("lost_by_resign"),
        share(pl.col("end_type") == "checkmate", bot_lost).alias("lost_by_mate"),
        share(pl.col("end_type") == "timeout", bot_lost).alias("lost_on_time"),
        share(pl.col("end_type") == "timeout", bot_won).alias("won_on_time"),
        share(pl.col("end_type") == "checkmate", bot_won).alias("won_by_mate"),
        pl.col("opponent_mean_loss").mean().alias("bot_mean_loss"),
        (pl.col("opponent_blunders") / (pl.col("n_plies") / 2)).mean().alias("bot_blunder_rate"),
        pl.col("has_evals").sum().alias("n_eval_games"),
        pl.col("rematch").mean().alias("rematch_rate"),
        pl.col("return_7d").filter(last).mean().alias("return_7d_rate"),
        pl.col("session_length")
        .filter(pl.col("session_game_index") == 0)
        .mean()
        .alias("mean_session_length"),
    )
    return (
        agg.join(_opening_diversity(games), on="opponent", how="left")
        .with_columns((pl.col("n_games") / pl.col("n_players")).alias("games_per_player"))
        .sort("n_games", descending=True)
    )
