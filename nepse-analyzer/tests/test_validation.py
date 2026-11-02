import numpy as np
import pytest

from nepse_ta.config import DataConfig
from nepse_ta.data.validation import prepare_series
from tests.conftest import HEADER, make_ohlc, write_csv

CFG = DataConfig()


def _write(tmp_path, rows: list[str], name: str = "T.csv"):
    p = tmp_path / name
    p.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return p


def test_duplicates_malformed_and_invalid_rows(tmp_path):
    p = _write(
        tmp_path,
        [
            "2025-01-02,100,105,99,104,nan,1000,104000,1",
            "2025-01-01,98,101,97,100,nan,900,90000,1",  # unsorted
            "2025-01-03,104,106,103,105,0.0,1200,126000,1",
            "2025-01-03,104,106,103,105,0.96,1200,126000,1",  # same OHLCV, usable per_change wins
            "2025-01-06,105,107,104,106,0.95",  # malformed (too few columns)
            "2025-01-07,abc,107,104,106,0.95,10,10,1",  # non-numeric
            "2025-01-08,-1,107,104,106,0.95,10,10,1",  # non-positive
            "2025-01-09,106,108,105,107,0.94,0,0,1",  # zero volume -> NaN
            "not-a-date,1,1,1,1,0,1,1,0",
        ],
    )
    s = prepare_series("T", p, CFG)
    q = s.quality
    assert q["malformed_rows"] == 1
    assert q["non_numeric_price_rows"] == 1
    assert q["non_positive_price_rows"] == 1
    assert q["bad_date_rows"] == 1
    assert q["unsorted"] == 1
    assert q["duplicate_date_rows"] == 2
    assert s.df.index.is_monotonic_increasing and s.df.index.is_unique
    assert s.df.loc["2025-01-03", "per_change"] == pytest.approx(0.96)
    assert np.isnan(s.df.loc["2025-01-09", "volume"])  # never silently zero
    assert len(s.df) == 4


def test_conflicting_duplicates_warn(tmp_path):
    p = _write(tmp_path, ["2025-01-01,100,101,99,100,nan,10,10,0", "2025-01-01,100,102,99,101,1,10,10,1"])
    s = prepare_series("T", p, CFG)
    assert s.quality["conflicting_duplicates"] == 1
    assert s.df["close"].iloc[0] == 101
    assert s.warnings


def test_ohlc_inconsistency_repaired_and_flagged(tmp_path):
    p = _write(tmp_path, ["2025-01-01,110,105,100,104,nan,10,10,1"])  # open above high
    s = prepare_series("T", p, CFG)
    row = s.df.iloc[0]
    assert row["high"] == 110 and row["low"] == 100
    assert bool(row["ohlc_repaired"]) and s.quality["ohlc_repaired_rows"] == 1


def _bonus_csv(tmp_path, factor: float):
    """Price series with a bonus issue: raw price drops by ``factor`` but per_change stays small."""
    df = make_ohlc(n=120, drift=0.0, vol=0.005, seed=3)
    cut = 80
    df.iloc[cut:, :4] = df.iloc[cut:, :4] * factor
    p = write_csv(df, tmp_path / "B.csv")
    # rewrite per_change on the event row as NEPSE would (vs adjusted previous close)
    lines = p.read_text().splitlines()
    parts = lines[cut + 1].split(",")
    prev_close = float(lines[cut].split(",")[4])
    parts[5] = f"{(float(parts[4]) / (prev_close * factor) - 1) * 100:.2f}"
    lines[cut + 1] = ",".join(parts)
    p.write_text("\n".join(lines) + "\n")
    return p, df, cut


def test_bonus_adjustment_detected_and_applied(tmp_path):
    factor = 1 / 1.10  # 10% bonus share
    p, df, cut = _bonus_csv(tmp_path, factor)
    s = prepare_series("B", p, CFG)
    assert len(s.adjustments) == 1 and not s.breaks
    assert s.adjustments[0].factor == pytest.approx(factor, rel=2e-3)
    # after adjustment the series is continuous: no move beyond 3% at the event
    jump = s.df["close"].iloc[cut] / s.df["close"].iloc[cut - 1] - 1
    assert abs(jump) < 0.03
    # the latest prices are untouched (they are real market prices)
    assert s.df["close"].iloc[-1] == pytest.approx(round(df["close"].iloc[-1], 2), abs=0.01)


def test_unexplained_break_truncates_live_history(tmp_path):
    df = make_ohlc(n=150, drift=0.0, vol=0.004, seed=5)
    df.iloc[100:, :4] = df.iloc[100:, :4] * 0.6
    p = write_csv(df, tmp_path / "X.csv")
    lines = p.read_text().splitlines()
    parts = lines[101].split(",")
    parts[5] = "nan"  # no usable per_change -> cannot explain the -40% move
    lines[101] = ",".join(parts)
    p.write_text("\n".join(lines) + "\n")
    s = prepare_series("X", p, CFG)
    assert len(s.breaks) == 1
    assert len(s.live) == 50
    assert sum(len(x) for x in s.segments()) == len(s.df)


def test_genuine_large_move_is_not_a_break(tmp_path):
    p = _write(tmp_path, ["2025-01-01,100,101,99,100,nan,10,10,0", "2025-01-02,100,112,100,111,11.0,10,10,1"])
    s = prepare_series("T", p, CFG)
    assert not s.breaks and not s.adjustments
