"""Machine-readable outputs: stock-by-stock CSV and full JSON."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from nepse_ta.agents.sector_agent import AgentReport, GroupStats
from nepse_ta.analysis import StockAnalysis
from nepse_ta.scan import ScanResult
from nepse_ta.scoring import SCORING_RULES

DISCLAIMER_EN = (
    "Educational technical analysis generated automatically from public OHLC data. "
    "Setup scores are heuristic rankings, not probabilities. Not investment advice."
)


def flatten(a: StockAnalysis) -> dict:
    """One CSV row per stock."""
    row = {
        "symbol": a.symbol,
        "company_name": a.company_name,
        "agent": a.agent,
        "sector": a.sector,
        "group": a.group,
        "date": a.date,
        "close": a.close,
        "change_pct": a.change_pct,
        "return_20d_pct": a.return_20d,
        "daily_trend": a.daily_trend,
        "weekly_trend": a.weekly_trend,
        **{k: v for k, v in a.sma.items()},
        "rsi14": a.rsi,
        "macd": a.macd,
        "macd_signal": a.macd_signal,
        "macd_hist": a.macd_hist,
        "atr14": a.atr,
        "atr_pct": a.atr_pct,
        "volume": a.volume,
        "rel_volume": a.rel_volume,
        "volume_reliable": a.volume_reliable,
        "median_turnover_20d": a.median_turnover_20,
        "low_liquidity": a.low_liquidity,
        "candle": a.candle_direction,
        "candle_close_location": a.candle_close_location,
        "patterns": "|".join(a.patterns),
        "status": a.status,
        "high_52w": a.high_52w,
        "low_52w": a.low_52w,
    }
    for i in range(2):
        s = a.supports[i] if i < len(a.supports) else {}
        r = a.resistances[i] if i < len(a.resistances) else {}
        row[f"support{i + 1}_low"], row[f"support{i + 1}_high"] = s.get("low"), s.get("high")
        row[f"resistance{i + 1}_low"], row[f"resistance{i + 1}_high"] = r.get("low"), r.get("high")
    p = a.plan
    row.update(
        {
            "plan_type": p.plan_type,
            "trigger": p.trigger,
            "entry_low": p.entry_low,
            "entry_high": p.entry_high,
            "stop": p.stop,
            "target1": p.target1,
            "target2": p.target2,
            "rr1": p.rr1,
            "rr2": p.rr2,
            "invalidation": " | ".join(p.invalidation),
            "setup_score": a.score,
            "score_band": a.score_band,
            "score_breakdown": " ".join(f"{k}:{v:+d}" for k, v in a.score_breakdown),
            "eligible_master": a.eligible,
            "ineligible_reasons": " | ".join(a.ineligible_reasons),
            "stale": a.stale,
            "scenario_bullish": a.scenario_bullish,
            "scenario_bearish": a.scenario_bearish,
            "historical_t1_rate_pct": (a.historical_rate or {}).get("t1_hit_rate_pct"),
            "warnings": " | ".join(a.warnings),
        }
    )
    return row


def write_csv(analyses: list[StockAnalysis], path: Path) -> None:
    rows = [flatten(a) for a in sorted(analyses, key=lambda a: (a.agent, a.symbol))]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel shows Nepali text
        if not rows:
            fh.write("symbol\n")
            return
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _gs(g: GroupStats) -> dict:
    d = asdict(g)
    d["strength"] = g.strength
    return d


def _agent(r: AgentReport) -> dict:
    return {
        "key": r.key,
        "title": r.title,
        "overall": _gs(r.overall),
        "groups": [_gs(g) for g in r.groups],
        "valid_setups": [a.symbol for a in r.setups],
        "watchlist": [a.symbol for a in r.watchlist],
        "breakdowns": [a.symbol for a in r.breakdowns],
        "stale": [a.symbol for a in r.stale],
        "comparison": r.comparison,
        "warnings": r.warnings,
        "symbols": [a.symbol for a in r.analyses],
    }


def build_json(res: ScanResult) -> dict:
    m = res.master
    return {
        "meta": {
            "run_at_utc": res.run_at_utc,
            "run_at_seoul": res.run_at_seoul,
            "market_date": res.market_date,
            "data_age_days": res.data_age_days,
            "freshness": res.freshness,
            "is_current_session": bool(res.fresh and res.fresh.is_current),
            "expected_latest_session": str(res.fresh.expected_session) if res.fresh else None,
            "sessions_missing": res.fresh.sessions_missing if res.fresh else None,
            "trading_weekdays_inferred": list(res.fresh.trading_weekdays) if res.fresh else None,
            "source": asdict(res.source),
            "historical_expectancy_r": ((res.backtest or {}).get("summary_eligible_rule") or {}).get("expectancy_r"),
            "probability_status": "calibrated_historical_rates" if res.calibration else "not_calibrated",
            "disclaimer": DISCLAIMER_EN,
            "scoring_rules": [{"id": r[0], "points": r[1], "rule": r[2]} for r in SCORING_RULES],
        },
        "warnings": res.global_warnings,
        "quality_totals": res.quality_totals,
        "master": {
            "no_valid_setup": m.no_valid_setup,
            "blocked_reason": m.blocked_reason,
            "top_setups": [a.symbol for a in m.top_setups],
            "watchlist": [a.symbol for a in m.watchlist],
            "sector_ranking": [{"agent": t, **_gs(g)} for t, g in m.sector_ranking],
            "notes": m.notes,
        },
        "agents": [_agent(r) for r in res.agent_reports],
        "stocks": [a.to_dict() for a in sorted(res.analyses, key=lambda a: a.symbol)],
        "unclassified": [a.symbol for a in res.unclassified],
        "excluded_instruments": res.excluded_instruments,
        "inactive": [{"symbol": s, "last_date": d} for s, d in res.inactive],
        "failures": res.failures,
    }


def write_json(res: ScanResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_json(res), ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
