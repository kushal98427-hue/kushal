"""Build the stored daily analysis record for one stock, and compare plans.

The record separates *content* (what the analysis says, hashed for duplicate
detection) from *run metadata* (when/where it was produced). Two runs on the
same trading date that produce identical content are duplicates; different
content is a revision.
"""

from __future__ import annotations

from nepse_ta.analysis import SETUP_TYPES, StockAnalysis
from nepse_ta.config import STRATEGY_VERSION
from nepse_ta.memory.store import content_hash

SCHEMA_VERSION = 1

#: Fields of the plan that define "the trade plan" for change tracking.
PLAN_FIELDS = ("plan_type", "entry_low", "entry_high", "stop", "target1", "target2", "classification")  # stored view


def classify(a: StockAnalysis, watchlist: set[str], open_recs: set[str]) -> str:
    """v1 rules mapped onto the A–E categories (A–C refined in later phases)."""
    if a.symbol in open_recs:
        return "E_existing_monitor"
    if a.eligible:
        return "A_high_priority_setup"
    if a.symbol in watchlist:
        return "B_watchlist_waiting_confirmation"
    return "D_avoid_no_trade"


def thesis_text(a: StockAnalysis) -> str:
    """Plain statement built only from computed fields (template until Phase 2)."""
    p = a.plan
    parts = [f"दैनिक {a.daily_trend}, साप्ताहिक {a.weekly_trend}, स्थिति {a.status}"]
    if p.plan_type in SETUP_TYPES:
        parts.append(f"{p.plan_type} सेटअप: इन्ट्री {p.entry_low}–{p.entry_high}, स्टप {p.stop}, T1 {p.target1}")
    elif p.plan_type == "watch_breakout":
        parts.append(f"ट्रिगर पर्खने: {p.trigger}")
    else:
        parts.append("सक्रिय सेटअप छैन")
    return "; ".join(parts)


def confirmation_conditions(a: StockAnalysis) -> list[str]:
    p = a.plan
    if p.plan_type in SETUP_TYPES:
        return [f"अर्को सत्रमा मूल्य इन्ट्री जोन {p.entry_low}–{p.entry_high} भित्र कारोबार होस् (स्टप {p.stop} माथि)"]
    if p.trigger:
        return [p.trigger]
    return []


def build_content(a: StockAnalysis, classification: str) -> dict:
    """Everything the analysis says about the stock on its trading date (hashed)."""
    p = a.plan
    return {
        "schema": SCHEMA_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "symbol": a.symbol,
        "company_name": a.company_name,
        "sector": a.sector,
        "group": a.group,
        "trading_date": a.date,
        "price": {
            "close": a.close,
            "change_pct": a.change_pct,
            "return_20d_pct": a.return_20d,
            "high_52w": a.high_52w,
            "low_52w": a.low_52w,
        },
        "volume": {
            "volume": a.volume,
            "rel_volume": a.rel_volume,
            "volume_reliable": a.volume_reliable,
            "median_turnover_20": a.median_turnover_20,
            "low_liquidity": a.low_liquidity,
        },
        "technical": {
            "daily_trend": a.daily_trend,
            "weekly_trend": a.weekly_trend,
            "status": a.status,
            "sma": a.sma,
            "rsi": a.rsi,
            "macd": a.macd,
            "macd_signal": a.macd_signal,
            "macd_hist": a.macd_hist,
            "atr": a.atr,
            "atr_pct": a.atr_pct,
            "candle": a.candle_direction,
            "patterns": a.patterns,
            "supports": a.supports,
            "resistances": a.resistances,
        },
        # Filled from Phase 2 / Phase 5. Explicitly marked so a reader never mistakes
        # "not analysed yet" for "nothing found".
        "smc": {"status": "not_available", "reason": "SMC module not implemented yet (Phase 2)"},
        "events": {"status": "not_available", "reason": "event/corporate-action module not implemented yet (Phase 5)"},
        "plan": {
            "plan_type": p.plan_type,
            "entry_low": p.entry_low,
            "entry_high": p.entry_high,
            "entry_trigger": p.trigger or (f"entry zone {p.entry_low}–{p.entry_high}" if p.entry_low else None),
            "stop": p.stop,
            "stop_basis": p.stop_basis,
            "target1": p.target1,
            "target1_basis": p.target1_basis,
            "target2": p.target2,
            "target2_basis": p.target2_basis,
            "target3": None,
            "rr1": p.rr1,
            "rr2": p.rr2,
            "target_is_projection": bool(p.target1_basis and "प्रक्षेपण" in p.target1_basis),
            "notes": p.notes,
        },
        "thesis": thesis_text(a),
        "confirmation_conditions": confirmation_conditions(a),
        "invalidation_conditions": list(p.invalidation),
        "scenarios": {"bullish": a.scenario_bullish, "bearish": a.scenario_bearish},
        "score": {"value": a.score, "band": a.score_band, "breakdown": a.score_breakdown, "kind": "heuristic, not probability"},
        "classification": classification,
        "eligible": a.eligible,
        "ineligible_reasons": a.ineligible_reasons,
        # Stock-staleness warnings change every day ("N sessions behind") without any new
        # information about the stock, so they live in run context, not in hashed content.
        "warnings": [w for w in a.warnings if not _is_staleness_warning(w)],
    }


def _is_staleness_warning(w: str) -> bool:
    return "सत्र पछाडि (stale)" in w


def run_context(a: StockAnalysis) -> dict:
    """Per-run facts about a stock that are NOT part of its analysis content."""
    return {"stale_stock": a.stale, "staleness_warnings": [w for w in a.warnings if _is_staleness_warning(w)]}


def plan_view(content: dict) -> dict:
    """The subset compared for plan-change tracking."""
    p = content["plan"]
    return {
        "plan_type": p["plan_type"],
        "entry_low": p["entry_low"],
        "entry_high": p["entry_high"],
        "stop": p["stop"],
        "target1": p["target1"],
        "target2": p["target2"],
        "classification": content["classification"],
    }


#: Classes whose trade plan matters (setup, watchlist, event, existing trade).
ACTIONABLE = ("A_", "B_", "C_", "E_")
PRICE_FIELDS = ("entry_low", "entry_high", "stop", "target1", "target2")
#: A price level must move by more than this fraction to count as a plan change.
LEVEL_TOLERANCE = 0.01


def diff_fields(old: dict, new: dict) -> list[str]:
    """Meaningful plan changes.

    * plan type or classification changed → always a change;
    * otherwise price levels only matter when the stock is (or was) actionable
      (A/B/C/E), and only if a level moved by more than ``LEVEL_TOLERANCE``
      (daily ATR recalculation moves every level a little).
    """
    changed = ["classification"] if old.get("classification") != new.get("classification") else []
    actionable = any(str(x.get("classification", "")).startswith(ACTIONABLE) for x in (old, new))
    if not actionable:
        return changed  # a no-trade stock's plan type / levels are not a trade plan
    if old.get("plan_type") != new.get("plan_type"):
        changed.append("plan_type")
    for k in PRICE_FIELDS:
        a, b = old.get(k), new.get(k)
        if (a is None) != (b is None):
            changed.append(k)
        elif a is not None and b is not None and abs(b - a) > LEVEL_TOLERANCE * max(abs(a), 1e-9):
            changed.append(k)
    return changed


def explain_change(prev: dict, cur: dict, same_date: bool) -> str:
    """Rule-based reason (facts only, no invented narrative)."""
    reasons = []
    if same_date:
        reasons.append("same trading date re-analysed")
        if prev["strategy_version"] != cur["strategy_version"]:
            reasons.append(f"strategy version {prev['strategy_version']} → {cur['strategy_version']}")
        if prev["price"] != cur["price"] or prev["volume"] != cur["volume"]:
            reasons.append("source price/volume data for this date changed")
        sections = sorted(k for k in cur if prev.get(k) != cur.get(k))
        reasons.append("changed sections: " + ", ".join(sections))
    else:
        reasons.append(f"new candle {cur['trading_date']} (previous analysis {prev['trading_date']})")
    t0, t1 = prev["technical"], cur["technical"]
    for k in ("status", "daily_trend", "weekly_trend"):
        if t0.get(k) != t1.get(k):
            reasons.append(f"{k}: {t0.get(k)} → {t1.get(k)}")
    if prev["eligible"] != cur["eligible"]:
        reasons.append(f"eligible: {prev['eligible']} → {cur['eligible']}")
    return "; ".join(reasons)


def record_id(content: dict) -> str:
    return content_hash(content)[:16]
