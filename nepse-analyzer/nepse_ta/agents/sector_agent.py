"""Sector agents.

An "agent" here is a deterministic analyst module: it receives the per-stock
analyses for its sectors and produces breadth statistics, a ranked list of valid
setups, a watchlist and warnings. No LLM is needed. (An optional LLM narrative
can be layered on top -- see ``nepse_ta.narrative``.)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from nepse_ta.analysis import StockAnalysis
from nepse_ta.sectors import AGENT_TITLES_NP


@dataclass
class GroupStats:
    """Breadth statistics for one sector / sub-group."""

    group: str
    n: int
    n_uptrend: int
    n_downtrend: int
    pct_above_sma50: float | None
    pct_above_sma200: float | None
    median_rsi: float | None
    median_return_20d: float | None
    avg_score: float | None
    n_breakouts: int
    n_breakdowns: int
    n_valid_setups: int

    @property
    def strength(self) -> float:
        """Composite used only for ordering sectors: avg of %>SMA50 and avg score."""
        a = self.pct_above_sma50 if self.pct_above_sma50 is not None else 0.0
        b = self.avg_score if self.avg_score is not None else 0.0
        return round((a + b) / 2, 1)


def _median(vals: list[float]) -> float | None:
    return round(statistics.median(vals), 2) if vals else None


def group_stats(group: str, items: list[StockAnalysis]) -> GroupStats:
    """Compute breadth for a list of analyses (stale stocks excluded by the caller)."""
    with50 = [a for a in items if a.sma.get("sma50") is not None]
    with200 = [a for a in items if a.sma.get("sma200") is not None]
    return GroupStats(
        group=group,
        n=len(items),
        n_uptrend=sum(a.daily_trend == "uptrend" for a in items),
        n_downtrend=sum(a.daily_trend == "downtrend" for a in items),
        pct_above_sma50=round(100 * sum(a.close > a.sma["sma50"] for a in with50) / len(with50), 1) if with50 else None,
        pct_above_sma200=round(100 * sum(a.close > a.sma["sma200"] for a in with200) / len(with200), 1)
        if with200
        else None,
        median_rsi=_median([a.rsi for a in items if a.rsi is not None]),
        median_return_20d=_median([a.return_20d for a in items if a.return_20d is not None]),
        avg_score=round(statistics.mean([a.score for a in items]), 1) if items else None,
        n_breakouts=sum(a.status == "breakout" for a in items),
        n_breakdowns=sum(a.status == "breakdown" for a in items),
        n_valid_setups=sum(a.eligible for a in items),
    )


def rank_key(a: StockAnalysis) -> tuple:
    """Sort key: score, then reward:risk, then relative volume (all descending)."""
    return (-a.score, -(a.plan.rr1 or 0.0), -(a.rel_volume or 0.0), a.symbol)


@dataclass
class AgentReport:
    """Output of one sector agent."""

    key: str
    title: str
    analyses: list[StockAnalysis]
    stale: list[StockAnalysis]
    groups: list[GroupStats]
    overall: GroupStats
    setups: list[StockAnalysis]
    watchlist: list[StockAnalysis]
    breakdowns: list[StockAnalysis]
    comparison: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SectorAgent:
    """Analyst for one set of sectors."""

    def __init__(self, key: str, watchlist_size: int = 8) -> None:
        self.key = key
        self.title = AGENT_TITLES_NP.get(key, key)
        self.watchlist_size = watchlist_size

    def run(self, analyses: list[StockAnalysis]) -> AgentReport:
        """Build the report for this agent's stocks."""
        fresh = [a for a in analyses if not a.stale]
        stale = [a for a in analyses if a.stale]
        groups_map: dict[str, list[StockAnalysis]] = {}
        for a in fresh:
            groups_map.setdefault(a.group or a.sector, []).append(a)
        groups = sorted((group_stats(g, v) for g, v in groups_map.items()), key=lambda g: -g.strength)
        setups = sorted([a for a in fresh if a.eligible], key=rank_key)
        watch = sorted(
            [
                a
                for a in fresh
                if not a.eligible
                and a.plan.plan_type in ("watch_breakout", "breakout", "pullback")
                and a.daily_trend == "uptrend"
                and (a.plan.rr1 or 0) >= 1.5
                and not a.low_liquidity
            ],
            key=rank_key,
        )[: self.watchlist_size]
        breakdowns = sorted([a for a in fresh if a.status == "breakdown"], key=lambda a: a.return_20d or 0.0)
        report = AgentReport(
            key=self.key,
            title=self.title,
            analyses=sorted(fresh, key=rank_key),
            stale=stale,
            groups=groups,
            overall=group_stats("सबै", fresh),
            setups=setups,
            watchlist=watch,
            breakdowns=breakdowns,
        )
        if len(groups) > 1:
            report.comparison = compare_groups(groups)
        if stale:
            report.warnings.append(f"{len(stale)} स्टकको डाटा पुरानो (stale) — सेटअप सूचीबाट हटाइयो")
        return report


def compare_groups(groups: list[GroupStats]) -> list[str]:
    """Plain-language comparison lines between groups (strongest first)."""
    from nepse_ta.sectors import SECTOR_NP

    lines = []
    best, worst = groups[0], groups[-1]
    lines.append(
        f"प्राविधिक रूपमा बलियो समूह: **{SECTOR_NP.get(best.group, best.group)}** "
        f"(SMA50 माथि {best.pct_above_sma50}%, औसत स्कोर {best.avg_score})"
    )
    lines.append(
        f"कमजोर समूह: **{SECTOR_NP.get(worst.group, worst.group)}** "
        f"(SMA50 माथि {worst.pct_above_sma50}%, औसत स्कोर {worst.avg_score})"
    )
    for g in groups:
        lines.append(
            f"{SECTOR_NP.get(g.group, g.group)}: {g.n} स्टक, अपट्रेन्ड {g.n_uptrend}, डाउनट्रेन्ड {g.n_downtrend}, "
            f"२० दिने मध्य प्रतिफल {g.median_return_20d}%, मध्य RSI {g.median_rsi}"
        )
    return lines
