"""Historical backtest and walk-forward calibration of the setup score.

Rules (identical to the live scanner, because both call ``analyze_at``):

* **Signal**: bar ``t`` where ``analyze_at`` returns a ``breakout`` or ``pullback``
  plan, using only data ``<= t`` (indicators are causal; pivots are used only
  after confirmation).
* **Entry**: next session's open, plus slippage. Skipped if the open gaps more
  than ``max_entry_gap_pct`` above the entry zone or opens at/below the stop.
* **Settlement lock**: NEPSE settles T+2, so no exit is possible for the first
  ``min_hold_sessions`` sessions. If the stop was breached while locked, the
  trade exits at the first allowed open if it is still below the stop.
* **Exit**: stop-loss or Target 1, whichever is touched first. If both are
  inside one bar's range, the *stop* is assumed first (conservative). Gaps
  through a level fill at the open. Time exit at the close after
  ``max_hold_sessions``.
* **Costs**: commission + SEBON fee per side, DP charge on sell, slippage on
  both fills, capital-gains tax on profitable trades.
* **One position per stock at a time** (no overlapping trades on one symbol).

Walk-forward: for each test year Y >= ``first_test_year``, the score buckets'
Target-1 hit rate measured on all years < Y (in-sample) is compared with the
hit rate in Y (out-of-sample). Only if the out-of-sample error is small and the
sample is large is the result marked ``calibrated``. Even then the report calls
it a *historical hit rate*, not a probability.
"""

from __future__ import annotations

import json
import logging
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from nepse_ta.analysis import SETUP_TYPES, TradePlan, analyze_at, prepare_frame
from nepse_ta.config import DEFAULT_SETTINGS, BacktestConfig, CostConfig, Settings
from nepse_ta.data.validation import prepare_series
from nepse_ta.scoring import score_bucket

log = logging.getLogger(__name__)
BUCKETS = ("0-39", "40-49", "50-59", "60-69", "70-100")


@dataclass
class Trade:
    """One simulated trade."""

    symbol: str
    setup_type: str
    signal_date: str
    entry_date: str
    exit_date: str
    score: int
    bucket: str
    rr1: float
    eligible_rule: bool
    entry_price: float
    stop: float
    target1: float
    exit_price: float
    exit_reason: str  # target1 | stop | time | end_of_data
    sessions_held: int
    gross_return_pct: float
    net_return_pct: float
    r_multiple: float

    @property
    def hit_t1(self) -> bool:
        return self.exit_reason == "target1"


def net_return(entry_px: float, exit_px: float, costs: CostConfig) -> float:
    """Net % return after fees and capital-gains tax (slippage already in the prices)."""
    fee = (costs.commission_pct + costs.sebon_fee_pct) / 100
    dp = costs.dp_charge_npr / costs.notional_npr
    cost_basis = entry_px * (1 + fee)
    proceeds = exit_px * (1 - fee) - entry_px * dp
    ret = proceeds / cost_basis - 1
    if ret > 0:
        ret *= 1 - costs.cgt_pct / 100
    return ret * 100


def simulate_trade(
    ind: pd.DataFrame, t: int, plan: TradePlan, bcfg: BacktestConfig, costs: CostConfig
) -> tuple[dict, int] | None:
    """Simulate a trade signalled at bar ``t``. Returns (fields, exit_index) or None if not entered."""
    e = t + 1
    n = len(ind)
    if e >= n or plan.stop is None or plan.target1 is None or plan.entry_high is None:
        return None
    o = ind["open"].to_numpy()
    h = ind["high"].to_numpy()
    lo = ind["low"].to_numpy()
    c = ind["close"].to_numpy()
    stop, t1 = float(plan.stop), float(plan.target1)
    if o[e] > plan.entry_high * (1 + bcfg.max_entry_gap_pct / 100) or o[e] <= stop or o[e] >= t1:
        return None
    slip = costs.slippage_pct / 100
    entry_px = o[e] * (1 + slip)
    exit_raw, reason, j_exit = None, "end_of_data", n - 1
    last = min(e + bcfg.max_hold_sessions, n - 1)
    for j in range(e + bcfg.min_hold_sessions, last + 1):
        if o[j] <= stop:
            exit_raw, reason = o[j], "stop"
        elif o[j] >= t1:
            exit_raw, reason = o[j], "target1"
        elif lo[j] <= stop:
            exit_raw, reason = stop, "stop"
        elif h[j] >= t1:
            exit_raw, reason = t1, "target1"
        if exit_raw is not None:
            j_exit = j
            break
    if exit_raw is None:
        if e + bcfg.max_hold_sessions <= n - 1:
            j_exit, exit_raw, reason = last, c[last], "time"
        else:
            j_exit, exit_raw, reason = n - 1, c[n - 1], "end_of_data"
    exit_px = exit_raw * (1 - slip)
    net = net_return(entry_px, exit_px, costs)
    risk_pct = (entry_px - stop) / entry_px * 100
    fields = {
        "entry_date": ind.index[e].strftime("%Y-%m-%d"),
        "exit_date": ind.index[j_exit].strftime("%Y-%m-%d"),
        "entry_price": round(entry_px, 2),
        "exit_price": round(exit_px, 2),
        "exit_reason": reason,
        "sessions_held": j_exit - e,
        "gross_return_pct": round((exit_px / entry_px - 1) * 100, 3),
        "net_return_pct": round(net, 3),
        "r_multiple": round(net / risk_pct, 3) if risk_pct > 0 else 0.0,
    }
    return fields, j_exit


def _candidates(ind: pd.DataFrame, start: pd.Timestamp) -> np.ndarray:
    """Cheap vectorised pre-filter; ``analyze_at`` makes the real decision."""
    breakout = ind["close"] > ind["prior_high"]
    uptrendish = (ind["close"] > ind["sma50"]) & (ind["sma20"] > ind["sma50"]) & ind["rsi"].between(40, 60)
    mask = (breakout | uptrendish) & (ind.index >= start)
    return np.flatnonzero(mask.to_numpy())


def backtest_symbol(args: tuple[str, str, Settings]) -> list[dict]:
    """Backtest one CSV (runs in a worker process)."""
    symbol, path, settings = args
    out: list[dict] = []
    try:
        series = prepare_series(symbol, Path(path), settings.data)
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
        log.warning("%s: skipped (%s)", symbol, exc)
        return out
    start = pd.Timestamp(settings.backtest.start_date)
    a_cfg, d_cfg = settings.analysis, settings.data
    for seg in series.segments():
        if len(seg) < d_cfg.min_history + 2 or seg.index[-1] < start:
            continue
        frame = prepare_frame(seg, a_cfg)
        busy_until = -1
        for t in _candidates(frame.ind, start):
            if t <= busy_until or t + 1 < d_cfg.min_history:
                continue
            a = analyze_at(frame, int(t), a_cfg, d_cfg, symbol, with_text=False)
            if a is None or a.plan.plan_type not in SETUP_TYPES or a.plan.rr1 is None:
                continue
            res = simulate_trade(frame.ind, int(t), a.plan, settings.backtest, settings.costs)
            if res is None:
                continue
            fields, j_exit = res
            busy_until = j_exit
            eligible = a.plan.rr1 >= a_cfg.min_rr_for_valid_setup and a.score >= a_cfg.min_score_for_master and not a.low_liquidity
            out.append(
                asdict(
                    Trade(
                        symbol=symbol,
                        setup_type=a.plan.plan_type,
                        signal_date=a.date,
                        score=a.score,
                        bucket=score_bucket(a.score),
                        rr1=float(a.plan.rr1),
                        eligible_rule=bool(eligible),
                        stop=float(a.plan.stop),  # type: ignore[arg-type]
                        target1=float(a.plan.target1),  # type: ignore[arg-type]
                        **fields,
                    )
                )
            )
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion (in %)."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(100 * (centre - half), 1), round(100 * (centre + half), 1))


def summarize(trades: pd.DataFrame, alloc: float = 0.10) -> dict:
    """Win rate, T1 hit rate, expectancy, profit factor, max drawdown, sample size."""
    closed = trades[trades["exit_reason"] != "end_of_data"] if len(trades) else trades
    n = len(closed)
    if n == 0:
        return {"trades": 0}
    net = closed["net_return_pct"]
    wins, losses = net[net > 0], net[net <= 0]
    hits = int((closed["exit_reason"] == "target1").sum())
    eq = (1 + alloc * closed.sort_values("exit_date")["net_return_pct"] / 100).cumprod()
    dd = float((eq / eq.cummax() - 1).min() * 100)
    pf = float(wins.sum() / -losses.sum()) if losses.sum() < 0 else math.inf
    return {
        "trades": n,
        "win_rate_pct": round(100 * len(wins) / n, 1),
        "t1_hit_rate_pct": round(100 * hits / n, 1),
        "t1_hit_rate_ci95": wilson(hits, n),
        "avg_net_return_pct": round(float(net.mean()), 3),
        "expectancy_r": round(float(closed["r_multiple"].mean()), 3),
        "profit_factor": round(pf, 2) if math.isfinite(pf) else None,
        "max_drawdown_pct_at_10pct_alloc": round(dd, 1),
        "avg_sessions_held": round(float(closed["sessions_held"].mean()), 1),
        "exit_reasons": closed["exit_reason"].value_counts().to_dict(),
    }


def walk_forward(trades: pd.DataFrame, bcfg: BacktestConfig) -> dict:
    """Expanding-window calibration check of T1 hit rate per score bucket."""
    closed = trades[trades["exit_reason"] != "end_of_data"].copy()
    if closed.empty:
        return {"folds": [], "calibrated": False, "reason": "no trades"}
    closed["year"] = closed["signal_date"].str[:4].astype(int)
    folds, abs_err_w, w_total, oos_total = [], 0.0, 0, 0
    for year in sorted(y for y in closed["year"].unique() if y >= bcfg.first_test_year):
        train = closed[closed["year"] < year]
        test = closed[closed["year"] == year]
        fold = {"test_year": int(year), "train_trades": len(train), "test_trades": len(test), "buckets": {}}
        for b in BUCKETS:
            tr, te = train[train["bucket"] == b], test[test["bucket"] == b]
            if len(tr) < bcfg.min_bucket_trades or len(te) < 10:
                continue
            r_tr = float(100 * (tr["exit_reason"] == "target1").mean())
            r_te = float(100 * (te["exit_reason"] == "target1").mean())
            fold["buckets"][b] = {
                "train_rate": round(r_tr, 1),
                "test_rate": round(r_te, 1),
                "test_n": len(te),
                "abs_error_pp": round(abs(r_tr - r_te), 1),
            }
            abs_err_w += abs(r_tr - r_te) * len(te)
            w_total += len(te)
        oos_total += len(test)
        folds.append(fold)
    err = abs_err_w / w_total if w_total else math.inf
    calibrated = bool(w_total >= bcfg.min_total_oos_trades and err <= bcfg.max_calibration_error_pp)
    reason = (
        "passed"
        if calibrated
        else f"weighted OOS error {err:.1f}pp (max {bcfg.max_calibration_error_pp}) "
        f"over {w_total} bucketed OOS trades (min {bcfg.min_total_oos_trades})"
    )
    return {
        "folds": folds,
        "weighted_oos_error_pp": round(err, 2) if math.isfinite(err) else None,
        "oos_trades": oos_total,
        "bucketed_oos_trades": w_total,
        "calibrated": calibrated,
        "reason": reason,
    }


def bucket_table(trades: pd.DataFrame, min_n: int) -> dict[str, dict]:
    """Full-sample T1 hit rate per bucket with Wilson CI (used by the live report if calibrated)."""
    closed = trades[trades["exit_reason"] != "end_of_data"]
    out = {}
    for b in BUCKETS:
        sub = closed[closed["bucket"] == b]
        k, n = int((sub["exit_reason"] == "target1").sum()), len(sub)
        out[b] = {
            "n": n,
            "t1_hit_rate_pct": round(100 * k / n, 1) if n else None,
            "ci95": wilson(k, n) if n else None,
            "expectancy_r": round(float(sub["r_multiple"].mean()), 3) if n else None,
            "sufficient_sample": n >= min_n,
        }
    return out


def run_backtest(files: dict[str, Path], settings: Settings = DEFAULT_SETTINGS, workers: int | None = None) -> dict:
    """Backtest every file; return the summary dict (trades included as a DataFrame under '_trades')."""
    jobs = [(s, str(p), settings) for s, p in sorted(files.items())]
    workers = workers or max(1, (os.cpu_count() or 2) - 0)
    rows: list[dict] = []
    if workers == 1:
        for j in jobs:
            rows.extend(backtest_symbol(j))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for res in pool.map(backtest_symbol, jobs, chunksize=4):
                rows.extend(res)
    trades = pd.DataFrame(rows)
    if trades.empty:
        return {"summary_all": {"trades": 0}, "calibrated": False, "_trades": trades}
    bcfg = settings.backtest
    wf = walk_forward(trades, bcfg)
    eligible = trades[trades["eligible_rule"]]
    result = {
        "rules": __doc__.split("Rules (")[1].split("Walk-forward:")[0].strip() if __doc__ else "",
        "settings": {"backtest": asdict(bcfg), "costs": asdict(settings.costs)},
        "symbols_tested": len(files),
        "period": {"start": trades["signal_date"].min(), "end": trades["signal_date"].max()},
        "summary_all": summarize(trades),
        "summary_eligible_rule": summarize(eligible) if len(eligible) else {"trades": 0},
        "by_setup_type": {k: summarize(v) for k, v in trades.groupby("setup_type")},
        "by_bucket": bucket_table(trades, bcfg.min_bucket_trades),
        "walk_forward": wf,
        "calibrated": bool(wf["calibrated"]),
        "_trades": trades,
    }
    return result


def save_backtest(result: dict, out_dir: Path) -> Path:
    """Write latest.json + trades.csv."""
    out_dir.mkdir(parents=True, exist_ok=True)
    trades: pd.DataFrame = result.pop("_trades")
    trades.to_csv(out_dir / "trades.csv", index=False)
    path = out_dir / "latest.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    result["_trades"] = trades
    return path


def load_backtest(path: Path) -> dict | None:
    """Load a saved backtest summary (calibrated or not); None if missing/corrupt."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def load_calibration(path: Path) -> dict | None:
    """Return the saved backtest only if it passed walk-forward calibration, else None."""
    data = load_backtest(path)
    return data if data and data.get("calibrated") else None
