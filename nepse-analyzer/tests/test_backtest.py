import pandas as pd
import pytest

from nepse_ta.analysis import TradePlan, analyze_at, prepare_frame
from nepse_ta.backtest import net_return, simulate_trade, summarize, walk_forward, wilson
from nepse_ta.config import AnalysisConfig, BacktestConfig, CostConfig, DataConfig
from tests.conftest import make_ohlc

NO_COST = CostConfig(commission_pct=0, sebon_fee_pct=0, dp_charge_npr=0, cgt_pct=0, slippage_pct=0)
B = BacktestConfig(min_hold_sessions=3, max_hold_sessions=10)


def bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-01", periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


PLAN = TradePlan(plan_type="breakout", entry_low=100, entry_high=101, entry_ref=100.5, stop=95, target1=110)
FLAT = (100.0, 101.0, 99.0, 100.0)


def test_target_hit():
    df = bars([FLAT, FLAT, FLAT, FLAT, (100, 111, 99, 108), FLAT])
    fields, j = simulate_trade(df, 0, PLAN, B, NO_COST)
    assert fields["exit_reason"] == "target1" and fields["exit_price"] == 110 and j == 4


def test_stop_and_target_same_bar_assumes_stop():
    df = bars([FLAT, FLAT, FLAT, FLAT, (100, 111, 94, 100), FLAT])
    fields, _ = simulate_trade(df, 0, PLAN, B, NO_COST)
    assert fields["exit_reason"] == "stop" and fields["exit_price"] == 95


def test_gap_through_stop_fills_at_open():
    df = bars([FLAT, FLAT, FLAT, FLAT, (90, 92, 88, 91), FLAT])
    fields, _ = simulate_trade(df, 0, PLAN, B, NO_COST)
    assert fields["exit_price"] == 90 and fields["exit_reason"] == "stop"


def test_settlement_lock_ignores_early_stop_if_recovered():
    # stop breached on day 2 (locked), price recovers, then target hit
    df = bars([FLAT, FLAT, (100, 101, 90, 96), FLAT, FLAT, (100, 112, 99, 111), FLAT])
    fields, _ = simulate_trade(df, 0, PLAN, B, NO_COST)
    assert fields["exit_reason"] == "target1"


def test_no_entry_when_open_gaps_above_zone():
    df = bars([FLAT, (105, 106, 104, 105), FLAT])
    assert simulate_trade(df, 0, PLAN, B, NO_COST) is None


def test_time_exit():
    df = bars([FLAT] * 15)
    fields, j = simulate_trade(df, 0, PLAN, B, NO_COST)
    assert fields["exit_reason"] == "time" and j == 1 + B.max_hold_sessions


def test_net_return_costs_and_tax():
    c = CostConfig(commission_pct=0.36, sebon_fee_pct=0.015, dp_charge_npr=25, cgt_pct=7.5, notional_npr=100_000)
    fee = 0.00375
    gross = (110 * (1 - fee) - 100 * 0.00025) / (100 * (1 + fee)) - 1
    assert net_return(100, 110, c) == pytest.approx(gross * 0.925 * 100)
    # losses are not taxed
    loss = (95 * (1 - fee) - 100 * 0.00025) / (100 * (1 + fee)) - 1
    assert net_return(100, 95, c) == pytest.approx(loss * 100)
    assert net_return(100, 100, c) < 0  # round trip at same price loses money


def test_analysis_has_no_lookahead():
    """Changing future bars must not change the analysis at bar t."""
    df = make_ohlc(n=320, seed=11).assign(ohlc_repaired=False)
    t = 250
    a1 = analyze_at(prepare_frame(df, AnalysisConfig()), t, AnalysisConfig(), DataConfig())
    future = df.copy()
    future.iloc[t + 1 :, :4] = future.iloc[t + 1 :, :4] * 3.0
    a2 = analyze_at(prepare_frame(future, AnalysisConfig()), t, AnalysisConfig(), DataConfig())
    assert a1.to_dict() == a2.to_dict()


def test_wilson_interval():
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(40.4, abs=0.1) and hi == pytest.approx(59.6, abs=0.1)


def _trades(rate_by_year: dict[int, float], n: int = 100) -> pd.DataFrame:
    rows = []
    for y, rate in rate_by_year.items():
        for i in range(n):
            hit = i < rate * n
            rows.append(
                {
                    "signal_date": f"{y}-03-01",
                    "exit_date": f"{y}-03-{1 + i % 27:02d}",
                    "bucket": "60-69",
                    "exit_reason": "target1" if hit else "stop",
                    "net_return_pct": 5.0 if hit else -3.0,
                    "r_multiple": 1.5 if hit else -1.0,
                    "sessions_held": 5,
                }
            )
    return pd.DataFrame(rows)


def test_walk_forward_calibrated_when_stable():
    cfg = BacktestConfig(first_test_year=2021, min_bucket_trades=50, min_total_oos_trades=300)
    wf = walk_forward(_trades({2019: 0.4, 2020: 0.4, 2021: 0.42, 2022: 0.38, 2023: 0.41}), cfg)
    assert wf["calibrated"] is True


def test_walk_forward_rejects_unstable_rates():
    cfg = BacktestConfig(first_test_year=2021, min_bucket_trades=50, min_total_oos_trades=300)
    wf = walk_forward(_trades({2019: 0.6, 2020: 0.6, 2021: 0.2, 2022: 0.2, 2023: 0.2}), cfg)
    assert wf["calibrated"] is False


def test_summarize_metrics():
    s = summarize(_trades({2020: 0.5}))
    assert s["trades"] == 100 and s["win_rate_pct"] == 50.0 and s["t1_hit_rate_pct"] == 50.0
    assert s["expectancy_r"] == pytest.approx(0.25)
    assert s["max_drawdown_pct_at_10pct_alloc"] <= 0
