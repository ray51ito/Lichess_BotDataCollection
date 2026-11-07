"""Data locations, engine binaries and dump URLs shared by every collection stage.

Every location can be moved with an environment variable, so the raw dumps (5-35 GB each)
and the month tables can live on an external drive.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
"""Repository root directory."""

DATA_ROOT: Path = Path(os.environ.get("LBD_DATA_ROOT", PROJECT_ROOT / "data"))
"""Root of all collected data (``LBD_DATA_ROOT`` overrides)."""

RAW_DIR: Path = Path(os.environ.get("LBD_RAW_DIR", DATA_ROOT / "raw"))
"""Downloaded Lichess dumps (``LBD_RAW_DIR`` overrides)."""

INTERIM_DIR: Path = Path(os.environ.get("LBD_INTERIM_DIR", DATA_ROOT / "interim"))
"""One folder of tables per month, plus the stacked panel (``LBD_INTERIM_DIR`` overrides)."""

EXTERNAL_DIR: Path = Path(os.environ.get("LBD_EXTERNAL_DIR", DATA_ROOT / "external"))
"""Data collected from the Lichess API outside the dumps (``LBD_EXTERNAL_DIR`` overrides)."""

TOOLS_DIR: Path = Path(os.environ.get("LBD_TOOLS_DIR", DATA_ROOT / "tools"))
"""Engine binaries and network weights (``LBD_TOOLS_DIR`` overrides)."""

STOCKFISH_PATH: Path = Path(
    os.environ.get(
        "LBD_STOCKFISH", TOOLS_DIR / "stockfish" / "stockfish-windows-x86-64-universal.exe"
    )
)
"""Stockfish executable used for engine evaluations (``LBD_STOCKFISH`` overrides)."""

LC0_PATH: Path = Path(os.environ.get("LBD_LC0", TOOLS_DIR / "lc0" / "lc0.exe"))
"""lc0 executable (CPU build) that runs the Maia networks (``LBD_LC0`` overrides)."""

MAIA_WEIGHTS_DIR: Path = Path(os.environ.get("LBD_MAIA_WEIGHTS", TOOLS_DIR / "maia"))
"""Folder of the Maia-1 weights ``maia-1100.pb.gz`` ... ``maia-1900.pb.gz``."""

CODEBOOK_PATH: Path = PROJECT_ROOT / "codebook" / "bot_codebook.csv"
"""Hand-coded engine families of the most played bots (overrides keyword classification)."""

DUMP_URL_TEMPLATE: str = (
    "https://database.lichess.org/standard/lichess_db_standard_rated_{month}.pgn.zst"
)
"""URL of a monthly standard rated games dump; ``month`` is ``YYYY-MM``."""


def dump_url(month: str) -> str:
    """Returns the dump URL for a ``YYYY-MM`` month."""
    return DUMP_URL_TEMPLATE.format(month=month)


def dump_path(month: str) -> Path:
    """Returns the local path of a downloaded monthly dump."""
    return RAW_DIR / f"lichess_db_standard_rated_{month}.pgn.zst"
