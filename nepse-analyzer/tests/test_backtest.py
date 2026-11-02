import pandas as pd
import pytest

from nepse_ta.analysis import TradePlan, analyze_at, prepare_frame
from nepse_ta.audit import simulate_portfolio
from nepse_ta.backtest import max_drawdown_r, net_return, simulate_trade, summarize, walk_forward, wilson
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
                    "signal_date": f"{y}-{1 + i % 12:02d}-01",
                    "entry_date": f"{y}-{1 + i % 12:02d}-02",
                    "exit_date": f"{y}-{1 + i % 12:02d}-{3 + i % 25:02d}",
                    "risk_pct": 2.0,
                    "calendar_days_held": 7,
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
    assert s["max_drawdown_r"] <= 0
    assert s["avg_win_pct"] == 5.0 and s["avg_loss_pct"] == -3.0
    lo, hi = s["expectancy_r_ci95_monthly_bootstrap"]
    assert lo <= 0.25 <= hi


def test_lower_circuit_lock_defers_exit():
    # day 3: locked at lower circuit (single price, -10%) -> cannot sell; exit next day at open
    locked = (90.0, 90.0, 90.0, 90.0)
    df = bars([FLAT, FLAT, FLAT, FLAT, locked, (85, 86, 84, 85), FLAT])  # entry bar 1, first sell bar 4
    fields, j = simulate_trade(df, 0, PLAN, B, NO_COST)
    assert j == 5 and fields["exit_price"] == 85 and fields["exit_reason"] == "stop"
    off = BacktestConfig(min_hold_sessions=3, max_hold_sessions=10, model_circuit_locks=False)
    fields2, j2 = simulate_trade(df, 0, PLAN, off, NO_COST)
    assert j2 == 4 and fields2["exit_price"] == 90


def test_upper_circuit_locked_entry_is_skipped():
    plan = TradePlan(plan_type="breakout", entry_low=100, entry_high=110, entry_ref=105, stop=95, target1=130)
    df = bars([FLAT, (110.0, 110.0, 110.0, 110.0), FLAT])
    assert simulate_trade(df, 0, plan, B, NO_COST) is None


def test_stale_entry_after_trading_gap_is_skipped():
    idx = pd.DatetimeIndex(["2025-01-01", "2025-01-20", "2025-01-21", "2025-01-22", "2025-01-23"])
    df = pd.DataFrame([FLAT] * 5, columns=["open", "high", "low", "close"], index=idx)
    assert simulate_trade(df, 0, PLAN, B, NO_COST) is None


def test_data_break_is_counted_but_open_is_not():
    df = bars([FLAT] * 4)
    f_open, _ = simulate_trade(df, 0, PLAN, B, NO_COST, segment_is_last=True)
    f_brk, _ = simulate_trade(df, 0, PLAN, B, NO_COST, segment_is_last=False)
    assert f_open["exit_reason"] == "open" and f_brk["exit_reason"] == "data_break"


def test_raw_gross_net_ordering_with_costs():
    df = bars([FLAT, FLAT, FLAT, FLAT, (100, 111, 99, 108), FLAT])
    f, _ = simulate_trade(df, 0, PLAN, B, CostConfig())
    assert f["raw_return_pct"] > f["gross_return_pct"] > f["net_return_pct"]
    assert f["r_multiple"] == pytest.approx(f["net_return_pct"] / f["risk_pct"], abs=1e-3)


def test_max_drawdown_r():
    t = pd.DataFrame({"exit_date": ["a", "b", "c", "d"], "entry_date": ["a"] * 4, "r_multiple": [1.0, -1.0, -1.5, 2.0]})
    assert max_drawdown_r(t) == -2.5


def test_portfolio_respects_slots():
    rows = []
    for i in range(5):  # five simultaneous signals, 2 slots -> 3 skipped
        rows.append(
            {
                "entry_date": "2025-01-02", "exit_date": "2025-01-06", "exit_reason": "target1",
                "score": 50 + i, "net_return_pct": 10.0,
                "_path": [("2025-01-02", 1.0), ("2025-01-03", 1.05), ("2025-01-06", 1.1)],
            }
        )
    res = simulate_portfolio(pd.DataFrame(rows), NO_COST, slots=2)
    assert res["trades_taken"] == 2 and res["signals_skipped_no_capital"] == 3
    assert res["total_return_pct"] == pytest.approx(10.0)
