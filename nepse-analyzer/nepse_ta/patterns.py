"""Candlestick structure and a small, well-defined set of patterns.

Each rule is written out explicitly so the report can be audited. Patterns are
context, not signals on their own; they add at most a few points to the score.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

PATTERN_NP: dict[str, str] = {
    "bullish_engulfing": "बुलिस एन्गल्फिङ",
    "bearish_engulfing": "बेयरिस एन्गल्फिङ",
    "hammer": "ह्यामर",
    "shooting_star": "सुटिङ स्टार",
    "doji": "डोजी",
    "inside_bar": "इनसाइड बार",
    "bullish_marubozu": "बुलिस मारुबोजु",
    "bearish_marubozu": "बेयरिस मारुबोजु",
    "morning_star": "मर्निङ स्टार",
    "evening_star": "इभनिङ स्टार",
}

BULLISH = {"bullish_engulfing", "hammer", "bullish_marubozu", "morning_star"}
BEARISH = {"bearish_engulfing", "shooting_star", "bearish_marubozu", "evening_star"}


@dataclass(frozen=True)
class CandleInfo:
    """Description of the latest candle."""

    direction: str  # "bullish" | "bearish" | "neutral"
    body_pct_of_range: float | None
    close_location: float | None  # 0 = closed at low, 1 = closed at high
    patterns: tuple[str, ...]

    @property
    def bias(self) -> str:
        bull = any(p in BULLISH for p in self.patterns)
        bear = any(p in BEARISH for p in self.patterns)
        if bull and not bear:
            return "bullish"
        if bear and not bull:
            return "bearish"
        return "neutral"


def _parts(o: float, h: float, low: float, c: float) -> tuple[float, float, float, float]:
    body = abs(c - o)
    rng = h - low
    upper = h - max(o, c)
    lower = min(o, c) - low
    return body, rng, upper, lower


def detect_patterns(df: pd.DataFrame, t: int, atr_value: float | None) -> CandleInfo:
    """Detect patterns on the bar at integer position ``t`` using bars ``t-2..t`` only."""
    o, h, low, c = (float(df[k].iat[t]) for k in ("open", "high", "low", "close"))
    body, rng, upper, lower = _parts(o, h, low, c)
    direction = "bullish" if c > o else "bearish" if c < o else "neutral"
    found: list[str] = []
    atr_ok = atr_value is not None and np.isfinite(atr_value) and atr_value > 0

    if rng > 0:
        if body <= 0.1 * rng:
            found.append("doji")
        # trend context from the 5-bar change before this bar
        prior_move = None
        if t >= 5:
            prior_move = float(df["close"].iat[t - 1]) - float(df["close"].iat[t - 5])
        if body > 0 and lower >= 2 * body and upper <= 0.25 * rng and prior_move is not None and prior_move < 0:
            found.append("hammer")
        if body > 0 and upper >= 2 * body and lower <= 0.25 * rng and prior_move is not None and prior_move > 0:
            found.append("shooting_star")
        if atr_ok and body >= 0.9 * rng and rng >= atr_value:  # type: ignore[operator]
            found.append("bullish_marubozu" if c > o else "bearish_marubozu")

    if t >= 1:
        po, ph, pl, pc = (float(df[k].iat[t - 1]) for k in ("open", "high", "low", "close"))
        pbody = abs(pc - po)
        if pc < po and c > o and o <= pc and c >= po and body > pbody:
            found.append("bullish_engulfing")
        if pc > po and c < o and o >= pc and c <= po and body > pbody:
            found.append("bearish_engulfing")
        if h < ph and low > pl:
            found.append("inside_bar")

    if t >= 2 and atr_ok:
        o2, c2 = float(df["open"].iat[t - 2]), float(df["close"].iat[t - 2])
        o1, c1 = float(df["open"].iat[t - 1]), float(df["close"].iat[t - 1])
        big2 = abs(c2 - o2) >= 0.6 * atr_value  # type: ignore[operator]
        small1 = abs(c1 - o1) <= 0.3 * atr_value  # type: ignore[operator]
        if big2 and small1 and c2 < o2 and c > o and c > (o2 + c2) / 2:
            found.append("morning_star")
        if big2 and small1 and c2 > o2 and c < o and c < (o2 + c2) / 2:
            found.append("evening_star")

    return CandleInfo(
        direction=direction,
        body_pct_of_range=round(body / rng * 100, 1) if rng > 0 else None,
        close_location=round((c - low) / rng, 2) if rng > 0 else None,
        patterns=tuple(found),
    )
