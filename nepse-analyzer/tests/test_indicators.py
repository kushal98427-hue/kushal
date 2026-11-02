import numpy as np
import pandas as pd
import pytest

from nepse_ta.config import AnalysisConfig
from nepse_ta.indicators import add_indicators, atr, confirmed_pivots, ema, macd, rsi, sma, to_weekly, wilder_rma


def _reference_rsi(close: list[float], n: int) -> list[float]:
    """Straightforward textbook Wilder RSI for cross-checking."""
    out = [float("nan")] * len(close)
    gains = [max(close[i] - close[i - 1], 0) for i in range(1, len(close))]
    losses = [max(close[i - 1] - close[i], 0) for i in range(1, len(close))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    out[n] = 100 - 100 / (1 + ag / al)
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out[i + 1] = 100 - 100 / (1 + ag / al)
    return out


def test_sma_and_ema_warmup():
    s = pd.Series(np.arange(1, 11, dtype=float))
    assert sma(s, 3).iloc[2] == pytest.approx(2.0)
    assert sma(s, 3).iloc[:2].isna().all()
    assert ema(s, 3).iloc[:2].isna().all()
    assert ema(pd.Series([5.0] * 10), 3).dropna().eq(5.0).all()


def test_wilder_rma_seed_and_recursion():
    v = np.array([1, 2, 3, 4, 5, 6], dtype=float)
    out = wilder_rma(v, 3)
    assert np.isnan(out[:2]).all()
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx((2.0 * 2 + 4) / 3)


def test_rsi_matches_reference(ohlc):
    close = ohlc["close"]
    ours = rsi(close, 14).to_numpy()
    ref = np.array(_reference_rsi(close.tolist(), 14))
    assert np.isnan(ours[:14]).all()
    np.testing.assert_allclose(ours[14:], ref[14:], rtol=1e-10)


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 40, dtype=float))
    assert rsi(up, 14).iloc[-1] == pytest.approx(100.0)
    flat = pd.Series([10.0] * 30)
    assert rsi(flat, 14).iloc[-1] == pytest.approx(50.0)


def test_macd_zero_on_constant_series():
    m = macd(pd.Series([100.0] * 60))
    assert m.dropna().abs().max().max() == pytest.approx(0.0)


def test_atr_constant_range():
    idx = pd.bdate_range("2025-01-01", periods=30)
    df = pd.DataFrame({"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0}, index=idx)
    assert atr(df, 14).iloc[-1] == pytest.approx(4.0)


def test_atr_uses_gap_from_previous_close():
    idx = pd.bdate_range("2025-01-01", periods=3)
    df = pd.DataFrame({"open": [100, 110, 110], "high": [101, 111, 111], "low": [99, 109, 109], "close": [100, 110, 110]}, index=idx)
    # day 2 true range = max(2, |111-100|, |109-100|) = 11
    assert atr(df, 2).iloc[1] == pytest.approx((2 + 11) / 2)


def test_weekly_resample_keeps_missing_volume_missing():
    idx = pd.date_range("2026-10-04", "2026-10-15", freq="D")  # Sun..Thu, two weeks
    idx = idx[idx.dayofweek.isin([6, 0, 1, 2, 3])]
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": np.nan}, index=idx)
    wk = to_weekly(df)
    assert len(wk) == 2  # Sunday-start weeks end Saturday
    assert wk["volume"].isna().all()


def test_pivots_confirmed_after_window(ohlc):
    piv = confirmed_pivots(ohlc, 5)
    assert not piv.empty
    assert (piv["confirm_pos"] == piv["pos"] + 5).all()


def test_indicators_are_causal(ohlc):
    """Values at bar t must not change when future bars are removed (no look-ahead)."""
    cfg = AnalysisConfig()
    df = ohlc.assign(ohlc_repaired=False)
    full = add_indicators(df, cfg)
    for t in (60, 150, 250):
        part = add_indicators(df.iloc[: t + 1], cfg)
        cols = [c for c in full.columns if c not in df.columns]
        pd.testing.assert_series_equal(full.iloc[t][cols], part.iloc[t][cols], check_names=False)
