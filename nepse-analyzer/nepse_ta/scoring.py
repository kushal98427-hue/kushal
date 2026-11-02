"""Transparent setup score (0-100).

This is a *heuristic ranking score*, NOT a probability. Each rule and its
points are listed in ``SCORING_RULES`` and every analysed stock carries a
breakdown of the rules that fired. Whether higher scores actually led to
better outcomes is measured separately by ``nepse_ta.backtest``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# (rule id, points, English description, Nepali description)
SCORING_RULES: tuple[tuple[str, int, str, str], ...] = (
    ("daily_uptrend", 10, "Close > SMA50 and SMA20 > SMA50", "दैनिक अपट्रेन्ड (मूल्य > SMA50, SMA20 > SMA50)"),
    ("sma50_rising", 5, "SMA50 higher than 10 sessions ago", "SMA50 बढ्दो (१० सत्र अघिभन्दा माथि)"),
    ("weekly_uptrend", 10, "Weekly close > 10w SMA > 20w SMA", "साप्ताहिक अपट्रेन्ड"),
    ("rsi_healthy", 10, "RSI(14) between 50 and 70", "RSI ५०–७० (स्वस्थ गति)"),
    ("rsi_neutral", 5, "RSI 40-50 or 70-75", "RSI ४०–५० वा ७०–७५"),
    ("macd_above_signal", 5, "MACD line above signal", "MACD सिग्नलभन्दा माथि"),
    ("macd_hist_rising", 5, "MACD histogram higher than 3 sessions ago", "MACD हिस्टोग्राम बढ्दो"),
    ("breakout_volume", 25, "20-day breakout with volume >= 1.5x average", "२० दिने ब्रेकआउट + भोल्युम ≥ १.५x"),
    ("breakout_no_volume", 15, "20-day breakout without volume confirmation", "ब्रेकआउट (भोल्युम पुष्टि बिना)"),
    ("pullback_in_uptrend", 20, "Pullback to SMA20/support inside uptrend", "अपट्रेन्डभित्र SMA20/सपोर्टमा पुलब्याक"),
    ("bullish_pattern", 5, "Bullish candlestick pattern on the signal bar", "बुलिस क्यान्डलस्टिक प्याटर्न"),
    ("volume_strong", 10, "Up day with volume >= 1.5x average", "बढेको दिन भोल्युम ≥ १.५x"),
    ("volume_ok", 5, "Up day with volume >= 1.0x average", "बढेको दिन भोल्युम ≥ १.०x"),
    ("rr_3", 20, "Reward:risk to Target 1 >= 3", "जोखिम:प्रतिफल (T1) ≥ ३"),
    ("rr_2", 15, "Reward:risk to Target 1 >= 2", "जोखिम:प्रतिफल (T1) ≥ २"),
    ("rr_1_5", 10, "Reward:risk to Target 1 >= 1.5", "जोखिम:प्रतिफल (T1) ≥ १.५"),
    ("rr_1", 5, "Reward:risk to Target 1 >= 1", "जोखिम:प्रतिफल (T1) ≥ १"),
    ("pen_low_liquidity", -10, "Median 20-day turnover below threshold", "कम कारोबार (तरलता कम)"),
    ("pen_short_history", -5, "Fewer than 200 sessions of usable history", "२०० सत्रभन्दा कम इतिहास"),
    ("pen_data_repairs", -5, "More than 5 repaired OHLC rows in last 60 sessions", "पछिल्ला ६० सत्रमा ५+ OHLC सुधार"),
    ("pen_recent_break", -5, "Unexplained price break within last 250 sessions", "पछिल्ला २५० सत्रमा अस्पष्ट मूल्य उछाल/गिरावट"),
    ("pen_overbought", -5, "RSI above 80", "RSI ८० भन्दा माथि (ओभरबट)"),
)
_POINTS = {r[0]: r[1] for r in SCORING_RULES}


@dataclass
class ScoreInputs:
    """Everything the score depends on (all computed from data up to the signal bar)."""

    daily_trend: str
    sma50_rising: bool | None
    weekly_trend: str
    rsi: float | None
    macd_above_signal: bool | None
    macd_hist_rising: bool | None
    setup_type: str
    breakout_volume_confirmed: bool | None
    bullish_pattern: bool
    up_day: bool
    rel_volume: float | None
    volume_reliable: bool
    rr1: float | None
    low_liquidity: bool = False
    short_history: bool = False
    recent_repairs: int = 0
    recent_break: bool = False


@dataclass
class ScoreResult:
    """Score with the list of rules that fired."""

    total: int
    breakdown: list[tuple[str, int]] = field(default_factory=list)

    @property
    def band(self) -> str:
        if self.total >= 70:
            return "strong"
        if self.total >= 55:
            return "moderate"
        if self.total >= 40:
            return "weak"
        return "none"


def compute_score(x: ScoreInputs) -> ScoreResult:
    """Apply ``SCORING_RULES`` to ``x``; clamp to 0..100."""
    fired: list[str] = []
    if x.daily_trend == "uptrend":
        fired.append("daily_uptrend")
    if x.sma50_rising:
        fired.append("sma50_rising")
    if x.weekly_trend == "uptrend":
        fired.append("weekly_uptrend")
    if x.rsi is not None:
        if 50 <= x.rsi <= 70:
            fired.append("rsi_healthy")
        elif 40 <= x.rsi < 50 or 70 < x.rsi <= 75:
            fired.append("rsi_neutral")
        if x.rsi > 80:
            fired.append("pen_overbought")
    if x.macd_above_signal:
        fired.append("macd_above_signal")
    if x.macd_hist_rising:
        fired.append("macd_hist_rising")
    if x.setup_type == "breakout":
        fired.append("breakout_volume" if x.breakout_volume_confirmed else "breakout_no_volume")
    elif x.setup_type == "pullback":
        fired.append("pullback_in_uptrend")
    if x.bullish_pattern:
        fired.append("bullish_pattern")
    if x.volume_reliable and x.up_day and x.rel_volume is not None:
        if x.rel_volume >= 1.5:
            fired.append("volume_strong")
        elif x.rel_volume >= 1.0:
            fired.append("volume_ok")
    if x.rr1 is not None:
        for rid, thr in (("rr_3", 3.0), ("rr_2", 2.0), ("rr_1_5", 1.5), ("rr_1", 1.0)):
            if x.rr1 >= thr:
                fired.append(rid)
                break
    if x.low_liquidity:
        fired.append("pen_low_liquidity")
    if x.short_history:
        fired.append("pen_short_history")
    if x.recent_repairs > 5:
        fired.append("pen_data_repairs")
    if x.recent_break:
        fired.append("pen_recent_break")
    breakdown = [(rid, _POINTS[rid]) for rid in fired]
    total = max(0, min(100, sum(p for _, p in breakdown)))
    return ScoreResult(total=total, breakdown=breakdown)


def score_bucket(score: int) -> str:
    """Bucket label used for backtest calibration."""
    if score >= 70:
        return "70-100"
    if score >= 60:
        return "60-69"
    if score >= 50:
        return "50-59"
    if score >= 40:
        return "40-49"
    return "0-39"
