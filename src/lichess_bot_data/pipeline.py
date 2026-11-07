"""Orchestrates the post-extraction stages: profiles, engine sample, feature tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from lichess_bot_data import config
from lichess_bot_data.bots import BotProfileCollector, apply_codebook, load_codebook
from lichess_bot_data.engine import EngineSettings, StockfishEvaluator
from lichess_bot_data.features.bot_features import aggregate_bot_features
from lichess_bot_data.features.games import Perspective, build_player_table
from lichess_bot_data.features.identity import activity_by_id, canonicalise
from lichess_bot_data.features.sequences import annotate_sequences
from lichess_bot_data.io import write_parquet_atomic
from lichess_bot_data.maia import MaiaScorer, MaiaSettings


@dataclass(frozen=True)
class MonthPaths:
    """File locations of one month's interim tables.

    Attributes:
        root: Directory holding the month's tables.
    """

    root: Path

    @classmethod
    def for_month(cls, month: str) -> MonthPaths:
        """Returns the paths for a ``YYYY-MM`` month under ``config.INTERIM_DIR``."""
        return cls(config.INTERIM_DIR / month)

    @property
    def bot_games(self) -> Path:
        """Extracted human-vs-BOT games."""
        return self.root / "bot_games.parquet"

    @property
    def baseline_games(self) -> Path:
        """Extracted human-vs-human baseline games."""
        return self.root / "baseline_games.parquet"

    @property
    def bot_vs_bot_games(self) -> Path:
        """Extracted bot-vs-bot games (headers and clocks only)."""
        return self.root / "bot_vs_bot_games.parquet"

    @property
    def watched_human_games(self) -> Path:
        """Human-vs-human games of watched users (bot players of the watched months)."""
        return self.root / "watched_human_games.parquet"

    @property
    def user_activity(self) -> Path:
        """Human-vs-human game counts per user."""
        return self.root / "user_activity.parquet"

    @property
    def user_activity_monthly(self) -> Path:
        """Human-vs-human game counts per user and month (merged panels only)."""
        return self.root / "user_activity_monthly.parquet"

    @property
    def bot_profiles(self) -> Path:
        """Lichess API profiles of bots."""
        return self.root / "bot_profiles.parquet"

    @property
    def sf_evals(self) -> Path:
        """Stockfish evals of the stratified game sample."""
        return self.root / "sf_evals.parquet"

    @property
    def maia_evals(self) -> Path:
        """Maia probabilities of the played moves in the Stockfish-evaluated sample."""
        return self.root / "maia_evals.parquet"

    @property
    def player_games(self) -> Path:
        """Annotated human-perspective human-vs-bot table."""
        return self.root / "player_games.parquet"

    @property
    def baseline_player_games(self) -> Path:
        """Annotated both-sides human-vs-human baseline table."""
        return self.root / "baseline_player_games.parquet"

    @property
    def bot_features(self) -> Path:
        """One row per bot with aggregated metrics."""
        return self.root / "bot_features.parquet"


def bot_players(paths: MonthPaths) -> set[str]:
    """Returns the human usernames that played a bot in the month (empty if not extracted)."""
    if not paths.bot_games.exists():
        return set()
    games = pl.read_parquet(paths.bot_games, columns=["white", "black", "white_title"])
    humans = games.select(
        pl.when(pl.col("white_title") == "BOT").then(pl.col("black")).otherwise(pl.col("white"))
    ).to_series()
    return set(humans.drop_nulls().to_list())


_CONCAT_TABLES: tuple[str, ...] = (
    "bot_games",
    "baseline_games",
    "bot_vs_bot_games",
    "watched_human_games",
    "sf_evals",
    "maia_evals",
)
"""Extracted tables that a merged panel stacks month by month (missing ones are skipped)."""


def merge_months(months: list[str], target: MonthPaths) -> None:
    """Stacks several months' extracted tables into one panel directory.

    Sequence outcomes are then rebuilt by ``build_tables`` over the joint timeline, so a
    July session can be followed into August. Per-user activity is summed and also kept
    per month; bot profiles come from the latest month that has them.

    Args:
        months: ``YYYY-MM`` months in chronological order.
        target: Output location of the panel.
    """
    sources = [MonthPaths.for_month(m) for m in months]
    target.root.mkdir(parents=True, exist_ok=True)
    for name in _CONCAT_TABLES:
        parts = [pl.read_parquet(getattr(s, name)) for s in sources if getattr(s, name).exists()]
        if parts:
            pl.concat(parts, how="vertical_relaxed").unique("game_id", keep="first").write_parquet(
                getattr(target, name)
            )
    monthly = pl.concat(
        [
            pl.read_parquet(s.user_activity).with_columns(pl.lit(m).alias("month"))
            for m, s in zip(months, sources, strict=True)
        ]
    )
    monthly.write_parquet(target.user_activity_monthly)
    monthly.group_by("user").agg(pl.col("n_human_games").sum()).write_parquet(target.user_activity)
    profiles = [s.bot_profiles for s in reversed(sources) if s.bot_profiles.exists()]
    if profiles:
        pl.read_parquet(profiles[0]).write_parquet(target.bot_profiles)


def study_users(months: list[str], human_sample: int, seed: int = 0) -> pl.DataFrame:
    """Users of the given months for API collection, labelled by role.

    Roles: ``bot`` (bot accounts), ``bot_player`` (humans who played a bot, with their number
    of bot games) and ``human_only`` (a random sample of baseline players who played no bot).
    """
    players: list[pl.DataFrame] = []
    bots: set[str] = set()
    baseline: set[str] = set()
    for month in months:
        paths = MonthPaths.for_month(month)
        games = pl.read_parquet(paths.bot_games, columns=["white", "black", "white_title"])
        is_bot_white = pl.col("white_title") == "BOT"
        players.append(
            games.select(
                pl.when(is_bot_white).then(pl.col("black")).otherwise(pl.col("white")).alias("user")
            )
        )
        bots |= set(
            games.select(pl.when(is_bot_white).then(pl.col("white")).otherwise(pl.col("black")))
            .to_series()
            .to_list()
        )
        if paths.baseline_games.exists():
            base = pl.read_parquet(paths.baseline_games, columns=["white", "black"])
            baseline |= set(base["white"].to_list()) | set(base["black"].to_list())
    counts = pl.concat(players).group_by("user").len().rename({"len": "bot_games"})
    human_only = sorted(baseline - set(counts["user"].to_list()) - bots)
    sample = pl.Series("user", human_only).sample(
        min(human_sample, len(human_only)), seed=seed, shuffle=True
    )
    return pl.concat(
        [
            pl.DataFrame({"user": sorted(bots), "role": "bot", "bot_games": 0}),
            counts.with_columns(pl.lit("bot_player").alias("role")).select(
                "user", "role", "bot_games"
            ),
            pl.DataFrame({"user": sample, "role": "human_only", "bot_games": 0}),
        ],
        how="vertical_relaxed",
    )


def collect_profiles(paths: MonthPaths) -> pl.DataFrame:
    """Fetches API profiles for every bot appearing in the human-vs-bot games."""
    games = pl.read_parquet(paths.bot_games, columns=["white", "black", "white_title"])
    bots = games.select(
        pl.when(pl.col("white_title") == "BOT").then(pl.col("white")).otherwise(pl.col("black"))
    ).to_series()
    return BotProfileCollector().collect(bots.unique().to_list(), paths.bot_profiles)


def stratified_sample(games: pl.DataFrame, per_bot: int, seed: int = 0) -> pl.DataFrame:
    """Samples up to ``per_bot`` random games for each bot.

    Args:
        games: Extracted human-vs-BOT games.
        per_bot: Maximum games kept per bot.
        seed: Random seed for reproducibility.
    """
    bot = pl.when(pl.col("white_title") == "BOT").then(pl.col("white")).otherwise(pl.col("black"))
    return (
        games.with_columns(bot.alias("_bot"))
        .filter(pl.col("sans").str.len_chars() > 0)
        .sample(fraction=1.0, shuffle=True, seed=seed)
        .filter(pl.int_range(pl.len()).over("_bot") < per_bot)
        .drop("_bot")
    )


def evaluate_sample(
    paths: MonthPaths,
    per_bot: int,
    nodes: int,
    n_workers: int,
    *,
    limit: int | None = None,
    resume: bool = False,
) -> pl.DataFrame:
    """Runs Stockfish over a per-bot stratified sample and stores the evals.

    Args:
        paths: Month (or panel) locations.
        per_bot: Maximum games per bot (a very large value evaluates every game).
        nodes: Stockfish node budget per position.
        n_workers: Parallel engine processes.
        limit: Evaluate at most this many new games in this run.
        resume: Keep existing evals and only add games not evaluated yet.
    """
    sample = stratified_sample(pl.read_parquet(paths.bot_games), per_bot)
    existing = pl.read_parquet(paths.sf_evals) if resume and paths.sf_evals.exists() else None
    if existing is not None:
        sample = sample.join(existing.select("game_id"), on="game_id", how="anti")
    if limit is not None:
        sample = sample.head(limit)
    print(f"evaluating {sample.height} games", flush=True)
    evaluator = StockfishEvaluator(EngineSettings(config.STOCKFISH_PATH, nodes), n_workers)
    evals = evaluator.evaluate(sample.select("game_id", "sans"))
    if existing is not None:
        evals = pl.concat([existing, evals])
    write_parquet_atomic(evals, paths.sf_evals)
    return evals


def score_maia(
    paths: MonthPaths, n_workers: int, limit: int | None = None, resume: bool = False
) -> pl.DataFrame:
    """Scores the moves of the Stockfish-evaluated games with rating-matched Maia networks.

    Args:
        paths: Month (or panel) locations.
        n_workers: Parallel lc0 processes.
        limit: Score at most this many new games in this run.
        resume: Keep existing scores and only add games not scored yet.
    """
    sample_ids = pl.read_parquet(paths.sf_evals, columns=["game_id"])
    existing = pl.read_parquet(paths.maia_evals) if resume and paths.maia_evals.exists() else None
    if existing is not None:
        sample_ids = sample_ids.join(existing.select("game_id"), on="game_id", how="anti")
    games = pl.read_parquet(
        paths.bot_games, columns=["game_id", "sans", "white_elo", "black_elo"]
    ).join(sample_ids, on="game_id", how="semi")
    if limit is not None:
        games = games.head(limit)
    print(f"maia-scoring {games.height} games", flush=True)
    scorer = MaiaScorer(MaiaSettings(config.LC0_PATH, config.MAIA_WEIGHTS_DIR), n_workers)
    scores = scorer.score(games)
    if existing is not None:
        scores = pl.concat([existing, scores], how="diagonal_relaxed")
    write_parquet_atomic(scores, paths.maia_evals)
    return scores


def _with_engine_evals(games: pl.DataFrame, sf_evals_path: Path) -> pl.DataFrame:
    # Lichess %eval exists only for player-requested analyses, so only our own sample is used
    flagged = games.with_columns(pl.col("evals").is_not_null().alias("lichess_analysed"))
    if not sf_evals_path.exists():
        return flagged.with_columns(pl.lit(None, dtype=pl.List(pl.Float32)).alias("evals"))
    sf = pl.read_parquet(sf_evals_path)
    return flagged.drop("evals").join(sf, on="game_id", how="left").rename({"sf_evals": "evals"})


def build_tables(paths: MonthPaths) -> None:
    """Builds the annotated player tables and bot features for one month."""
    activity = activity_by_id(pl.read_parquet(paths.user_activity))

    bot_games = _with_engine_evals(pl.read_parquet(paths.bot_games), paths.sf_evals)
    table = build_player_table(bot_games, Perspective.HUMAN_VS_BOT).join(
        bot_games.select("game_id", "lichess_analysed"), on="game_id", how="left"
    )
    # one spelling per account before sequences are built (some dumps vary the case)
    table = (
        annotate_sequences(canonicalise(table, ["player", "opponent"]))
        .with_columns(pl.col("player").str.to_lowercase().alias("_id"))
        .join(activity, left_on="_id", right_on="id", how="left")
        .drop("_id")
        .with_columns(pl.col("n_human_games").fill_null(0))
    )
    if paths.bot_profiles.exists():
        profiles = pl.read_parquet(paths.bot_profiles)
        if config.CODEBOOK_PATH.exists():
            profiles = apply_codebook(profiles, load_codebook(config.CODEBOOK_PATH))
        profiles = profiles.select(
            pl.col("bot").str.to_lowercase().alias("_id"), "engine_family", "created_at_ms"
        ).unique("_id", keep="first")
        table = (
            table.with_columns(pl.col("opponent").str.to_lowercase().alias("_id"))
            .join(profiles, on="_id", how="left")
            .drop("_id")
            .with_columns(pl.col("engine_family").fill_null("unknown"))
        )
    write_parquet_atomic(table, paths.player_games)
    write_parquet_atomic(aggregate_bot_features(table), paths.bot_features)

    baseline = build_player_table(pl.read_parquet(paths.baseline_games), Perspective.BOTH_SIDES)
    baseline = canonicalise(baseline, ["player", "opponent"])
    write_parquet_atomic(annotate_sequences(baseline), paths.baseline_player_games)
