"""Run the independent backtest audit and write ``reports/audit/backtest_audit.md`` (+ JSON).

    python scripts/run_audit.py --source-dir /path/to/nepse-data/data/company-wise

No strategy parameter is tuned here. Variants change only *execution assumptions*
(circuit-lock modelling, settlement lock length, costs) to show how sensitive the
result is to them.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_ta import audit as A  # noqa: E402
from nepse_ta.backtest import run_backtest, summarize  # noqa: E402
from nepse_ta.config import DEFAULT_SETTINGS  # noqa: E402
from nepse_ta.data.fetcher import load_from_local_dir  # noqa: E402
from nepse_ta.sectors import EXCLUDED, load_sector_map  # noqa: E402


def variant(**bt) -> object:
    return dataclasses.replace(DEFAULT_SETTINGS, backtest=dataclasses.replace(DEFAULT_SETTINGS.backtest, **bt))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "audit")
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()

    sm = load_sector_map()
    files = {s: p for s, p in load_from_local_dir(args.source_dir).files.items() if not (s in sm and sm[s].agent == EXCLUDED)}
    equity_files = {s: p for s, p in files.items() if s in sm and sm[s].instrument_type == "Equity"}

    print("baseline backtest ...", flush=True)
    base = run_backtest(files, DEFAULT_SETTINGS, workers=args.workers)
    trades: pd.DataFrame = base["_trades"]
    print("variants ...", flush=True)
    no_circuit = run_backtest(files, variant(model_circuit_locks=False), workers=args.workers)["_trades"]
    hold2 = run_backtest(files, variant(min_hold_sessions=2), workers=args.workers)["_trades"]

    print("regimes / enrichment ...", flush=True)
    idx = A.equal_weight_index(equity_files, DEFAULT_SETTINGS.data)
    reg = A.classify_regimes(idx)
    t = A.enrich(trades, reg, sm)
    elig = t[t["eligible_rule"]]
    closed = t[t["exit_reason"] != "open"]

    res: dict = {
        "counts": {
            "trades_total": int(len(t)),
            "open_excluded": int((t["exit_reason"] == "open").sum()),
            "data_break_included": int((t["exit_reason"] == "data_break").sum()),
            "spans_adjustment": int(t["spans_adjustment"].sum()),
            "low_liquidity_trades": int(t["low_liquidity"].sum()),
            "calendar_days_gt_2x_sessions_plus_7": int((closed["calendar_days_held"] > 2 * closed["sessions_held"] + 7).sum()),
            "symbols": int(t["symbol"].nunique()),
            "delisted_or_suspended_symbols_traded": sorted(
                s for s in t["symbol"].unique() if sm.get(s) and sm[s].nepse_status in ("D", "S")
            ),
        },
        "overall": {
            "all_net": summarize(t),
            "all_gross_after_slippage": summarize(t, "gross_return_pct"),
            "all_raw_no_costs": summarize(t, "raw_return_pct"),
            "master_net": summarize(elig),
            "master_gross_after_slippage": summarize(elig, "gross_return_pct"),
            "master_raw_no_costs": summarize(elig, "raw_return_pct"),
        },
        "sensitivity": {
            "all_net_no_circuit_model": summarize(no_circuit),
            "all_net_min_hold_2": summarize(hold2),
            "master_net_no_circuit_model": summarize(no_circuit[no_circuit["eligible_rule"]]),
            "master_net_min_hold_2": summarize(hold2[hold2["eligible_rule"]]),
            "all_net_excluding_adjustment_spanning": summarize(t[~t["spans_adjustment"]]),
            "all_net_excluding_low_liquidity": summarize(t[~t["low_liquidity"]]),
        },
        "by_regime_all": A.breakdown(t, "regime"),
        "by_regime_master": A.breakdown(elig, "regime"),
        "by_sector_all": A.breakdown(t, "group"),
        "by_sector_master": A.breakdown(elig, "group"),
        "by_setup_all": A.breakdown(t, "setup_type"),
        "by_setup_master": A.breakdown(elig, "setup_type"),
        "by_score_bucket": A.breakdown(t, "bucket"),
        "by_holding_period": A.breakdown(t, "hold_bucket"),
        "by_year_all": A.breakdown(t, "year"),
        "by_year_master": A.breakdown(elig, "year"),
        "by_period_all": A.breakdown(t, "period"),
        "by_period_master": A.breakdown(elig, "period"),
        "portfolio_master_10_slots": A.simulate_portfolio(elig, DEFAULT_SETTINGS.costs, slots=10),
        "portfolio_all_10_slots": A.simulate_portfolio(t, DEFAULT_SETTINGS.costs, slots=10),
        "walk_forward": base["walk_forward"],
        "adjustments": A.adjustment_audit(files, DEFAULT_SETTINGS.data),
        "regime_days": reg[reg.index >= "2019-01-01"].value_counts().to_dict(),
        "index_range": [str(idx.index[0].date()), str(idx.index[-1].date())],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "backtest_audit.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    t.drop(columns=["_path"]).to_csv(args.out / "audit_trades.csv", index=False)
    print(json.dumps({k: res["overall"][k]["expectancy_r"] for k in res["overall"]}, indent=1))
    print("portfolio master", res["portfolio_master_10_slots"])
    print("saved", args.out)


if __name__ == "__main__":
    main()
