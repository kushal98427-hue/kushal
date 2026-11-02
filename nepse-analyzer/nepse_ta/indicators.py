"""Technical indicators. Every function is *causal*: the value at row ``t`` uses only rows ``<= t``.

That property is what makes the backtest free of look-ahead bias, and it is
verified by ``tests/test_indicators.py::test_indicators_are_causal``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nepse_ta.config import AnalysisConfig


def sma(s: pd.Series, n: int) -> pd.Series:
    """Simple moving average; NaN until ``n`` observations exist."""
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    """Exponential moving average (span ``n``, recursive form); NaN for the first ``n-1`` rows."""
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder_rma(values: np.ndarray, n: int) -> np.ndarray:
    """Wilder's smoothing: seed with the mean of the first ``n`` values, then ``(prev*(n-1)+x)/n``."""
    out = np.full(len(values), np.nan)
    if len(values) < n:
        return out
    out[n - 1] = np.mean(values[:n])
    for i in range(n, len(values)):
        out[i] = (out[i - 1] * (n - 1) + values[i]) / n
    return out


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI. The first value appears at row ``n`` (needs ``n`` price changes)."""
    delta = close.diff().to_numpy()[1:]
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = wilder_rma(gain, n)
    avg_loss = wilder_rma(loss, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        val = 100.0 - 100.0 / (1.0 + rs)
    val = np.where((avg_loss == 0) & (avg_gain > 0), 100.0, val)
    val = np.where((avg_loss == 0) & (avg_gain == 0), 50.0, val)
    return pd.Series(np.concatenate([[np.nan], val]), index=close.index, name="rsi")


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line, signal line and histogram."""
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig}, index=close.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    """True range; the first row uses high-low."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ATR."""
    return pd.Series(wilder_rma(true_range(df).to_numpy(), n), index=df.index, name="atr")


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily bars to weekly bars.

    NEPSE trades Sunday-Thursday (with some Fridays), so weeks end on Saturday
    (``W-SAT``) to keep each trading week in one bar.
    """
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    wk = df[list(agg)].resample("W-SAT").agg(agg)
    # sum() of an all-NaN week returns 0: restore NaN (missing is not zero).
    vol_count = df["volume"].resample("W-SAT").count()
    wk.loc[vol_count == 0, "volume"] = np.nan
    return wk.dropna(subset=["close"])


def confirmed_pivots(df: pd.DataFrame, w: int) -> pd.DataFrame:
    """Swing highs/lows with a ``w``-bar window on each side.

    A pivot at bar ``i`` is only *known* at bar ``i + w``. The returned frame has
    ``pivot_high``/``pivot_low`` (price at bar i) and ``confirm_pos`` (integer
    position at which it becomes known), so callers can avoid look-ahead.
    """
    hi = df["high"].to_numpy()
    lo = df["low"].to_numpy()
    rows = []
    for i in range(w, len(df) - w):
        win_h = hi[i - w : i + w + 1]
        win_l = lo[i - w : i + w + 1]
        if hi[i] == win_h.max() and np.argmax(win_h) == w:
            rows.append((i, i + w, "high", hi[i]))
        if lo[i] == win_l.min() and np.argmin(win_l) == w:
            rows.append((i, i + w, "low", lo[i]))
    return pd.DataFrame(rows, columns=["pos", "confirm_pos", "kind", "price"])


def add_indicators(df: pd.DataFrame, cfg: AnalysisConfig) -> pd.DataFrame:
    """Return a copy of ``df`` with all daily indicator columns added."""
    out = df.copy()
    for n in cfg.ma_periods:
        out[f"sma{n}"] = sma(out["close"], n)
    out["rsi"] = rsi(out["close"], cfg.rsi_period)
    out = out.join(macd(out["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal))
    out["atr"] = atr(out, cfg.atr_period)
    out["vol_avg"] = out["volume"].shift(1).rolling(cfg.volume_avg_period, min_periods=15).mean()
    out["rel_volume"] = out["volume"] / out["vol_avg"]
    lb = cfg.breakout_lookback
    out["prior_high"] = out["high"].shift(1).rolling(lb, min_periods=lb).max()
    out["prior_low"] = out["low"].shift(1).rolling(lb, min_periods=lb).min()
    out["range_high"] = out["high"].rolling(lb, min_periods=lb).max()
    out["range_low"] = out["low"].rolling(lb, min_periods=lb).min()
    return out
