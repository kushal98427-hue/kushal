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
    exit_reason: str  # target1 | stop | time | data_break | open (open = data ended, excluded)
    sessions_held: int
    calendar_days_held: int
    risk_pct: float
    raw_return_pct: float
    gross_return_pct: float
    net_return_pct: float
    r_multiple: float
    spans_adjustment: bool
    low_liquidity: bool
    median_turnover_20: float | None
    _path: list

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


def _locked(o: float, h: float, lo: float, c: float, prev_close: float, direction: int, limit: float) -> bool:
    """True if the bar traded at one price at the circuit limit (no counter-party all day).

    direction=-1: lower-circuit lock (cannot sell); +1: upper-circuit lock (cannot buy).
    """
    if not (h == lo == o == c) or prev_close <= 0:
        return False
    move = c / prev_close - 1
    return move <= -limit if direction < 0 else move >= limit


def simulate_trade(
    ind: pd.DataFrame,
    t: int,
    plan: TradePlan,
    bcfg: BacktestConfig,
    costs: CostConfig,
    segment_is_last: bool = True,
) -> tuple[dict, int] | None:
    """Simulate a trade signalled at bar ``t``. Returns (fields, exit_index) or None if not entered.

    ``segment_is_last`` tells whether the data really ends after this frame (open trade) or a
    price break cut it (``data_break``: closed at the last close and INCLUDED in statistics).
    """
    e = t + 1
    n = len(ind)
    if e >= n or plan.stop is None or plan.target1 is None or plan.entry_high is None:
        return None
    o = ind["open"].to_numpy()
    h = ind["high"].to_numpy()
    lo = ind["low"].to_numpy()
    c = ind["close"].to_numpy()
    dates = ind.index
    lim = bcfg.circuit_lock_pct / 100
    stop, t1 = float(plan.stop), float(plan.target1)
    # Stale signal: the stock did not trade in the next session(s) -> do not enter weeks later.
    if (dates[e] - dates[t]).days > bcfg.max_entry_delay_days:
        return None
    if o[e] > plan.entry_high * (1 + bcfg.max_entry_gap_pct / 100) or o[e] <= stop or o[e] >= t1:
        return None
    if bcfg.model_circuit_locks and _locked(o[e], h[e], lo[e], c[e], c[t], +1, lim):
        return None  # upper-circuit locked all day: no sellers, cannot buy
    slip = costs.slippage_pct / 100
    entry_px = o[e] * (1 + slip)
    exit_raw, reason, j_exit = None, "", n - 1
    last = min(e + bcfg.max_hold_sessions, n - 1)
    for j in range(e + bcfg.min_hold_sessions, last + 1):
        if bcfg.model_circuit_locks and _locked(o[j], h[j], lo[j], c[j], c[j - 1], -1, lim):
            continue  # lower-circuit locked all day: no buyers, cannot sell
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
            j_exit, exit_raw = n - 1, c[n - 1]
            reason = "open" if segment_is_last else "data_break"
    exit_px = exit_raw * (1 - slip)
    net = net_return(entry_px, exit_px, costs)
    risk_pct = (entry_px - stop) / entry_px * 100
    adj = ind["adj_factor"].to_numpy() if "adj_factor" in ind else None
    fields = {
        "entry_date": dates[e].strftime("%Y-%m-%d"),
        "exit_date": dates[j_exit].strftime("%Y-%m-%d"),
        "entry_price": round(entry_px, 2),
        "exit_price": round(exit_px, 2),
        "exit_reason": reason,
        "sessions_held": j_exit - e,
        "calendar_days_held": (dates[j_exit] - dates[e]).days,
        "risk_pct": round(risk_pct, 3),
        "raw_return_pct": round((exit_raw / o[e] - 1) * 100, 3),  # no slippage, fees or tax
        "gross_return_pct": round((exit_px / entry_px - 1) * 100, 3),  # after slippage only
        "net_return_pct": round(net, 3),  # after slippage, fees, DP and CGT
        "r_multiple": round(net / risk_pct, 3) if risk_pct > 0 else 0.0,
        "spans_adjustment": bool(adj is not None and adj[e] != adj[j_exit]),
        "_path": [(dates[k].strftime("%Y-%m-%d"), float(c[k] / o[e])) for k in range(e, j_exit + 1)],
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
    segments = series.segments()
    for si, seg in enumerate(segments):
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
            res = simulate_trade(
                frame.ind, int(t), a.plan, settings.backtest, settings.costs, segment_is_last=si == len(segments) - 1
            )
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
                        low_liquidity=bool(a.low_liquidity),
                        median_turnover_20=a.median_turnover_20,
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


def max_drawdown_r(closed: pd.DataFrame) -> float:
    """Largest peak-to-trough fall of the cumulative R curve (trades ordered by exit date)."""
    if closed.empty:
        return 0.0
    cum = closed.sort_values(["exit_date", "entry_date"])["r_multiple"].cumsum()
    peak = cum.cummax().clip(lower=0)
    return round(float((cum - peak).min()), 2)


def block_bootstrap_ci(closed: pd.DataFrame, col: str = "r_multiple", reps: int = 1000, seed: int = 0) -> tuple:
    """95% CI of the mean of ``col`` resampling whole calendar MONTHS of signals.

    Signals on the same days across many stocks are correlated (one market move hits all),
    so a naive per-trade CI would be too narrow.
    """
    if len(closed) < 30:
        return (None, None)
    months = closed["signal_date"].str[:7]
    groups = [g[col].to_numpy() for _, g in closed.groupby(months)]
    if len(groups) < 6:
        return (None, None)
    rng = np.random.default_rng(seed)
    sums = np.array([g.sum() for g in groups])
    counts = np.array([len(g) for g in groups])
    idx = rng.integers(0, len(groups), size=(reps, len(groups)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return (round(float(lo), 3), round(float(hi), 3))


def summarize(trades: pd.DataFrame, ret_col: str = "net_return_pct") -> dict:
    """Trade statistics. ``open`` trades (data ended) are excluded; everything else is included."""
    closed = trades[trades["exit_reason"] != "open"] if len(trades) else trades
    n = len(closed)
    if n == 0:
        return {"trades": 0}
    ret = closed[ret_col]
    r = closed["r_multiple"] if ret_col == "net_return_pct" else closed[ret_col] / closed["risk_pct"]
    wins, losses = ret[ret > 0], ret[ret <= 0]
    hits = int((closed["exit_reason"] == "target1").sum())
    pf = float(wins.sum() / -losses.sum()) if losses.sum() < 0 else math.inf
    tmp = closed.assign(r_multiple=r)
    return {
        "trades": n,
        "win_rate_pct": round(100 * len(wins) / n, 1),
        "win_rate_ci95": wilson(len(wins), n),
        "t1_hit_rate_pct": round(100 * hits / n, 1),
        "t1_hit_rate_ci95": wilson(hits, n),
        "avg_win_pct": round(float(wins.mean()), 3) if len(wins) else None,
        "avg_loss_pct": round(float(losses.mean()), 3) if len(losses) else None,
        "avg_return_pct": round(float(ret.mean()), 3),
        "expectancy_r": round(float(r.mean()), 3),
        "expectancy_r_ci95_monthly_bootstrap": block_bootstrap_ci(tmp),
        "profit_factor": round(pf, 2) if math.isfinite(pf) else None,
        "max_drawdown_r": max_drawdown_r(tmp),
        "avg_sessions_held": round(float(closed["sessions_held"].mean()), 1),
        "avg_calendar_days_held": round(float(closed["calendar_days_held"].mean()), 1)
        if "calendar_days_held" in closed
        else None,
        "exit_reasons": closed["exit_reason"].value_counts().to_dict(),
    }


def walk_forward(trades: pd.DataFrame, bcfg: BacktestConfig) -> dict:
    """Expanding-window calibration check of T1 hit rate per score bucket."""
    closed = trades[trades["exit_reason"] != "open"].copy()
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
    closed = trades[trades["exit_reason"] != "open"]
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
    trades.drop(columns=["_path"], errors="ignore").to_csv(out_dir / "trades.csv", index=False)
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
