"""Shared fixtures: synthetic OHLC data written in the exact source CSV format."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HEADER = "published_date,open,high,low,close,per_change,traded_quantity,traded_amount,status"


def make_ohlc(
    n: int = 300,
    start: str = "2025-01-01",
    drift: float = 0.0015,
    vol: float = 0.012,
    seed: int = 7,
    base: float = 500.0,
) -> pd.DataFrame:
    """Random-walk OHLC on business days (deterministic with ``seed``)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    rets = drift + vol * rng.standard_normal(n)
    close = base * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[base], close[:-1]]) * (1 + 0.002 * rng.standard_normal(n))
    high = np.maximum(open_, close) * (1 + np.abs(0.006 * rng.standard_normal(n)))
    low = np.minimum(open_, close) * (1 - np.abs(0.006 * rng.standard_normal(n)))
    volume = rng.integers(20_000, 60_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume, "turnover": volume * close},
        index=pd.DatetimeIndex(dates, name="date"),
    )


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    """Write ``df`` in the source repository's CSV format (per_change vs previous close)."""
    pc = (df["close"].pct_change() * 100).round(2)
    lines = [HEADER]
    for (d, r), p in zip(df.iterrows(), pc, strict=False):
        pcs = "nan" if pd.isna(p) else f"{p}"
        status = 1 if r.close > r.open else -1 if r.close < r.open else 0
        lines.append(
            f"{d:%Y-%m-%d},{r.open:.2f},{r.high:.2f},{r.low:.2f},{r.close:.2f},{pcs},{r.volume:.1f},{r.turnover:.1f},{status}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def ohlc() -> pd.DataFrame:
    return make_ohlc()
