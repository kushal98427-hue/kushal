"""Render reports/audit/backtest_audit.json into the audit tables (Markdown).

    python scripts/write_audit_md.py /path/to/backtest_audit.json > tables.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_ta.audit import sector_label, table  # noqa: E402

ORDER_REGIME = ["bull", "sideways", "bear", "unknown"]


def ordered(d: dict, order: list[str]) -> dict:
    return {k: d[k] for k in order if k in d} | {k: v for k, v in d.items() if k not in order}


def main() -> None:
    r = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    o, sens = r["overall"], r["sensitivity"]
    out: list[str] = []
    out += table(
        "Costs: raw (no costs) vs gross (after slippage) vs net (slippage + fees + DP + CGT)",
        {
            "All setups — raw, no costs": o["all_raw_no_costs"],
            "All setups — gross (slippage only)": o["all_gross_after_slippage"],
            "All setups — net": o["all_net"],
            "Master list — raw, no costs": o["master_raw_no_costs"],
            "Master list — gross (slippage only)": o["master_gross_after_slippage"],
            "Master list — net": o["master_net"],
        },
    )
    out += table(
        "Sensitivity to execution assumptions (net)",
        {
            "All — baseline (circuit locks modelled, sell from 3rd session)": o["all_net"],
            "All — circuit locks NOT modelled": sens["all_net_no_circuit_model"],
            "All — sell from 2nd session (T+2 optimistic)": sens["all_net_min_hold_2"],
            "All — excluding trades spanning a bonus/right adjustment": sens["all_net_excluding_adjustment_spanning"],
            "All — excluding low-liquidity stocks": sens["all_net_excluding_low_liquidity"],
            "Master — circuit locks NOT modelled": sens["master_net_no_circuit_model"],
            "Master — sell from 2nd session": sens["master_net_min_hold_2"],
        },
    )
    out += table("Market regime — all setups (net)", ordered(r["by_regime_all"], ORDER_REGIME))
    out += table("Market regime — master list (net)", ordered(r["by_regime_master"], ORDER_REGIME))
    out += table("Setup type — all (net)", r["by_setup_all"])
    out += table("Setup type — master list (net)", r["by_setup_master"])
    out += table("Score range — all setups (net)", r["by_score_bucket"])
    out += table("Holding period (sessions) — all setups (net)", ordered(r["by_holding_period"], ["3-5", "6-10", "11-15", "16-20"]))
    out += table("Sector — all setups (net)", dict(sorted(r["by_sector_all"].items(), key=lambda kv: -kv[1]["trades"])), sector_label)
    out += table("Sector — master list (net)", dict(sorted(r["by_sector_master"].items(), key=lambda kv: -kv[1]["trades"])), sector_label)
    out += table("Out-of-sample: 2019-2024 vs untouched holdout 2025-2026 — all (net)", r["by_period_all"])
    out += table("Out-of-sample: 2019-2024 vs untouched holdout 2025-2026 — master (net)", r["by_period_master"])
    out += table("By signal year — all setups (net)", r["by_year_all"])
    out += table("By signal year — master list (net)", r["by_year_master"])
    for name in ("portfolio_master_10_slots", "portfolio_all_10_slots"):
        p = r[name]
        out += [
            f"### Capital-constrained portfolio: {name.replace('_', ' ')}",
            "",
            f"- Trades taken {p.get('trades_taken')} · skipped for lack of capital/slots {p.get('signals_skipped_no_capital')}",
            f"- Total return {p.get('total_return_pct')}% · CAGR {p.get('cagr_pct')}% · **max drawdown {p.get('max_drawdown_pct')}%** "
            f"(daily mark-to-market) · avg positions open {p.get('avg_positions_open')}",
            f"- Yearly return %: {p.get('yearly_return_pct')}",
            "",
        ]
    wf = r["walk_forward"]
    out += ["### Walk-forward calibration of T1 hit rate (expanding window)", "", "| Test year | Train trades | Test trades | Bucket: train% → test% (n) |", "|---|---|---|---|"]
    for f in wf["folds"]:
        parts = ", ".join(f"{b}: {v['train_rate']}→{v['test_rate']} ({v['test_n']})" for b, v in f["buckets"].items())
        out.append(f"| {f['test_year']} | {f['train_trades']} | {f['test_trades']} | {parts} |")
    out += ["", f"Weighted OOS error {wf.get('weighted_oos_error_pp')} pp over {wf.get('bucketed_oos_trades')} trades → calibrated = {wf.get('calibrated')}", ""]
    print("\n".join(out))


if __name__ == "__main__":
    main()
