"""Daily scan: fetch -> validate -> analyse -> agents -> master. Pure orchestration."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from nepse_ta.agents import AgentReport, MasterAgent, MasterReport, SectorAgent
from nepse_ta.analysis import SETUP_TYPES, StockAnalysis, analyze_at, prepare_frame
from nepse_ta.config import DEFAULT_SETTINGS, NEPAL_TZ, SEOUL_TZ, Settings
from nepse_ta.data.fetcher import FetchResult, SourceInfo
from nepse_ta.data.validation import CleanSeries, prepare_series
from nepse_ta.scoring import score_bucket
from nepse_ta.sectors import EXCLUDED, SECTOR_AGENTS, UNCLASSIFIED, SectorInfo, unclassified

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Everything produced by one scan."""

    run_at_utc: str
    run_at_seoul: str
    market_date: str | None
    data_age_days: int | None
    freshness: str  # "ok" | "warn" | "blocked"
    source: SourceInfo
    analyses: list[StockAnalysis]
    agent_reports: list[AgentReport]
    unclassified: list[StockAnalysis]
    master: MasterReport
    excluded_instruments: list[str] = field(default_factory=list)
    inactive: list[tuple[str, str]] = field(default_factory=list)  # (symbol, last date)
    failures: dict[str, str] = field(default_factory=dict)
    global_warnings: list[str] = field(default_factory=list)
    quality_totals: dict[str, int] = field(default_factory=dict)
    calibration: dict | None = None
    backtest: dict | None = None  # latest backtest summary (shown even when not calibrated)


def market_session_dates(series: dict[str, CleanSeries], min_share: float = 0.25) -> list[pd.Timestamp]:
    """Dates on which at least ``min_share`` of symbols traded (robust 'market calendar')."""
    counts: dict[pd.Timestamp, int] = {}
    for s in series.values():
        for d in s.df.index[-400:]:
            counts[d] = counts.get(d, 0) + 1
    if not counts:
        return []
    need = max(1, int(min_share * len(series)))
    return sorted(d for d, c in counts.items() if c >= need)


def run_scan(
    fetch: FetchResult,
    sector_map: dict[str, SectorInfo],
    settings: Settings = DEFAULT_SETTINGS,
    now_utc: dt.datetime | None = None,
    calibration: dict | None = None,
    backtest: dict | None = None,
) -> ScanResult:
    """Run the full deterministic scan over already-fetched CSV files."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    dcfg, acfg = settings.data, settings.analysis
    failures = dict(fetch.failures)
    warnings: list[str] = []

    series: dict[str, CleanSeries] = {}
    for sym, path in sorted(fetch.files.items()):
        try:
            series[sym] = prepare_series(sym, path, dcfg)
        except Exception as exc:  # noqa: BLE001 - log and continue
            failures[sym] = f"validation failed: {exc}"
            log.exception("%s: validation failed", sym)
    for sym, msg in fetch.cache_warnings.items():
        warnings.append(f"{sym}: {msg}")

    sessions = market_session_dates(series)
    market_date = sessions[-1] if sessions else None
    nepal_today = now_utc.astimezone(ZoneInfo(NEPAL_TZ)).date()
    age = (nepal_today - market_date.date()).days if market_date is not None else None
    if age is None:
        freshness = "blocked"
        warnings.append("कुनै प्रयोगयोग्य डाटा भेटिएन")
    elif age > dcfg.market_stale_block_days:
        freshness = "blocked"
        warnings.append(f"डाटा {age} दिन पुरानो छ — सेटअप सूची रोकिएको (सीमा {dcfg.market_stale_block_days} दिन)")
    elif age > dcfg.market_stale_warn_days:
        freshness = "warn"
        warnings.append(f"डाटा {age} दिन पुरानो छ — बिदा वा स्रोत अपडेट नभएको हुन सक्छ")
    else:
        freshness = "ok"
    if fetch.source.commit_date_utc:
        warnings.append(f"स्रोत रिपोजिटरीको अन्तिम commit: {fetch.source.commit_date_utc} (UTC)")

    session_pos = {d: i for i, d in enumerate(sessions)}
    analyses: list[StockAnalysis] = []
    excluded: list[str] = []
    inactive: list[tuple[str, str]] = []
    totals: dict[str, int] = {}
    for sym, s in series.items():
        for k, v in s.quality.items():
            totals[k] = totals.get(k, 0) + int(v)
        info = sector_map.get(sym) or unclassified(sym)
        if info.agent == EXCLUDED:
            excluded.append(sym)
            continue
        last = s.last_date
        if last is None or market_date is None:
            failures[sym] = "no valid rows"
            continue
        if last < sessions[0] or (market_date - last).days > 120:
            inactive.append((sym, last.strftime("%Y-%m-%d")))
            continue
        behind = len(sessions) - 1 - session_pos.get(last, max(i for d, i in session_pos.items() if d <= last))
        live = s.live
        if len(live) < dcfg.min_history:
            failures[sym] = f"insufficient usable history ({len(live)} sessions after last price break)"
            continue
        try:
            frame = prepare_frame(live, acfg)
            recent_break = bool(s.breaks) and len(live) < 250
            a = analyze_at(frame, len(live) - 1, acfg, dcfg, sym, recent_break=recent_break)
        except Exception as exc:  # noqa: BLE001
            failures[sym] = f"analysis failed: {exc}"
            log.exception("%s: analysis failed", sym)
            continue
        if a is None:
            failures[sym] = "insufficient history"
            continue
        a.company_name, a.sector, a.group, a.agent = info.company_name, info.sector, info.group, info.agent
        a.warnings = list(s.warnings) + a.warnings
        if s.breaks and len(live) < 750:  # older breaks don't affect any indicator we use
            b = s.breaks[-1]
            a.warnings.append(f"{b.date} मा अस्पष्ट {b.raw_move_pct}% मूल्य परिवर्तन — त्यसअघिको इतिहास प्रयोग गरिएन")
        recent_adj = [e for e in s.adjustments if pd.Timestamp(e.date) >= live.index[max(0, len(live) - 250)]]
        if recent_adj:
            a.warnings.append(
                "बोनस/हकप्रद समायोजन लागू: "
                + ", ".join(f"{e.date} (×{e.factor:.3f})" for e in recent_adj)
                + " — पुराना मूल्य समायोजित"
            )
        if info.nepse_status in ("D", "S"):
            a.warnings.append(f"NEPSE स्थिति '{info.nepse_status}' (D=delisted, S=suspended) — सावधानी")
        if behind >= dcfg.stock_stale_sessions:
            a.stale = True
            a.warnings.append(f"अन्तिम कारोबार {a.date}; बजारभन्दा {behind} सत्र पछाडि (stale)")
        _set_eligibility(a, settings, freshness)
        if calibration:
            a.historical_rate = calibration.get("by_bucket", {}).get(score_bucket(a.score))
        analyses.append(a)

    by_agent: dict[str, list[StockAnalysis]] = {k: [] for k in SECTOR_AGENTS}
    uncls: list[StockAnalysis] = []
    for a in analyses:
        (by_agent[a.agent] if a.agent in by_agent else uncls).append(a)
    reports = [SectorAgent(k).run(by_agent[k]) for k in SECTOR_AGENTS]
    blocked = None if freshness != "blocked" else warnings[0]
    master = MasterAgent().run(reports, blocked_reason=blocked)

    if failures:
        warnings.append(f"{len(failures)} स्टक विश्लेषण/डाउनलोड हुन सकेन (विवरण JSON मा)")
    seoul = now_utc.astimezone(ZoneInfo(SEOUL_TZ))
    return ScanResult(
        run_at_utc=now_utc.isoformat(timespec="seconds"),
        run_at_seoul=seoul.strftime("%Y-%m-%d %H:%M %Z"),
        market_date=market_date.strftime("%Y-%m-%d") if market_date is not None else None,
        data_age_days=age,
        freshness=freshness,
        source=fetch.source,
        analyses=analyses,
        agent_reports=reports,
        unclassified=sorted(uncls, key=lambda a: a.symbol),
        master=master,
        excluded_instruments=sorted(excluded),
        inactive=sorted(inactive),
        failures=failures,
        global_warnings=warnings,
        quality_totals=totals,
        calibration=calibration,
        backtest=backtest,
    )


def _set_eligibility(a: StockAnalysis, settings: Settings, freshness: str) -> None:
    """Master-list eligibility. Every failed rule is recorded so nothing is hidden."""
    acfg = settings.analysis
    reasons = []
    if a.plan.plan_type not in SETUP_TYPES:
        reasons.append("आज सक्रिय सेटअप छैन")
    if a.plan.rr1 is None or a.plan.rr1 < acfg.min_rr_for_valid_setup:
        reasons.append(f"R:R {a.plan.rr1} < {acfg.min_rr_for_valid_setup}")
    if a.score < acfg.min_score_for_master:
        reasons.append(f"स्कोर {a.score} < {acfg.min_score_for_master}")
    if a.low_liquidity:
        reasons.append("कम तरलता")
    if a.stale:
        reasons.append("डाटा पुरानो")
    if a.agent == UNCLASSIFIED:
        reasons.append("सेक्टर वर्गीकरण नभएको")
    if freshness == "blocked":
        reasons.append("बजार डाटा पुरानो")
    a.eligible = not reasons
    a.ineligible_reasons = reasons


def load_fetch(source_dir: Path | None, cache_dir: Path, sector_map: dict[str, SectorInfo], symbols: list[str] | None) -> FetchResult:
    """Pick local directory or GitHub download."""
    from nepse_ta.data.fetcher import fetch_from_github, load_from_local_dir

    if source_dir:
        return load_from_local_dir(source_dir, symbols)
    return fetch_from_github(cache_dir, fallback_symbols=sorted(sector_map), symbols=symbols)
