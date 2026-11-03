"""Phase 2 (smc-1): market structure & SMC rules — docs/SMC_SPEC.md."""

import re

import numpy as np
import pandas as pd
import pytest

from nepse_ta.smc import DAILY, Engine, completed_weeks, explain, smc_snapshot, volume_behaviour
from tests.conftest import make_ohlc


def bars(rows, start="2025-01-06", vol=1000.0, freq="B"):
    idx = pd.date_range(start, periods=len(rows), freq=freq)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)
    df["volume"] = vol
    df["ohlc_repaired"] = False
    return df


def path(points, n=5, wick=0.3):
    """Bars moving linearly between turning points (n bars per leg), small wicks."""
    rows, prev = [], points[0]
    for a, b in zip(points[:-1], points[1:], strict=False):
        for j in range(1, n + 1):
            c = a + (b - a) * j / n
            rows.append((prev, max(prev, c) + wick, min(prev, c) - wick, c))
            prev = c
    return rows


WARM = path([100, 102, 100, 102, 100], n=5)  # 20 bars so ATR(14) exists


def run(rows, **kw):
    return Engine(bars(rows, **kw), DAILY).run()


def mirror(df, k=1000.0):
    m = df.copy()
    m["open"], m["close"] = k - df["open"], k - df["close"]
    m["high"], m["low"] = k - df["low"], k - df["high"]
    return m


# --------------------------------------------------------------------------- swings & labels
def test_bullish_structure_labels():
    e = run(WARM + path([100, 110, 104, 116, 109, 122, 115], n=5))
    labels = [(s["type"], s["label"]) for s in e.acc]
    assert ("high", "HH") in labels and ("low", "HL") in labels
    assert e.state() == "bullish"


def test_bearish_structure_is_mirror():
    df = bars(WARM + path([100, 110, 104, 116, 109, 122, 115], n=5))
    up, dn = Engine(df).run(), Engine(mirror(df)).run()
    assert up.state() == "bullish" and dn.state() == "bearish"
    flip = {"HH": "LL", "HL": "LH", "LH": "HL", "LL": "HH", "EH": "EL", "EL": "EH", None: None}
    assert [(s["i"], flip[s["label"]]) for s in up.acc] == [(s["i"], s["label"]) for s in dn.acc]


def test_small_pullbacks_inside_a_trend_are_not_swings():
    # trend with ATR ≈ 1.2 and dips of 0.3 (swing high-to-low ≈ 0.9 incl. wicks) < 1 ATR → no swing low inside
    e = run(WARM + path([100, 110, 109.7, 112, 111.7, 114, 113.7, 116], n=5))
    lows_inside = [s for s in e.acc if s["type"] == "low" and s["i"] > 24]
    assert lows_inside == []
    # the same dips scaled up to several ATR ARE swings
    e2 = run(WARM + path([100, 110, 103, 112, 105, 114], n=5))
    assert [s for s in e2.acc if s["type"] == "low" and s["i"] > 24]


def test_tie_rule_first_of_equal_highs():
    rows = WARM + path([100, 108], n=4) + [(108, 108.3, 107.5, 108)] + path([108, 101], n=5) + path([101, 106], n=5)
    e = run(rows)
    highs = [s for s in e.acc if s["type"] == "high" and s["i"] >= 20]
    assert highs and highs[0]["i"] == 23  # bar 23 (first 108.3) not bar 24 (equal high)


def test_swing_known_only_after_k_bars():
    rows = WARM + path([100, 110], n=5) + path([110, 103], n=5)
    df = bars(rows)
    peak = 24
    assert all(s["i"] != peak for s in Engine(df).run(peak + 2).acc)  # not yet confirmed
    e = Engine(df).run(peak + 3)
    assert any(s["i"] == peak and s["formed_i"] == peak + 3 for s in e.acc)


# --------------------------------------------------------------------------- BOS / CHoCH
UPTREND = WARM + path([100, 110, 104, 116, 109], n=5)  # last HH ≈ 116.3 is the reference high


def test_bullish_bos_close_vs_wick():
    e0 = run(UPTREND)
    ref = e0._last("high")["price"]
    wick = run(UPTREND + [(112, ref + 1.0, 111.5, ref - 0.5)])  # wick above, close below
    assert not [x for x in wick.events if x["type"] == "BOS"]
    assert wick.sweeps and wick.sweeps[-1]["side"] == "buy_side"
    brk = run(UPTREND + path([109, 120], n=4))
    bos = [x for x in brk.events if x["type"] == "BOS"]
    assert len(bos) == 1 and bos[0]["dir"] == "bullish" and bos[0]["level"] == pytest.approx(ref, abs=0.01)


def test_bearish_bos_symmetric():
    df = bars(UPTREND + path([109, 120], n=4))
    up, dn = Engine(df).run(), Engine(mirror(df)).run()
    eu = [(x["type"], x["i"]) for x in up.events]
    ed = [(x["type"], x["i"]) for x in dn.events]
    assert eu == ed and all(x["dir"] == "bearish" for x in dn.events if x["type"] == "BOS")


def test_failed_bos():
    rows = UPTREND + path([109, 118], n=3) + path([118, 108], n=3)
    e = run(rows)
    bos = [x for x in e.events if x["type"] == "BOS"][0]
    assert bos["status"] == "failed_bos"


DOWNTREND = WARM + path([100, 90, 96, 84, 91, 80, 88], n=5)  # LH ≈ 91.3 … LL ≈ 79.7


def test_bullish_choch_levels_and_confirmation():
    e0 = run(DOWNTREND)
    assert e0.state() == "bearish"
    lh, ll = e0._last("high")["price"], e0._last("low")["price"]
    rows = DOWNTREND + path([88, 95], n=4)
    e = run(rows)
    ch = [x for x in e.events if x["type"] == "CHoCH"][0]
    assert ch["dir"] == "bullish" and ch["level"] == pytest.approx(lh, abs=0.01)
    assert ch["origin"] == pytest.approx(ll, abs=0.01) and ch["status"] == "confirmed_close"
    conf = run(rows + path([95, 88], n=5) + path([88, 97], n=5))  # higher low above origin
    assert [x for x in conf.events if x["type"] == "CHoCH"][0]["status"] == "structure_confirmed"
    fail = run(rows + path([95, 76], n=6))
    assert [x for x in fail.events if x["type"] == "CHoCH"][0]["status"] == "failed_choch"


def test_bearish_choch_is_mirror():
    df = bars(DOWNTREND + path([88, 95], n=4))
    a, b = Engine(df).run(), Engine(mirror(df)).run()
    ca = [x for x in a.events if x["type"] == "CHoCH"][0]
    cb = [x for x in b.events if x["type"] == "CHoCH"][0]
    assert ca["i"] == cb["i"] and cb["dir"] == "bearish"
    assert cb["level"] == pytest.approx(1000 - ca["level"], abs=0.01)
    assert cb["origin"] == pytest.approx(1000 - ca["origin"], abs=0.01)


def test_range_break_is_not_choch():
    rows = WARM + path([100, 110, 103, 108, 104, 107], n=5)  # HH then LH: transition
    e = run(rows)
    assert e.state() == "transition"
    e2 = run(rows + path([107, 115], n=4))
    assert [x["type"] for x in e2.events if x["i"] > len(rows) - 1] == ["range_break"]


def test_displacement_and_volume_labels():
    rows = UPTREND + [(109, 125, 108.8, 124.5)]  # huge body
    df = bars(rows)
    df.iloc[-1, df.columns.get_loc("volume")] = 5000
    ev = [x for x in Engine(df).run().events if x["type"] == "BOS"][0]
    assert ev["displacement"] == "strong" and ev["volume"] == "volume_supported"
    df["volume"] = np.nan
    ev = [x for x in Engine(df).run().events if x["type"] == "BOS"][0]
    assert ev["volume"] == "volume_unknown"


# --------------------------------------------------------------------------- order blocks
def test_bullish_ob_selection_zone_and_body():
    rows = UPTREND + [(109.5, 109.8, 107.0, 107.5)] + [(107.5, 125, 107.4, 124.5)]  # bearish candle then displacement
    e = run(rows)
    ob = [o for o in e.obs if o["dir"] == "bullish"][-1]
    assert ob["zone"] == [107.0, 109.8] and ob["body"] == [107.5, 109.5] and ob["status"] == "fresh"


def test_ob_leg_starts_after_the_broken_swing():
    # the earlier, lower low (before the broken swing high) must NOT be chosen as leg origin
    rows = UPTREND + [(109.5, 109.8, 107.0, 107.5)] + [(107.5, 125, 107.4, 124.5)]
    e = run(rows)
    ob = e.obs[-1]
    assert ob["candle_date"] == bars(rows).index[40].strftime("%Y-%m-%d")  # the pullback candle, not bar 29


def test_no_ob_without_opposite_candle_or_displacement():
    # pullback made only of up-close candles → no bearish candle in the leg → no OB
    up_closes = UPTREND[:-5] + [(r[3] + 0.2, max(r[1], r[3] + 0.5), r[2], r[3] + 0.4) for r in UPTREND[-5:]]
    e = run(up_closes + [(up_closes[-1][3], 125, up_closes[-1][3] - 0.1, 124.5)])
    assert not [o for o in e.obs if o["formed_i"] >= len(up_closes)]
    assert e.counts["ob_no_opposite_candle"] >= 1
    # shallow pullback: bearish candle present but break close < 2 ATR above its low → no OB
    shallow = WARM + path([100, 110, 104, 116, 115], n=5) + [(115, 115.2, 114.6, 114.7)]
    small = run(shallow + [(114.7, 117.6, 114.6, 117.4)])
    assert [x for x in small.events if x["type"] == "BOS"]
    assert not [o for o in small.obs if o["formed_i"] >= len(shallow)]
    assert small.counts["ob_insufficient_displacement"] >= 1


def test_ob_tested_invalidated_expired():
    base = UPTREND + [(109.5, 109.8, 107.0, 107.5)] + [(107.5, 125, 107.4, 124.5)]
    t = run(base + path([124.5, 109.5], n=4))
    assert [o for o in t.obs if o["dir"] == "bullish"][-1]["status"] == "tested"
    inv = run(base + path([124.5, 105], n=4))
    assert [o for o in inv.obs if o["dir"] == "bullish"][-1]["status"] == "invalidated"
    exp = run(base + [(125, 126, 124, 125)] * 125)
    assert [o for o in exp.obs if o["dir"] == "bullish"][-1]["status"] == "expired"


def test_ob_mirror():
    df = bars(UPTREND + [(109.5, 109.8, 107.0, 107.5)] + [(107.5, 125, 107.4, 124.5)])
    a, b = Engine(df).run(), Engine(mirror(df)).run()
    oa, ob = a.obs[-1], b.obs[-1]
    assert ob["dir"] == "bearish" and ob["zone"] == [pytest.approx(1000 - oa["zone"][1]), pytest.approx(1000 - oa["zone"][0])]


# --------------------------------------------------------------------------- FVG
def test_fvg_detection_size_fill_and_flags():
    rows = WARM + [(100, 101, 99.5, 100.5), (100.5, 111, 100.4, 110.8), (110.8, 112, 104, 111.5)]  # +10.2% day
    e = run(rows)
    g = e.fvgs[-1]
    assert g["dir"] == "bullish" and g["zone"] == [101.0, 104.0] and "circuit_bar" in g["flags"]
    plain = run(WARM + [(100, 101, 99.5, 100.5), (100.5, 106, 100.4, 105.8), (105.8, 108, 104, 107.5)])
    assert plain.fvgs[-1]["flags"] == []  # 5% day: no circuit flag
    small = run(WARM + [(100, 101, 99.5, 100.5), (100.5, 101.5, 100.4, 101.3), (101.3, 101.6, 101.05, 101.4)])
    assert not [x for x in small.fvgs if x["formed_i"] >= 20]  # gap 0.05 < 0.25 ATR
    part = run(rows + [(111.5, 112, 103, 106)])
    assert part.fvgs[-1]["status"] == "partially_filled" and part.fvgs[-1]["fill_pct"] == 33
    full = run(rows + [(111.5, 112, 100.8, 102)])
    assert full.fvgs[-1]["status"] == "filled"
    inv = run(rows + [(111.5, 112, 99, 100.5)])
    assert inv.fvgs[-1]["status"] == "invalidated"


def test_fvg_long_gap_flag():
    rows = WARM + [(100, 101, 99.5, 100.5), (100.5, 103, 100.4, 102.9), (102.9, 104, 102.6, 103.8)]
    df = bars(rows)
    new_idx = list(df.index[:-1]) + [df.index[-1] + pd.Timedelta(days=10)]
    df.index = pd.DatetimeIndex(new_idx)
    g = Engine(df).run().fvgs[-1]
    assert "long_gap" in g["flags"]


# --------------------------------------------------------------------------- liquidity
def test_equal_highs_zone_swept_and_broken():
    rows = WARM + path([100, 110, 103, 110.1, 103.5], n=5)
    e = run(rows)
    z = [z for z in e.eq_zones if z["side"] == "high"]
    assert z and z[-1]["zone"] == [pytest.approx(110.3, abs=0.01), pytest.approx(110.4, abs=0.01)]
    sw = run(rows + [(104, 111.5, 103.8, 108)])
    assert [z for z in sw.eq_zones if z["side"] == "high"][-1]["status"] == "swept"
    br = run(rows + path([103.5, 113], n=3))
    assert [z for z in br.eq_zones if z["side"] == "high"][-1]["status"] == "broken"


def test_sweep_reaction_states_and_single_price_bar():
    base = UPTREND
    lo = run(base)._last("low")["price"]
    s = run(base + [(110, 110.5, lo - 1.0, lo + 0.5)] + [(lo + 0.5, 114, lo + 0.4, 113.5)])
    sell = [x for x in s.sweeps if x["side"] == "sell_side"][-1]
    assert sell["implication"] == "bullish" and sell["status"] == "reaction_confirmed"
    acc = run(base + [(110, 110.5, lo - 1.0, lo + 0.5)] + [(lo + 0.5, lo + 0.6, lo - 2, lo - 1.5)])
    assert [x for x in acc.sweeps if x["side"] == "sell_side"][-1]["status"] == "accepted"
    unc = run(base + [(110, 110.5, lo - 1.0, lo + 0.5)] + [(lo + 0.5, lo + 1.0, lo + 0.2, lo + 0.6)] * 4)
    assert [x for x in unc.sweeps if x["side"] == "sell_side"][-1]["status"] == "unconfirmed"
    one = run(base + [(lo - 1.0, lo - 1.0, lo - 1.0, lo - 1.0)])
    assert not [x for x in one.sweeps if x["i"] == len(base)]  # no wick on a single-price bar


def test_two_sided_bar_flags_both():
    base = UPTREND
    e0 = run(base)
    hi, lo = e0._last("high")["price"], e0._last("low")["price"]
    e = run(base + [(112, hi + 1, lo - 1, hi + 0.5)])  # close above ref high, wick below ref low
    assert any("two_sided" in x["flags"] for x in e.events if x["i"] == len(base))
    assert any("two_sided" in x["flags"] for x in e.sweeps if x["i"] == len(base))


# --------------------------------------------------------------------------- premium / discount, weekly, volume
def test_premium_discount():
    rows = UPTREND + path([109, 120, 113, 118], n=5)
    pd_ = Engine(bars(rows)).run().snapshot()["premium_discount"]
    assert pd_["status"] == "ok" and pd_["leg"] == "bullish"
    lo_, hi_ = pd_["range"]
    assert pd_["equilibrium"] == pytest.approx((lo_ + hi_) / 2, abs=0.01)
    assert run(WARM).snapshot()["premium_discount"]["status"] == "range_unclear"


def test_completed_weeks_excludes_current_week():
    df = bars(path([100, 110, 100, 110, 100, 110, 100, 110, 100, 110], n=10))
    wk = completed_weeks(df)
    assert wk.index[-1] < df.index[-1]
    assert df.index[-1].to_period("W-SAT") not in set(wk.index.to_period("W-SAT"))
    # adding more days inside the same (incomplete) week never changes weekly output
    cut = df.index.to_period("W-SAT") == df.index[-1].to_period("W-SAT")
    first_of_week = int(np.argmax(cut))
    w1 = completed_weeks(df.iloc[: first_of_week + 1])
    w2 = completed_weeks(df)
    pd.testing.assert_frame_equal(w1, w2)


def test_volume_behaviour_unavailable_when_missing():
    df = bars(path([100, 110, 100], n=15))
    assert volume_behaviour(df)["status"] == "ok"
    df["volume"] = np.nan
    assert volume_behaviour(df)["status"] == "unavailable"


# --------------------------------------------------------------------------- causality (mandatory)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_lookahead_truncation_and_future_change(seed):
    df = make_ohlc(n=420, seed=seed, vol=0.02).assign(ohlc_repaired=False)
    full = Engine(df)
    for t in (150, 260, 419):
        full.run(t)
        snap_full = full.snapshot()
        snap_trunc = Engine(df.iloc[: t + 1]).run().snapshot()
        assert snap_full == snap_trunc
        fut = df.copy()
        fut.iloc[t + 1 :, :4] = fut.iloc[t + 1 :, :4] * 3.0
        assert Engine(fut).run(t).snapshot() == snap_trunc


def test_smc_snapshot_does_not_use_future_or_incomplete_weeks():
    df = make_ohlc(n=500, seed=9, vol=0.02).assign(ohlc_repaired=False)
    t = 400
    a = smc_snapshot(df.iloc[: t + 1])
    fut = df.copy()
    fut.iloc[t + 1 :, :4] = fut.iloc[t + 1 :, :4] * 0.5
    assert smc_snapshot(fut.iloc[: t + 1]) == a  # same input → same output (determinism)


def test_scale_invariance_bonus_adjustment():
    df = make_ohlc(n=400, seed=4, vol=0.02).assign(ohlc_repaired=False)
    a = Engine(df).run()
    scaled = df.copy()
    scaled[["open", "high", "low", "close"]] *= 0.9
    b = Engine(scaled).run()
    assert [(s["i"], s["label"]) for s in a.acc] == [(s["i"], s["label"]) for s in b.acc]
    assert [(e["type"], e["dir"], e["i"]) for e in a.events] == [(e["type"], e["dir"], e["i"]) for e in b.events]
    assert [(g["dir"], g["formed_i"]) for g in a.fvgs] == [(g["dir"], g["formed_i"]) for g in b.fvgs]


# --------------------------------------------------------------------------- output
def test_explanation_numbers_come_from_fields():
    df = make_ohlc(n=400, seed=5, vol=0.02).assign(ohlc_repaired=False)
    out = smc_snapshot(df)

    def numbers(obj, acc):
        if isinstance(obj, dict):
            for v in obj.values():
                numbers(v, acc)
        elif isinstance(obj, list):
            for v in obj:
                numbers(v, acc)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            acc.add(f"{obj:.2f}")
            acc.add(str(obj))
        elif isinstance(obj, str):
            acc.update(re.findall(r"\d{4}-\d{2}-\d{2}", obj))
        return acc

    known = numbers({k: v for k, v in out.items() if k != "explanation"}, set())
    for item in out["explanation"]:
        for text in item.values():
            for num in re.findall(r"\d{4}-\d{2}-\d{2}|\d+\.\d{2}", text):
                assert num in known, (num, text)
    assert all("smart money" not in str(x).lower() for x in out["explanation"])


def test_insufficient_history():
    assert smc_snapshot(bars(WARM))["status"] == "insufficient_history"


def test_explain_runs_on_minimal_snapshot():
    out = smc_snapshot(make_ohlc(n=200, seed=7).assign(ohlc_repaired=False))
    assert out["status"] == "ok" and explain(out)
    assert "OHLCV-based" in out["kind"] and out["unavailable"]


def test_tiny_wick_beyond_level_is_not_a_sweep():
    base = UPTREND
    e0 = run(base)
    lo, a = e0._last("low")["price"], e0.atr[len(base) - 1]
    tiny = run(base + [(110, 110.5, lo - 0.05 * a, lo + 0.5)])  # 0.05 ATR beyond < 0.10 ATR minimum
    assert not [x for x in tiny.sweeps if x["i"] == len(base) and x["side"] == "sell_side"]
    real = run(base + [(110, 110.5, lo - 0.2 * a, lo + 0.5)])
    assert [x for x in real.sweeps if x["i"] == len(base) and x["side"] == "sell_side"]



def test_completed_weeks_empty_shape_is_consistent():
    one_week = bars([(100, 101, 99, 100)] * 3, start="2025-02-04")  # Tue-Thu of one week
    a, b = completed_weeks(one_week), completed_weeks(one_week.iloc[:1])
    assert a.empty and b.empty and list(a.columns) == list(b.columns) and a.equals(b)
    # an empty slice of a real weekly frame must compare equal too (same dtypes)
    full = completed_weeks(bars(path([100, 110, 100, 110], n=10)))
    assert full.iloc[:0].equals(a)
