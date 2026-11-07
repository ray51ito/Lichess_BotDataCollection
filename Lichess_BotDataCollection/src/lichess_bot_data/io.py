"""Crash-safe file writing shared by the pipeline stages."""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl


def write_parquet_atomic(frame: pl.DataFrame, path: Path) -> None:
    """Writes ``frame`` to ``path`` so that a crash leaves the old file or none, never a torn one.

    Args:
        frame: Table to write.
        path: Destination Parquet file.
    """
    tmp = path.with_suffix(".tmp")
    frame.write_parquet(tmp)
    os.replace(tmp, path)
