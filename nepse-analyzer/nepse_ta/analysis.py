"""Per-stock technical analysis at a given bar.

``analyze_at(frame, t, ...)`` only reads rows ``<= t`` of the precomputed
(causal) indicator frame, so the exact same function powers both the live scan
(``t = last bar``) and the backtest (``t = every historical candidate bar``).

NEPSE does not allow short selling, so all trade plans are long-only. Bearish
analysis is expressed as scenarios / risk warnings for holders.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import pandas as pd

from nepse_ta.config import AnalysisConfig, DataConfig
from nepse_ta.indicators import add_indicators, confirmed_pivots, to_weekly
from nepse_ta.levels import Zone, build_zones, split_levels
from nepse_ta.patterns import PATTERN_NP, detect_patterns
from nepse_ta.scoring import ScoreInputs, compute_score

SETUP_TYPES = ("breakout", "pullback")  # actionable today
PLAN_NP = {
    "breakout": "ब्रेकआउट",
    "pullback": "अपट्रेन्ड पुलब्याक",
    "watch_breakout": "निगरानी (ब्रेकआउट पर्खने)",
    "none": "सेटअप छैन",
}
TREND_NP = {"uptrend": "अपट्रेन्ड", "downtrend": "डाउनट्रेन्ड", "sideways": "साइडवेज", "insufficient": "अपर्याप्त डाटा"}
STATUS_NP = {
    "breakout": "ब्रेकआउट",
    "breakdown": "ब्रेकडाउन",
    "consolidation": "कन्सोलिडेसन",
    "range": "दायराभित्र",
    "insufficient": "अपर्याप्त डाटा",
}


@dataclass
class Frame:
    """Precomputed causal indicators + confirmed pivots for one contiguous price segment."""

    ind: pd.DataFrame
    pivots: pd.DataFrame


def prepare_frame(df: pd.DataFrame, cfg: AnalysisConfig) -> Frame:
    """Compute all indicators once for a segment."""
    ind = add_indicators(df, cfg)
    return Frame(ind=ind, pivots=confirmed_pivots(ind, cfg.pivot_window))


@dataclass
class TradePlan:
    """Long-only plan. All prices are NPR on the adjusted series (= actual prices for the latest bar)."""

    plan_type: str
    entry_low: float | None = None
    entry_high: float | None = None
    entry_ref: float | None = None
    stop: float | None = None
    stop_basis: str | None = None
    target1: float | None = None
    target1_basis: str | None = None
    target2: float | None = None
    target2_basis: str | None = None
    rr1: float | None = None
    rr2: float | None = None
    trigger: str | None = None  # condition that must happen before entry (watch plans)
    invalidation: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class StockAnalysis:
    """Everything the reports need for one stock."""

    symbol: str
    date: str
    close: float
    change_pct: float | None
    return_20d: float | None
    sessions_used: int
    daily_trend: str
    weekly_trend: str
    sma: dict[str, float | None]
    rsi: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    atr: float | None
    atr_pct: float | None
    volume: float | None
    rel_volume: float | None
    volume_reliable: bool
    median_turnover_20: float | None
    low_liquidity: bool
    candle_direction: str
    candle_close_location: float | None
    patterns: list[str]
    pattern_bias: str
    status: str
    high_52w: float | None
    low_52w: float | None
    supports: list[dict]
    resistances: list[dict]
    plan: TradePlan
    score: int
    score_band: str
    score_breakdown: list[tuple[str, int]]
    scenario_bullish: str
    scenario_bearish: str
    warnings: list[str] = field(default_factory=list)
    # filled by the scan layer
    company_name: str = ""
    sector: str = ""
    group: str = ""
    agent: str = ""
    stale: bool = False
    eligible: bool = False
    ineligible_reasons: list[str] = field(default_factory=list)
    historical_rate: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _f(x: object) -> float | None:
    """Finite float or None (NaN never leaks into reports as a number)."""
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(x, nd)


def classify_daily_trend(close: float | None, s20: float | None, s50: float | None, s50_prev: float | None) -> str:
    """Uptrend / downtrend / sideways from close, SMA20, SMA50 and the SMA50 slope."""
    if close is None or s20 is None or s50 is None or s50_prev is None:
        return "insufficient"
    if close > s50 and s20 > s50 and s50 > s50_prev:
        return "uptrend"
    if close < s50 and s20 < s50 and s50 < s50_prev:
        return "downtrend"
    return "sideways"


def classify_weekly_trend(weekly: pd.DataFrame) -> str:
    """Weekly close vs 10w and 20w SMA, with the 10w slope over 3 weeks."""
    if len(weekly) < 23:
        return "insufficient"
    c = weekly["close"]
    s10 = c.rolling(10).mean()
    s20 = c.rolling(20).mean()
    last, a, b, a_prev = c.iloc[-1], s10.iloc[-1], s20.iloc[-1], s10.iloc[-4]
    if last > a > b and a > a_prev:
        return "uptrend"
    if last < a < b and a < a_prev:
        return "downtrend"
    return "sideways"


def _stop(entry_low: float, entry_ref: float, supports: list[Zone], atr_v: float, cfg: AnalysisConfig) -> tuple[float, str]:
    vol_stop = entry_ref - cfg.stop_atr_max * atr_v
    below = [z for z in supports if z.high < entry_low]
    if below:
        structural = below[0].low - 0.25 * atr_v
        if structural >= vol_stop:
            stop, basis = structural, f"सपोर्ट {below[0].low:.1f}–{below[0].high:.1f} तल (−0.25 ATR)"
        else:
            stop, basis = vol_stop, f"{cfg.stop_atr_max:g}×ATR (सपोर्ट धेरै तल भएकाले)"
    else:
        stop, basis = vol_stop, f"{cfg.stop_atr_max:g}×ATR (नजिक सपोर्ट नभएकाले)"
    min_stop = entry_ref - cfg.stop_atr_min * atr_v
    if stop > min_stop:
        stop, basis = min_stop, f"न्यूनतम {cfg.stop_atr_min:g}×ATR दूरी"
    return stop, basis


def _targets(
    entry_high: float, entry_ref: float, risk: float, resistances: list[Zone], atr_v: float
) -> tuple[float, str, float, str]:
    above = [z for z in resistances if z.low > entry_high]
    if above:
        t1, b1 = above[0].low, f"रेजिस्टेन्स {above[0].low:.1f}–{above[0].high:.1f}"
    else:
        t1, b1 = entry_ref + 2 * risk, "2R प्रक्षेपण (माथि रेजिस्टेन्स छैन)"
    nxt = [z for z in above[1:] if z.low > t1 + 0.5 * atr_v]
    if nxt:
        t2, b2 = nxt[0].low, f"रेजिस्टेन्स {nxt[0].low:.1f}–{nxt[0].high:.1f}"
    else:
        t2 = max(entry_ref + 3 * risk, t1 + risk)
        b2 = "प्रक्षेपण (3R वा T1+1R)"
    return t1, b1, t2, b2


def _finish_plan(
    plan_type: str,
    entry_low: float,
    entry_high: float,
    supports: list[Zone],
    resistances: list[Zone],
    atr_v: float,
    cfg: AnalysisConfig,
) -> TradePlan:
    entry_ref = (entry_low + entry_high) / 2
    stop, stop_basis = _stop(entry_low, entry_ref, supports, atr_v, cfg)
    risk = entry_ref - stop
    t1, b1, t2, b2 = _targets(entry_high, entry_ref, risk, resistances, atr_v)
    return TradePlan(
        plan_type=plan_type,
        entry_low=entry_low,
        entry_high=entry_high,
        entry_ref=entry_ref,
        stop=stop,
        stop_basis=stop_basis,
        target1=t1,
        target1_basis=b1,
        target2=t2,
        target2_basis=b2,
        rr1=(t1 - entry_ref) / risk if risk > 0 else None,
        rr2=(t2 - entry_ref) / risk if risk > 0 else None,
    )


def analyze_at(
    frame: Frame,
    t: int,
    cfg: AnalysisConfig,
    dcfg: DataConfig,
    symbol: str = "",
    with_text: bool = True,
    recent_break: bool = False,
) -> StockAnalysis | None:
    """Analyse bar ``t`` of ``frame`` using only data up to and including ``t``.

    Returns None if fewer than ``dcfg.min_history`` sessions are available.
    ``recent_break`` is supplied by the caller (an unexplained price break shortly
    before this segment started) and only affects the score penalty.
    """
    ind = frame.ind
    if t + 1 < dcfg.min_history:
        return None
    row = ind.iloc[t]
    close = float(row["close"])
    atr_v = _f(row["atr"])
    warnings: list[str] = []
    sessions = t + 1
    s = {f"sma{n}": _f(row.get(f"sma{n}")) for n in cfg.ma_periods}
    for n in cfg.ma_periods:
        if s[f"sma{n}"] is None:
            warnings.append(f"SMA{n} उपलब्ध छैन ({sessions} सत्र मात्र)")
    s50_prev = _f(ind["sma50"].iat[t - 10]) if t >= 10 else None
    daily_trend = classify_daily_trend(close, s["sma20"], s["sma50"], s50_prev)

    lo = max(0, t - 420)
    weekly = to_weekly(ind.iloc[lo : t + 1])
    weekly_trend = classify_weekly_trend(weekly)

    rsi_v = _f(row["rsi"])
    macd_v, sig_v, hist_v = _f(row["macd"]), _f(row["macd_signal"]), _f(row["macd_hist"])
    hist_prev = _f(ind["macd_hist"].iat[t - 3]) if t >= 3 else None

    vol_window = ind["volume"].iloc[max(0, t - 59) : t + 1]
    missing_frac = float(vol_window.isna().mean()) if len(vol_window) else 1.0
    volume_reliable = missing_frac <= dcfg.max_missing_volume_frac
    if not volume_reliable:
        warnings.append(f"भोल्युम डाटा अपूर्ण ({missing_frac:.0%} हराएको) — भोल्युम विश्लेषण बन्द")
    rel_vol = _f(row["rel_volume"]) if volume_reliable else None
    turnover = ind["turnover"].iloc[max(0, t - 19) : t + 1]
    med_turn = _f(turnover.median()) if turnover.notna().sum() >= 10 else None
    low_liq = med_turn is not None and med_turn < dcfg.min_median_turnover_npr
    if med_turn is None:
        warnings.append("कारोबार रकम (turnover) डाटा अपर्याप्त")
    elif low_liq:
        warnings.append(f"कम तरलता: २० दिनको मध्य कारोबार रु. {med_turn:,.0f}")

    candle = detect_patterns(ind, t, atr_v)
    prev_close = float(ind["close"].iat[t - 1]) if t >= 1 else None
    change_pct = (close / prev_close - 1) * 100 if prev_close else None

    prior_high, prior_low = _f(row["prior_high"]), _f(row["prior_low"])
    rng_hi, rng_lo = _f(row["range_high"]), _f(row["range_low"])
    if prior_high is None or atr_v is None or rng_hi is None or rng_lo is None or prior_low is None:
        status = "insufficient"
    elif close > prior_high:
        status = "breakout"
    elif close < prior_low:
        status = "breakdown"
    elif rng_hi - rng_lo <= cfg.consolidation_range_atr * atr_v:
        status = "consolidation"
    else:
        status = "range"

    win = ind.iloc[max(0, t - 249) : t + 1]
    high_52w, low_52w = float(win["high"].max()), float(win["low"].min())

    zones = build_zones(ind, frame.pivots, t, atr_v or 0.0, cfg.level_lookback, cfg.zone_merge_atr) if atr_v else []
    supports, resistances = split_levels(zones, close)

    # ---- plan ---------------------------------------------------------------
    plan = TradePlan(plan_type="none")
    vol_confirmed: bool | None = None
    if atr_v is not None and status != "insufficient":
        trend_ok_ref = s["sma50"] if s["sma50"] is not None else s["sma20"]
        low_t = float(row["low"])
        near_support = bool(supports) and low_t <= supports[0].high + 0.25 * atr_v
        near_sma20 = s["sma20"] is not None and low_t <= s["sma20"] + 0.25 * atr_v
        if (
            status == "breakout"
            and daily_trend != "downtrend"
            and trend_ok_ref is not None
            and close > trend_ok_ref
        ):
            level = prior_high  # type: ignore[assignment]
            plan = _finish_plan(
                "breakout", level, level + cfg.entry_zone_atr * atr_v, supports, resistances, atr_v, cfg
            )
            if rel_vol is not None:
                vol_confirmed = rel_vol >= cfg.breakout_volume_mult
            plan.invalidation = [
                f"दैनिक बन्द {level - 0.25 * atr_v:.1f} (ब्रेकआउट लेभल −0.25 ATR) भन्दा तल",
                f"स्टप-लस {plan.stop:.1f} छोएमा",
            ]
            if close > plan.entry_high:  # type: ignore[operator]
                plan.notes.append("मूल्य इन्ट्री जोनभन्दा माथि छ — पछ्याएर नकिन्ने, जोनमा फर्किए मात्र")
            if vol_confirmed is False:
                plan.notes.append("भोल्युमले ब्रेकआउट पुष्टि गरेको छैन")
            elif vol_confirmed is None:
                plan.notes.append("भोल्युम पुष्टि गर्न सकिएन (डाटा अपूर्ण)")
        elif (
            daily_trend == "uptrend"
            and (near_sma20 or near_support)
            and s["sma50"] is not None
            and close >= s["sma50"]
            and rsi_v is not None
            and 40 <= rsi_v <= 60
            and (close > float(row["open"]) or candle.bias == "bullish")
        ):
            plan = _finish_plan(
                "pullback", close - cfg.entry_zone_atr * atr_v, close, supports, resistances, atr_v, cfg
            )
            plan.invalidation = [
                f"दैनिक बन्द SMA50 ({s['sma50']:.1f}) भन्दा तल",
                f"स्टप-लस {plan.stop:.1f} छोएमा",
            ]
        else:
            level = resistances[0].low if resistances else prior_high
            if level is not None and level > close:
                plan = _finish_plan(
                    "watch_breakout", level, level + cfg.entry_zone_atr * atr_v, supports, resistances, atr_v, cfg
                )
                cond = f"दैनिक बन्द {level:.1f} माथि"
                if daily_trend == "downtrend" and s["sma50"] is not None:
                    cond += f" र SMA50 ({s['sma50']:.1f}) माथि"
                plan.trigger = cond + (" (भोल्युम ≥ १.५x सहित)" if volume_reliable else "")
                plan.invalidation = ["ट्रिगर नभएसम्म इन्ट्री नगर्ने", f"ट्रिगरपछि स्टप-लस {plan.stop:.1f}"]
            else:
                plan.notes.append("स्पष्ट ट्रिगर लेभल छैन")

    recent_repairs = int(ind["ohlc_repaired"].iloc[max(0, t - 59) : t + 1].sum()) if "ohlc_repaired" in ind else 0
    if recent_repairs:
        warnings.append(f"पछिल्ला ६० सत्रमा {recent_repairs} वटा OHLC पङ्क्ति सुधार गरिएको")
    short_history = sessions < 200

    sc = compute_score(
        ScoreInputs(
            daily_trend=daily_trend,
            sma50_rising=(s["sma50"] > s50_prev) if (s["sma50"] is not None and s50_prev is not None) else None,
            weekly_trend=weekly_trend,
            rsi=rsi_v,
            macd_above_signal=(macd_v > sig_v) if (macd_v is not None and sig_v is not None) else None,
            macd_hist_rising=(hist_v > hist_prev) if (hist_v is not None and hist_prev is not None) else None,
            setup_type=plan.plan_type,
            breakout_volume_confirmed=vol_confirmed,
            bullish_pattern=candle.bias == "bullish",
            up_day=change_pct is not None and change_pct > 0,
            rel_volume=rel_vol,
            volume_reliable=volume_reliable,
            rr1=plan.rr1 if plan.plan_type in SETUP_TYPES else None,
            low_liquidity=low_liq,
            short_history=short_history,
            recent_repairs=recent_repairs,
            recent_break=recent_break,
        )
    )

    bull, bear = ("", "")
    if with_text:
        bull, bear = _scenarios(close, supports, resistances, s, atr_v, plan)

    def _rp(p: TradePlan) -> TradePlan:
        for k in ("entry_low", "entry_high", "entry_ref", "stop", "target1", "target2"):
            setattr(p, k, _r(getattr(p, k)))
        p.rr1, p.rr2 = _r(p.rr1), _r(p.rr2)
        return p

    return StockAnalysis(
        symbol=symbol,
        date=ind.index[t].strftime("%Y-%m-%d"),
        close=round(close, 2),
        change_pct=_r(change_pct),
        return_20d=_r((close / float(ind["close"].iat[t - 20]) - 1) * 100) if t >= 20 else None,
        sessions_used=sessions,
        daily_trend=daily_trend,
        weekly_trend=weekly_trend,
        sma={k: _r(v) for k, v in s.items()},
        rsi=_r(rsi_v, 1),
        macd=_r(macd_v, 3),
        macd_signal=_r(sig_v, 3),
        macd_hist=_r(hist_v, 3),
        atr=_r(atr_v),
        atr_pct=_r(atr_v / close * 100) if atr_v else None,
        volume=_f(row["volume"]),
        rel_volume=_r(rel_vol),
        volume_reliable=volume_reliable,
        median_turnover_20=_r(med_turn, 0),
        low_liquidity=low_liq,
        candle_direction=candle.direction,
        candle_close_location=candle.close_location,
        patterns=list(candle.patterns),
        pattern_bias=candle.bias,
        status=status,
        high_52w=round(high_52w, 2),
        low_52w=round(low_52w, 2),
        supports=[z.as_dict() for z in supports[:3]],
        resistances=[z.as_dict() for z in resistances[:3]],
        plan=_rp(plan),
        score=sc.total,
        score_band=sc.band,
        score_breakdown=sc.breakdown,
        scenario_bullish=bull,
        scenario_bearish=bear,
        warnings=warnings,
    )


def _scenarios(
    close: float,
    supports: list[Zone],
    resistances: list[Zone],
    s: dict[str, float | None],
    atr_v: float | None,
    plan: TradePlan,
) -> tuple[str, str]:
    """Build bullish / bearish scenario sentences strictly from computed levels."""
    if resistances:
        r = resistances[0]
        nxt = f"{resistances[1].low:.1f}" if len(resistances) > 1 else (f"{plan.target1:.1f}" if plan.target1 else "")
        bull = f"{r.high:.1f} माथि दैनिक बन्द भए अर्को अवरोध {nxt} तर्फ बाटो खुल्छ।" if nxt else (
            f"{r.high:.1f} माथि दैनिक बन्द भए माथि ऐतिहासिक अवरोध देखिँदैन।"
        )
    else:
        bull = f"मूल्य {close:.1f} विश्लेषण अवधिको अवरोधभन्दा माथि छ; बलियो बन्द कायम रहे ट्रेन्ड जारी रहन सक्छ।"
    if supports:
        sp = supports[0]
        nxt_s = f"{supports[1].high:.1f}" if len(supports) > 1 else None
        bear = f"{sp.low:.1f} तल दैनिक बन्द भए कमजोरी बढ्छ" + (f"; अर्को सपोर्ट {nxt_s}।" if nxt_s else "।")
    elif s.get("sma50"):
        bear = f"SMA50 ({s['sma50']:.1f}) तल बन्द भए ट्रेन्ड कमजोर मानिन्छ।"
    else:
        bear = "नजिक पुष्टि भएको सपोर्ट छैन — गिरावटमा जोखिम बढी।"
    return bull, bear


def pattern_names_np(patterns: list[str]) -> str:
    """Comma-separated Nepali names for patterns."""
    return ", ".join(PATTERN_NP.get(p, p) for p in patterns) or "—"

