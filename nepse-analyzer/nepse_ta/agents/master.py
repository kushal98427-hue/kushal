"""Master agent: compares the five sector reports and picks the strongest supported setups."""

from __future__ import annotations

from dataclasses import dataclass, field

from nepse_ta.agents.sector_agent import AgentReport, GroupStats, rank_key
from nepse_ta.analysis import StockAnalysis


@dataclass
class MasterReport:
    """Market-wide summary."""

    top_setups: list[StockAnalysis]
    sector_ranking: list[tuple[str, GroupStats]]  # (agent title, group stats), strongest first
    agent_overview: list[tuple[str, GroupStats, int]]  # (agent title, overall stats, n setups)
    watchlist: list[StockAnalysis]
    no_valid_setup: bool
    blocked_reason: str | None = None
    notes: list[str] = field(default_factory=list)


class MasterAgent:
    """Ranks eligible setups across all agents. It never lowers the bar to fill a list."""

    def __init__(self, top_n: int = 10, watchlist_size: int = 10) -> None:
        self.top_n = top_n
        self.watchlist_size = watchlist_size

    def run(self, reports: list[AgentReport], blocked_reason: str | None = None) -> MasterReport:
        all_setups = [a for r in reports for a in r.setups]
        top = [] if blocked_reason else sorted(all_setups, key=rank_key)[: self.top_n]
        ranking = sorted(
            ((r.title, g) for r in reports for g in r.groups), key=lambda x: -x[1].strength
        )
        overview = [(r.title, r.overall, len(r.setups)) for r in reports]
        watch = sorted([a for r in reports for a in r.watchlist], key=rank_key)[: self.watchlist_size]
        notes = []
        if not top:
            notes.append("यो डाटा मितिमा मापदण्ड पूरा गर्ने कुनै सेटअप भेटिएन। जबरजस्ती सिफारिस गरिएको छैन।")
        # concentration check: avoid a list dominated by one sector without saying so
        if top:
            counts: dict[str, int] = {}
            for a in top:
                counts[a.group] = counts.get(a.group, 0) + 1
            g, c = max(counts.items(), key=lambda kv: kv[1])
            if c >= max(3, len(top) // 2 + 1):
                notes.append(f"शीर्ष सूचीमा {c} वटा एउटै समूह ({g}) बाट छन् — क्षेत्रगत जोखिम केन्द्रित हुन सक्छ।")
        return MasterReport(
            top_setups=top,
            sector_ranking=ranking,
            agent_overview=overview,
            watchlist=watch if not blocked_reason else [],
            no_valid_setup=not top,
            blocked_reason=blocked_reason,
            notes=notes,
        )
