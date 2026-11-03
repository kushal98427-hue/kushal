"""Phase 2 historical replay checks for smc-1 (descriptive; no tuning, no performance claims).

    python scripts/smc_replay.py --source-dir <nepse-data>/data/company-wise --out /tmp/smc_replay.json

1. Causality: for N stocks and every k-th session of 2025-2026, the daily snapshot from one
   incremental pass over the FULL series equals a fresh engine on data truncated at t; weekly
   bars built from full data (weeks before t's week) equal weekly bars built from truncated data.
2. Descriptive statistics: per stock-year counts of swings, BOS, CHoCH, range breaks, OBs, FVGs,
   sweeps, equal-high/low zones; status distributions; share of bars with any break event.
3. Spot check: one trending, one ranging and one circuit-heavy stock (latest snapshot).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_ta.config import DEFAULT_SETTINGS  # noqa: E402
from nepse_ta.data.validation import prepare_series  # noqa: E402
from nepse_ta.sectors import load_sector_map  # noqa: E402
from nepse_ta.smc import DAILY, Engine, completed_weeks, smc_snapshot  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--causality-stocks", type=int, default=30)
    ap.add_argument("--every", type=int, default=5)
    args = ap.parse_args()
    sm = load_sector_map()
    syms = sorted(s for s, i in sm.items() if i.instrument_type == "Equity" and (args.source_dir / f"{s}.csv").exists())
    series = {}
    for s in syms:
        live = prepare_series(s, args.source_dir / f"{s}.csv", DEFAULT_SETTINGS.data).live
        if len(live) >= 300 and live.index[-1] >= pd.Timestamp("2026-10-01"):
            series[s] = live
    rng = np.random.default_rng(0)
    sample = sorted(rng.choice(sorted(series), size=min(args.causality_stocks, len(series)), replace=False))

    # 1. causality ---------------------------------------------------------------
    t0 = time.time()
    checks = mismatches = wk_checks = wk_mismatches = 0
    examples = []
    for s in sample:
        df = series[s]
        idx = np.flatnonzero(df.index >= pd.Timestamp("2025-01-01"))[:: args.every]
        eng = Engine(df, DAILY)
        wk_full = completed_weeks(df)
        for t in idx:
            eng.run(int(t))
            a = eng.snapshot()
            b = Engine(df.iloc[: t + 1], DAILY).run().snapshot()
            checks += 1
            if a != b:
                mismatches += 1
                if len(examples) < 3:
                    examples.append((s, str(df.index[t].date())))
            cur = df.index[t].to_period("W-SAT")
            w_a = wk_full[wk_full.index.to_period("W-SAT") < cur]
            w_b = completed_weeks(df.iloc[: t + 1])
            wk_checks += 1
            if not w_a.equals(w_b):
                wk_mismatches += 1
    causality = {
        "stocks": len(sample),
        "daily_checks": checks,
        "daily_mismatches": mismatches,
        "weekly_checks": wk_checks,
        "weekly_mismatches": wk_mismatches,
        "examples": examples,
        "seconds": round(time.time() - t0, 1),
    }
    print("causality", causality, flush=True)

    # 2. descriptive statistics ----------------------------------------------------
    t0 = time.time()
    agg = collections.Counter()
    status = collections.defaultdict(collections.Counter)
    flags = collections.Counter()
    bars = 0
    break_bars = 0
    for _s, df in series.items():
        eng = Engine(df, DAILY).run()
        sel = df.index >= pd.Timestamp("2025-01-01")
        first = int(np.argmax(sel))
        n = int(sel.sum())
        bars += n
        agg["swings"] += sum(1 for x in eng.acc if x["i"] >= first)
        evs = [e for e in eng.events if e["i"] >= first]
        break_bars += len({e["i"] for e in evs})
        for e in evs:
            agg[f"{e['type']}_{e['dir']}"] += 1
            status[e["type"]][e["status"]] += 1
            if e.get("mss_like"):
                agg["mss_like"] += 1
            for f in e["flags"]:
                flags[f"event:{f}"] += 1
        for o in (o for o in eng.obs if o["formed_i"] >= first):
            agg[f"OB_{o['dir']}"] += 1
            status["OB"][o["status"]] += 1
            for f in o["flags"]:
                flags[f"OB:{f}"] += 1
        for g in (g for g in eng.fvgs if g["formed_i"] >= first):
            agg[f"FVG_{g['dir']}"] += 1
            status["FVG"][g["status"]] += 1
            for f in g["flags"]:
                flags[f"FVG:{f}"] += 1
        for w in (w for w in eng.sweeps if w["i"] >= first):
            agg[f"sweep_{w['side']}"] += 1
            status["sweep"][w["status"]] += 1
        for z in (z for z in eng.eq_zones if z["formed_i"] >= first):
            agg[f"EQ_{z['side']}"] += 1
            status["EQ"][z["status"]] += 1
        for k, v in eng.counts.items():
            agg[k] += v
    stock_years = bars / 245
    per_sy = {k: round(v / stock_years, 2) for k, v in sorted(agg.items())}
    descriptive = {
        "stocks": len(series),
        "bars_2025_2026": bars,
        "stock_years": round(stock_years, 1),
        "per_stock_year": per_sy,
        "share_of_bars_with_a_break_event_pct": round(100 * break_bars / bars, 2),
        "status_distribution": {k: dict(v) for k, v in status.items()},
        "flags": dict(flags),
        "seconds": round(time.time() - t0, 1),
    }
    print("descriptive", json.dumps(descriptive["per_stock_year"]), flush=True)

    # 3. spot check -------------------------------------------------------------------
    def ret(df, n=120):
        return float(df["close"].iloc[-1] / df["close"].iloc[-n] - 1) * 100

    def circuit_days(df, n=250):
        ch = df["close"].pct_change().abs().iloc[-n:] * 100
        return int((ch >= 9.5).sum())

    trend = max(series, key=lambda s: ret(series[s]))
    ranging = min(series, key=lambda s: abs(ret(series[s])) + 100 * (series[s]["close"].iloc[-120:].std() / series[s]["close"].iloc[-1] < 0.02))
    circuit = max(series, key=lambda s: circuit_days(series[s]))
    spot = {}
    for label, s in (("trend", trend), ("range", ranging), ("circuit_heavy", circuit)):
        out = smc_snapshot(series[s])
        spot[label] = {"symbol": s, "return_120d_pct": round(ret(series[s]), 1), "circuit_days_250": circuit_days(series[s]), "smc": out}
    result = {"causality": causality, "descriptive": descriptive, "spot_check": spot}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("spot", {k: (v["symbol"], v["return_120d_pct"], v["circuit_days_250"]) for k, v in spot.items()})


if __name__ == "__main__":
    main()
