"""Explicit data-freshness check against the expected latest NEPSE session.

The trading calendar is inferred from the data itself, because it changed in
2026 (Sunday-Thursday until mid-2026, Monday-Friday afterwards). Public holidays
are unknown, so a "stale" result on a holiday is a false alarm -- the message
says so. A report is only "current" when the data date equals the most recent
session that should already have closed (NEPSE closes 15:00 Nepal time).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass

import pandas as pd

MARKET_CLOSE_NPT = dt.time(15, 0)
WEEKDAY_NP = ["सोमबार", "मङ्गलबार", "बुधबार", "बिहीबार", "शुक्रबार", "शनिबार", "आइतबार"]


@dataclass(frozen=True)
class Freshness:
    """Result of the freshness check."""

    status: str  # "current" | "stale" | "blocked"
    market_date: dt.date | None
    expected_session: dt.date | None
    sessions_missing: int | None
    calendar_age_days: int | None
    trading_weekdays: tuple[int, ...]
    nepal_now: dt.datetime

    @property
    def is_current(self) -> bool:
        return self.status == "current"


def infer_trading_weekdays(sessions: list[pd.Timestamp], lookback: int = 40, min_count: int = 3) -> tuple[int, ...]:
    """Weekdays (Mon=0) that appear at least ``min_count`` times in the last ``lookback`` sessions."""
    recent = sessions[-lookback:]
    c = Counter(d.weekday() for d in recent)
    days = tuple(sorted(w for w, n in c.items() if n >= min_count))
    return days or (0, 1, 2, 3, 4)


def expected_latest_session(nepal_now: dt.datetime, weekdays: tuple[int, ...]) -> dt.date:
    """Most recent trading day whose session has closed by ``nepal_now`` (holidays unknown)."""
    d = nepal_now.date()
    if not (d.weekday() in weekdays and nepal_now.time() >= MARKET_CLOSE_NPT):
        d -= dt.timedelta(days=1)
        while d.weekday() not in weekdays:
            d -= dt.timedelta(days=1)
    return d


def count_sessions_between(start: dt.date, end: dt.date, weekdays: tuple[int, ...]) -> int:
    """Trading weekdays in the half-open interval (start, end]."""
    n, d = 0, start + dt.timedelta(days=1)
    while d <= end:
        n += d.weekday() in weekdays
        d += dt.timedelta(days=1)
    return n


def assess(
    market_date: dt.date | None,
    sessions: list[pd.Timestamp],
    nepal_now: dt.datetime,
    block_sessions: int = 4,
    block_days: int = 10,
) -> Freshness:
    """Classify data freshness. ``blocked`` suppresses all setups."""
    weekdays = infer_trading_weekdays(sessions)
    if market_date is None:
        return Freshness("blocked", None, None, None, None, weekdays, nepal_now)
    expected = expected_latest_session(nepal_now, weekdays)
    missing = count_sessions_between(market_date, expected, weekdays) if expected > market_date else 0
    age = (nepal_now.date() - market_date).days
    if missing == 0:
        status = "current"
    elif missing < block_sessions and age <= block_days:
        status = "stale"
    else:
        status = "blocked"
    return Freshness(status, market_date, expected, missing, age, weekdays, nepal_now)


def banner_np(f: Freshness) -> str:
    """One prominent line for the top of every report."""
    if f.market_date is None:
        return "⛔ **डाटा उपलब्ध छैन** — कुनै विश्लेषण भरपर्दो छैन।"
    md = f"{f.market_date} ({WEEKDAY_NP[f.market_date.weekday()]})"
    today = f"{f.nepal_now.date()} ({WEEKDAY_NP[f.nepal_now.weekday()]})"
    if f.status == "current":
        return f"✅ **डाटा ताजा:** {md} को कारोबार — यो सबैभन्दा पछिल्लो बन्द भएको सत्र हो।"
    exp = f"{f.expected_session} ({WEEKDAY_NP[f.expected_session.weekday()]})" if f.expected_session else "—"
    base = (
        f"**यो रिपोर्ट {md} को बन्द मूल्यमा आधारित हो, आज {today} को बजारको होइन।** "
        f"अपेक्षित पछिल्लो सत्र {exp} को डाटा स्रोतमा आएको छैन ({f.sessions_missing} सत्र छुटेको; "
        f"त्यो दिन सार्वजनिक बिदा भए यो स्वाभाविक हो)।"
    )
    if f.status == "stale":
        return "⚠️ **STALE — पुरानो डाटा:** " + base
    return "⛔ **BLOCKED — धेरै पुरानो डाटा, सेटअप सूची रोकिएको:** " + base
