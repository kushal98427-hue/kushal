"""Independent backtest audit: performance breakdowns, portfolio simulation, data checks.

Nothing here changes strategy parameters. It only slices the trades produced by
``nepse_ta.backtest`` and re-runs sensitivity variants of *execution assumptions*.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from nepse_ta.backtest import summarize
from nepse_ta.config import CostConfig
from nepse_ta.data.validation import prepare_series
from nepse_ta.indicators import sma
from nepse_ta.sectors import SECTOR_NP, SectorInfo, unclassified

HOLDOUT_START = "2025-01-01"


# --------------------------------------------------------------------------- regimes
def equal_weight_index(files: dict[str, Path], dcfg, min_stocks: int = 50) -> pd.Series:
    """Median daily return across equities -> cumulative index (proxy; NOT the official NEPSE index)."""
    rets = []
    for sym, p in files.items():
        try:
            s = prepare_series(sym, p, dcfg)
        except Exception:  # noqa: BLE001
            continue
        df = s.df
        gap = df.index.to_series().diff().dt.days
        r = df["close"].pct_change().where(gap <= 7)
        rets.append(r.rename(sym))
    panel = pd.concat(rets, axis=1)
    count = panel.notna().sum(axis=1)
    med = panel.median(axis=1).where(count >= min_stocks).dropna()
    return (1 + med).cumprod().rename("ew_index")


def classify_regimes(index: pd.Series) -> pd.Series:
    """bull / bear / sideways at each date using only data up to that date."""
    s200, s50 = sma(index, 200), sma(index, 50)
    slope = s50 - s50.shift(20)
    reg = pd.Series("sideways", index=index.index)
    reg[(index > s200) & (slope > 0)] = "bull"
    reg[(index < s200) & (slope < 0)] = "bear"
    reg[s200.isna()] = "unknown"
    return reg


# --------------------------------------------------------------------------- portfolio
def simulate_portfolio(trades: pd.DataFrame, costs: CostConfig, slots: int = 10) -> dict:
    """Capital-constrained, daily mark-to-market portfolio.

    * ``slots`` equal positions max; each new position gets equity/slots at entry.
    * When more signals than free slots arrive on one day, the highest score wins
      (score is known at signal time, so this uses no future information).
    * Open positions are marked at each close; exits book the trade's net return.
    """
    fee = (costs.commission_pct + costs.sebon_fee_pct) / 100
    slip = costs.slippage_pct / 100
    tr = trades[trades["exit_reason"] != "open"].reset_index(drop=True)
    entries: dict[str, list[int]] = {}
    for i, d in enumerate(tr["entry_date"]):
        entries.setdefault(d, []).append(i)
    paths = [dict(p) for p in tr["_path"]]
    all_dates = sorted({d for p in paths for d in p} | set(tr["exit_date"]))
    cash, open_pos, taken, skipped = 1.0, {}, 0, 0
    last_ratio: dict[int, float] = {}
    curve = []
    exits_by_date: dict[str, list[int]] = {}
    for i, d in enumerate(tr["exit_date"]):
        exits_by_date.setdefault(d, []).append(i)
    for d in all_dates:
        for i in exits_by_date.get(d, []):
            if i in open_pos:
                cash += open_pos.pop(i) * (1 + tr.at[i, "net_return_pct"] / 100)
        cands = sorted(entries.get(d, []), key=lambda i: -tr.at[i, "score"])
        equity_now = cash + sum(a * last_ratio.get(i, 1.0) / ((1 + slip) * (1 + fee)) for i, a in open_pos.items())
        for i in cands:
            if len(open_pos) >= slots:
                skipped += 1
                continue
            alloc = equity_now / slots
            if alloc > cash + 1e-12:
                skipped += 1
                continue
            cash -= alloc
            open_pos[i] = alloc
            taken += 1
        for i in open_pos:
            if d in paths[i]:
                last_ratio[i] = paths[i][d]
        mtm = sum(a * last_ratio.get(i, 1.0) / ((1 + slip) * (1 + fee)) for i, a in open_pos.items())
        curve.append((d, cash + mtm, len(open_pos)))
    eq = pd.DataFrame(curve, columns=["date", "equity", "positions"]).set_index("date")
    eq.index = pd.to_datetime(eq.index)
    if eq.empty:
        return {"trades_taken": 0}
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    dd = eq["equity"] / eq["equity"].cummax() - 1
    yearly = eq["equity"].resample("YE").last()
    yearly_ret = (yearly / yearly.shift(1).fillna(1.0) - 1) * 100
    return {
        "slots": slots,
        "trades_taken": taken,
        "signals_skipped_no_capital": skipped,
        "total_return_pct": round((eq["equity"].iloc[-1] - 1) * 100, 1),
        "cagr_pct": round((eq["equity"].iloc[-1] ** (1 / years) - 1) * 100, 2),
        "max_drawdown_pct": round(float(dd.min()) * 100, 1),
        "avg_positions_open": round(float(eq["positions"].mean()), 2),
        "yearly_return_pct": {str(k.year): round(float(v), 1) for k, v in yearly_ret.items()},
    }


# --------------------------------------------------------------------------- breakdowns
def _hold_bucket(n: int) -> str:
    return "3-5" if n <= 5 else "6-10" if n <= 10 else "11-15" if n <= 15 else "16-20"


def enrich(trades: pd.DataFrame, regimes: pd.Series, sector_map: dict[str, SectorInfo]) -> pd.DataFrame:
    t = trades.copy()
    reg = regimes.reindex(pd.to_datetime(t["signal_date"]), method="ffill")
    t["regime"] = reg.to_numpy()
    t["group"] = [(sector_map.get(s) or unclassified(s)).group for s in t["symbol"]]
    t["hold_bucket"] = t["sessions_held"].map(_hold_bucket)
    t["year"] = t["signal_date"].str[:4]
    t["period"] = np.where(t["signal_date"] >= HOLDOUT_START, "holdout 2025-2026", "2019-2024")
    return t


def breakdown(t: pd.DataFrame, by: str) -> dict[str, dict]:
    return {str(k): summarize(v) for k, v in t.groupby(by)}


def adjustment_audit(files: dict[str, Path], dcfg) -> dict:
    """Plausibility of detected bonus/right adjustments."""
    factors, residual_big, rows = [], 0, 0
    for sym, p in files.items():
        s = prepare_series(sym, p, dcfg)
        factors += [e.factor for e in s.adjustments if e.date >= "2019-01-01"]
        live = s.df[s.df.index >= "2019-01-01"]
        if len(live) > 1:
            gap = live.index.to_series().diff().dt.days
            mv = live["close"].pct_change().abs() * 100
            residual_big += int(((mv > dcfg.circuit_limit_pct) & (gap <= 7)).sum())
            rows += len(live)
    f = np.array(factors)
    implied = np.round((1 / f - 1) * 100, 1) if len(f) else np.array([])
    near_integer = np.abs(implied - np.round(implied)) <= 0.15 if len(f) else np.array([])
    top = pd.Series(np.round(implied)).value_counts().head(10).to_dict() if len(f) else {}
    return {
        "events_since_2019": int(len(f)),
        "implied_bonus_pct_top10": {f"{int(k)}%": int(v) for k, v in top.items()},
        "share_within_0.15pp_of_integer_pct": round(float(near_integer.mean()) * 100, 1) if len(f) else None,
        "residual_moves_beyond_circuit_after_adjustment": residual_big,
        "rows_checked": rows,
    }


def fmt_row(name: str, s: dict) -> str:
    if not s.get("trades"):
        return f"| {name} | 0 | | | | | | | | |"
    ci = s.get("expectancy_r_ci95_monthly_bootstrap") or (None, None)
    ci_s = f"{ci[0]} … {ci[1]}" if ci[0] is not None else "n<30"
    return (
        f"| {name} | {s['trades']} | {s['win_rate_pct']}% | {s['avg_win_pct']}% | {s['avg_loss_pct']}% | "
        f"{s['avg_return_pct']}% | **{s['expectancy_r']}R** ({ci_s}) | {s['profit_factor']} | {s['max_drawdown_r']}R | "
        f"{s['avg_sessions_held']} |"
    )


TABLE_HEAD = [
    "| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |",
    "|---|---|---|---|---|---|---|---|---|---|",
]


def table(title: str, rows: dict[str, dict], label=lambda k: k) -> list[str]:
    return [f"### {title}", "", *TABLE_HEAD, *(fmt_row(label(k), v) for k, v in rows.items()), ""]


def sector_label(k: str) -> str:
    return f"{k} ({SECTOR_NP.get(k, k)})"


def is_finite(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))
