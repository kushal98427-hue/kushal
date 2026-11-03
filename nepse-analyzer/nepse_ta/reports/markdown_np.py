"""Nepali Markdown reports: master, five sector-agent reports, and a combined report."""

from __future__ import annotations

from pathlib import Path

from nepse_ta.agents.sector_agent import AgentReport, GroupStats
from nepse_ta.freshness import banner_np
from nepse_ta.analysis import PLAN_NP, STATUS_NP, TREND_NP, StockAnalysis, pattern_names_np
from nepse_ta.scan import ScanResult
from nepse_ta.scoring import SCORING_RULES
from nepse_ta.sectors import AGENT_TITLES_NP, SECTOR_NP, UNCLASSIFIED

RULE_NP = {r[0]: r[3] for r in SCORING_RULES}
BAND_NP = {"strong": "बलियो", "moderate": "मध्यम", "weak": "कमजोर", "none": "सेटअप छैन"}
CANDLE_NP = {"bullish": "बुलिस (हरियो)", "bearish": "बेयरिस (रातो)", "neutral": "तटस्थ"}
FRESH_NP = {
    "current": "✅ ताजा (पछिल्लो सत्र)",
    "stale": "⚠️ STALE — पछिल्लो सत्रको डाटा छैन",
    "blocked": "⛔ धेरै पुरानो — सेटअप रोकिएको",
}

DISCLAIMER = (
    "> ⚠️ **महत्त्वपूर्ण:** यो सार्वजनिक OHLC डाटाबाट स्वचालित रूपमा बनेको शैक्षिक प्राविधिक विश्लेषण हो, "
    "लगानी सल्लाह होइन। **\"सेटअप स्कोर\" सम्भाव्यता (probability) होइन** — यो पारदर्शी नियममा आधारित "
    "क्रम-स्कोर मात्र हो। आफ्नो जोखिम क्षमता हेरेर मात्र निर्णय गर्नुहोस्; स्टप-लस सधैं प्रयोग गर्नुहोस्।"
)


def f(x: float | None, nd: int = 1, pct: bool = False, sign: bool = False) -> str:
    """Format a number or '—' (never prints NaN or invents zeros)."""
    if x is None:
        return "—"
    s = f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"
    return s + ("%" if pct else "")


def sec(name: str) -> str:
    return SECTOR_NP.get(name, name)


def _zone(z: dict) -> str:
    lo, hi = z["low"], z["high"]
    rng = f"{lo:,.1f}" if abs(hi - lo) < 0.05 else f"{lo:,.1f}–{hi:,.1f}"
    return f"{rng} ({z['touches']}×)"


def _header(res: ScanResult, title: str) -> list[str]:
    calib = (
        "T1 हिट दरको walk-forward जाँच पास — ऐतिहासिक दर देखाइएको छ, तर यो सम्भाव्यता वा नाफाको संकेत होइन"
        if res.calibration
        else "**Calibrated छैन** — कुनै दर/सम्भाव्यता देखाइएको छैन, 'सेटअप स्कोर' र 'परिदृश्य' मात्र"
    )
    lines = [
        f"# {title} — डाटा मिति {res.market_date or '—'}",
        "",
        f"> {banner_np(res.fresh)}" if res.fresh else "",
        "",
    ]
    exp_warn = expectancy_banner(res)
    if exp_warn:
        lines += [f"> {exp_warn}", ""]
    return lines + [
        f"- **डाटा मिति (अन्तिम उपलब्ध कारोबार दिन):** {res.market_date or '—'}",
        f"- **रिपोर्ट बनेको:** {res.run_at_seoul} ({res.run_at_utc} UTC)",
        f"- **डाटा ताजापन:** {FRESH_NP[res.freshness]} — नेपाल मितिअनुसार {res.data_age_days} दिन पुरानो"
        + (f", अपेक्षित पछिल्लो सत्र {res.fresh.expected_session}" if res.fresh else ""),
        "- **स्रोत:** github.com/Aabishkar2/nepse-data (`main`, data/company-wise)"
        + (f", commit `{res.source.commit_sha[:10]}`" if res.source.commit_sha else ""),
        f"- **ऐतिहासिक दर स्थिति:** {calib}",
        "",
        DISCLAIMER,
        "",
    ]


def expectancy_banner(res: ScanResult) -> str | None:
    """Prominent top-of-report warning when the rules have not made money historically."""
    bt = res.backtest or {}
    e = bt.get("summary_eligible_rule") or {}
    if not e.get("trades"):
        return "⚠️ **ब्याकटेस्ट प्रमाण उपलब्ध छैन** — यी नियम विगतमा नाफामूलक थिए भन्ने कुनै प्रमाण छैन।"
    if (e.get("expectancy_r") or 0) <= 0:
        return (
            f"🔻 **ऐतिहासिक नतिजा नकारात्मक:** यिनै नियमका मास्टर-सूची सेटअपहरू ({e['trades']} ट्रेड, "
            f"{bt.get('period', {}).get('start')}–{bt.get('period', {}).get('end')}) को लागतपछि औसत नतिजा "
            f"**{e['expectancy_r']}R** (profit factor {e.get('profit_factor')}) रह्यो। "
            "त्यसैले यो सूची **किन्ने सिफारिस होइन**, अध्ययनका लागि स्क्रिनिङ मात्र हो।"
        )
    return None


def _plan_cells(a: StockAnalysis) -> tuple[str, str, str, str, str]:
    p = a.plan
    entry = f"{f(p.entry_low)}–{f(p.entry_high)}" if p.entry_low is not None else "—"
    rr = f"{f(p.rr1, 2)} / {f(p.rr2, 2)}" if p.rr1 is not None else "—"
    return entry, f(p.stop), f(p.target1), f(p.target2), rr


def setups_table(items: list[StockAnalysis], with_sector: bool = True) -> list[str]:
    head = "| # | स्टक | " + ("क्षेत्र | " if with_sector else "") + "सेटअप | बन्द | इन्ट्री जोन | स्टप-लस | T1 | T2 | R:R (T1/T2) | स्कोर |"
    sep = "|" + "---|" * (11 if with_sector else 10)
    rows = [head, sep]
    for i, a in enumerate(items, 1):
        entry, stop, t1, t2, rr = _plan_cells(a)
        rows.append(
            f"| {i} | **{a.symbol}** | "
            + (f"{sec(a.group)} | " if with_sector else "")
            + f"{PLAN_NP[a.plan.plan_type]} | {f(a.close)} | {entry} | {stop} | {t1} | {t2} | {rr} | {a.score} |"
        )
    return rows


def watch_table(items: list[StockAnalysis]) -> list[str]:
    rows = ["| स्टक | क्षेत्र | बन्द | ट्रिगर (पहिले यो हुनुपर्छ) | स्टप | T1 | R:R | स्कोर |", "|---|---|---|---|---|---|---|---|"]
    for a in items:
        trig = a.plan.trigger or PLAN_NP[a.plan.plan_type]
        rows.append(
            f"| {a.symbol} | {sec(a.group)} | {f(a.close)} | {trig} | {f(a.plan.stop)} | {f(a.plan.target1)} | "
            f"{f(a.plan.rr1, 2)} | {a.score} |"
        )
    return rows


def group_table(groups: list[tuple[str, GroupStats]]) -> list[str]:
    rows = [
        "| क्षेत्र | स्टक | अपट्रेन्ड | डाउनट्रेन्ड | SMA50 माथि | SMA200 माथि | मध्य RSI | २० दिने मध्य प्रतिफल | औसत स्कोर | ब्रेकआउट | ब्रेकडाउन | मान्य सेटअप |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for label, g in groups:
        rows.append(
            f"| {label} | {g.n} | {g.n_uptrend} | {g.n_downtrend} | {f(g.pct_above_sma50, pct=True)} | "
            f"{f(g.pct_above_sma200, pct=True)} | {f(g.median_rsi)} | {f(g.median_return_20d, 2, True, True)} | "
            f"{f(g.avg_score)} | {g.n_breakouts} | {g.n_breakdowns} | {g.n_valid_setups} |"
        )
    return rows


def compact_table(items: list[StockAnalysis]) -> list[str]:
    rows = [
        "| स्टक | मिति | बन्द | दैनिक % | ट्रेन्ड (दै/सा) | RSI | स्थिति | नजिकको सपोर्ट | नजिकको रेजिस्टेन्स | योजना | स्कोर |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in items:
        s1 = _zone(a.supports[0]) if a.supports else "—"
        r1 = _zone(a.resistances[0]) if a.resistances else "—"
        flag = " ⚠️" if a.stale or a.low_liquidity else ""
        rows.append(
            f"| {a.symbol}{flag} | {a.date} | {f(a.close)} | {f(a.change_pct, 2, True, True)} | "
            f"{TREND_NP[a.daily_trend]} / {TREND_NP[a.weekly_trend]} | {f(a.rsi)} | {STATUS_NP[a.status]} | "
            f"{s1} | {r1} | {PLAN_NP[a.plan.plan_type]} | {a.score} |"
        )
    return rows


def stock_detail(a: StockAnalysis) -> list[str]:
    """All 14 required items for one stock."""
    p = a.plan
    sma = " · ".join(f"{k.upper()}: {f(v)}" for k, v in a.sma.items())
    sup = ", ".join(_zone(z) for z in a.supports) or "—"
    res = ", ".join(_zone(z) for z in a.resistances) or "—"
    vol = f"{f(a.rel_volume, 2)}x (२० दिन औसतको तुलनामा)" if a.volume_reliable else "भरपर्दो छैन"
    breakdown = ", ".join(f"{RULE_NP.get(k, k)} {v:+d}" for k, v in a.score_breakdown) or "कुनै नियम लागू भएन"
    lines = [
        f"#### {a.symbol} — {a.company_name or 'नाम उपलब्ध छैन'}",
        "",
        f"1. **अन्तिम प्रमाणित मिति / बन्द मूल्य:** {a.date} · रु. {f(a.close, 2)} ({f(a.change_pct, 2, True, True)}) · "
        f"२० दिने प्रतिफल {f(a.return_20d, 2, True, True)} · ५२ हप्ता दायरा {f(a.low_52w)}–{f(a.high_52w)}",
        f"2. **ट्रेन्ड:** दैनिक {TREND_NP[a.daily_trend]} · साप्ताहिक {TREND_NP[a.weekly_trend]}",
        f"3. **क्यान्डल:** {CANDLE_NP[a.candle_direction]}, दायराभित्र बन्द स्थान {f(a.candle_close_location, 2)} "
        f"(०=न्यून, १=उच्च) · प्याटर्न: {pattern_names_np(a.patterns)}",
        f"4. **सपोर्ट:** {sup} · **रेजिस्टेन्स:** {res}",
        f"5. **स्थिति:** {STATUS_NP[a.status]}",
        f"6. **मुभिङ एभरेज:** {sma}",
        f"7. **RSI(14):** {f(a.rsi)} · **MACD:** {f(a.macd, 2)} / सिग्नल {f(a.macd_signal, 2)} "
        f"(हिस्टो {f(a.macd_hist, 2, sign=True)}) · **ATR(14):** {f(a.atr, 2)} ({f(a.atr_pct, 2, True)}) · **भोल्युम:** {vol}",
    ]
    if p.entry_low is not None:
        trig = f" — **ट्रिगर:** {p.trigger}" if p.trigger else ""
        lines += [
            f"8. **योजना:** {PLAN_NP[p.plan_type]}{trig} · **इन्ट्री जोन:** {f(p.entry_low)}–{f(p.entry_high)} · "
            f"**अमान्य हुने अवस्था:** {'; '.join(p.invalidation) or '—'}",
            f"9. **स्टप-लस:** {f(p.stop)} ({p.stop_basis})",
            f"10. **T1:** {f(p.target1)} ({p.target1_basis}) · **T2:** {f(p.target2)} ({p.target2_basis})",
            f"11. **जोखिम:प्रतिफल:** T1 {f(p.rr1, 2)} · T2 {f(p.rr2, 2)}",
        ]
    else:
        lines += [f"8–11. **योजना:** {PLAN_NP[p.plan_type]} — {'; '.join(p.notes) or 'स्पष्ट लेभल छैन'}"]
    lines += [
        f"12. **बुलिस परिदृश्य:** {a.scenario_bullish} · **बेयरिस परिदृश्य:** {a.scenario_bearish}",
        f"13. **सेटअप स्कोर:** {a.score}/100 ({BAND_NP[a.score_band]}) — {breakdown}",
    ]
    if a.historical_rate and a.historical_rate.get("sufficient_sample"):
        hr = a.historical_rate
        lines.append(
            f"    - ऐतिहासिक T1 हिट दर (यही स्कोर समूह, backtest): {hr['t1_hit_rate_pct']}% "
            f"(95% CI {hr['ci95'][0]}–{hr['ci95'][1]}%, n={hr['n']}) · लागतपछि औसत नतिजा {hr['expectancy_r']}R"
        )
    warn = list(a.warnings) + [f"सूचीमा नपर्ने कारण: {', '.join(a.ineligible_reasons)}"] * bool(
        a.ineligible_reasons and a.plan.plan_type in ("breakout", "pullback")
    )
    lines.append(f"14. **डाटा चेतावनी:** {' · '.join(warn) if warn else 'छैन'}")
    if p.notes and p.entry_low is not None:
        lines.append(f"    - नोट: {' · '.join(p.notes)}")
    lines.append("")
    return lines


def agent_markdown(res: ScanResult, r: AgentReport) -> str:
    out = _header(res, f"{r.title} — दैनिक रिपोर्ट")
    o = r.overall
    out += [
        "## सारांश",
        "",
        f"- विश्लेषण गरिएका स्टक: **{o.n}** (पुरानो डाटा भएका {len(r.stale)} अलग)",
        f"- दैनिक अपट्रेन्ड: {o.n_uptrend} · डाउनट्रेन्ड: {o.n_downtrend} · SMA50 माथि: {f(o.pct_above_sma50, pct=True)} · "
        f"SMA200 माथि: {f(o.pct_above_sma200, pct=True)}",
        f"- ब्रेकआउट: {o.n_breakouts} · ब्रेकडाउन: {o.n_breakdowns} · **मान्य सेटअप: {len(r.setups)}**",
        "",
        "## समूहगत तुलना",
        "",
        *group_table([(sec(g.group), g) for g in r.groups]),
        "",
    ]
    if r.comparison:
        out += [*(f"- {c}" for c in r.comparison), ""]
    out += ["## मान्य सेटअपहरू", ""]
    if r.setups:
        out += [*setups_table(r.setups, with_sector=len(r.groups) > 1), ""]
    else:
        out += [f"**यो डाटा मिति ({res.market_date}) मा यस क्षेत्रमा मान्य सेटअप छैन।** (No valid setup)", ""]
    if r.watchlist:
        out += ["## निगरानी सूची (अहिले सेटअप होइन — ट्रिगर पर्खनुहोस्)", "", *watch_table(r.watchlist), ""]
    if r.breakdowns:
        out += [
            "## ब्रेकडाउन भएका (होल्डरका लागि जोखिम सङ्केत)",
            "",
            ", ".join(f"{a.symbol} ({f(a.change_pct, 2, True, True)})" for a in r.breakdowns),
            "",
        ]
    out += ["## सबै स्टक (छोटो तालिका)", "", *compact_table(r.analyses), ""]
    if r.stale:
        out += ["### पुरानो डाटा (stale)", "", *compact_table(r.stale), ""]
    out += ["## स्टकअनुसार विस्तृत विश्लेषण", ""]
    for a in r.analyses + r.stale:
        out += stock_detail(a)
    if r.warnings:
        out += ["## चेतावनी", "", *(f"- {w}" for w in r.warnings), ""]
    return "\n".join(out) + "\n"


def master_markdown(res: ScanResult, include_agents: bool = False) -> str:
    m = res.master
    title = "NEPSE दैनिक प्राविधिक विश्लेषण — पूर्ण रिपोर्ट" if include_agents else "मास्टर एजेन्ट — बजारव्यापी शीर्ष सेटअप"
    out = _header(res, title)
    n_total = len(res.analyses)
    n_setups = sum(len(r.setups) for r in res.agent_reports)
    out += [
        f"## निष्कर्ष (डाटा मिति {res.market_date})",
        "",
        f"- विश्लेषण गरिएका इक्विटी/म्युचुअल फण्ड: **{n_total}** · पाँच एजेन्टमा मान्य सेटअप: **{n_setups}**",
        "- मान्य सेटअपको मापदण्ड: ब्रेकआउट वा अपट्रेन्ड पुलब्याक, R:R (T1) ≥ 1.5, स्कोर ≥ 60, पर्याप्त तरलता, स्टकको डाटा stale नभएको, बजार डाटा BLOCKED नभएको",
    ]
    if m.blocked_reason:
        out += [f"- ⛔ **सेटअप सूची रोकिएको:** {m.blocked_reason}"]
    out += [*(f"- {n}" for n in m.notes), ""]
    out += ["## पुष्टि भएका मान्य सेटअप (Confirmed setups — सबै क्षेत्र)", ""]
    if m.top_setups:
        out += [*setups_table(m.top_setups), "", "### शीर्ष सेटअपको विस्तृत विवरण", ""]
        for a in m.top_setups:
            out += stock_detail(a)
    else:
        out += [f"### ❌ कुनै मान्य सेटअप छैन — No valid setup ({res.market_date} को डाटा)", "", "बजारले स्पष्ट प्राविधिक अवसर नदिएको दिन पर्खनु पनि रणनीति हो।", ""]
    if m.watchlist:
        out += ["## निगरानी सूची (सेटअप होइन — ट्रिगर पूरा भए मात्र विचार गर्ने)", "", *watch_table(m.watchlist), ""]
    out += [
        "## क्षेत्रगत प्राविधिक बल (बलियोदेखि कमजोर)",
        "",
        "_बल = (SMA50 माथि भएका % + औसत स्कोर) ÷ २ — क्रम मिलाउन मात्र प्रयोग गरिएको_",
        "",
        *group_table([(sec(g.group), g) for _, g in m.sector_ranking]),
        "",
        "## एजेन्ट अनुसार सारांश",
        "",
        "| एजेन्ट | स्टक | अपट्रेन्ड | SMA50 माथि | औसत स्कोर | मान्य सेटअप |",
        "|---|---|---|---|---|---|",
    ]
    for title_a, g, n in m.agent_overview:
        out.append(f"| {title_a} | {g.n} | {g.n_uptrend} | {f(g.pct_above_sma50, pct=True)} | {f(g.avg_score)} | {n} |")
    out.append("")
    ins = next((r for r in res.agent_reports if r.key == "agent4_insurance"), None)
    if ins and ins.comparison:
        out += ["### जीवन बीमा बनाम निर्जीवन बीमा", "", *(f"- {c}" for c in ins.comparison), ""]

    if include_agents:
        for r in res.agent_reports:
            out += [f"## {r.title}", "", *group_table([(sec(g.group), g) for g in r.groups]), ""]
            out += ["**मान्य सेटअप:** " + (", ".join(a.symbol for a in r.setups) or "छैन"), ""]
            out += [*compact_table(r.analyses), ""]
            out += [f"_विस्तृत विश्लेषण: `agents/{r.key}.md`_", ""]
    if res.unclassified:
        out += [
            f"## {AGENT_TITLES_NP[UNCLASSIFIED]}",
            "",
            "यी स्टकको सेक्टर दुई स्रोतमा मेल नखाएकाले वा नभेटिएकाले अनुमान गरिएको छैन; मास्टर सूचीमा समावेश छैनन्।",
            "",
            *compact_table(res.unclassified),
            "",
        ]
    out += backtest_section(res)
    out += data_quality_section(res)
    out += methodology_section()
    return "\n".join(out) + "\n"


def unclassified_markdown(res: ScanResult) -> str:
    out = _header(res, AGENT_TITLES_NP[UNCLASSIFIED])
    out += ["सेक्टर पुष्टि नभएका स्टक (अनुमान गरिएको छैन)।", ""]
    if res.unclassified:
        out += [*compact_table(res.unclassified), ""]
        for a in res.unclassified:
            out += stock_detail(a)
    else:
        out += ["छैन।", ""]
    return "\n".join(out) + "\n"


def backtest_section(res: ScanResult) -> list[str]:
    """Historical evidence for the rules, shown every day so scores are read in context."""
    bt = res.backtest
    out = ["## ब्याकटेस्ट प्रमाण (यी नियम विगतमा कस्ता रहे?)", ""]
    if not bt or not bt.get("summary_all", {}).get("trades"):
        return out + ["ब्याकटेस्ट नतिजा उपलब्ध छैन — `python -m nepse_ta backtest` चलाउनुहोस्।", ""]
    e, a = bt.get("summary_eligible_rule", {}), bt["summary_all"]
    period = bt.get("period", {})
    out += [
        f"- अवधि {period.get('start')} → {period.get('end')}, {bt.get('symbols_tested')} स्टक, लागत (कमिसन, SEBON, DP, स्लिपेज, CGT) सहित।",
        f"- **मास्टर मापदण्डका सेटअप:** {e.get('trades', 0)} ट्रेड · जित दर {e.get('win_rate_pct')}% · "
        f"T1 हिट {e.get('t1_hit_rate_pct')}% · औसत नेट प्रतिफल {e.get('avg_return_pct')}% · expectancy {e.get('expectancy_r')}R · "
        f"profit factor {e.get('profit_factor')}",
        f"- सबै सेटअप: {a.get('trades')} ट्रेड · expectancy {a.get('expectancy_r')}R · profit factor {a.get('profit_factor')}",
        f"- Walk-forward calibration: {'पास' if bt.get('calibrated') else 'पास भएन'} "
        f"(OOS त्रुटि {bt.get('walk_forward', {}).get('weighted_oos_error_pp')} pp)",
    ]
    if (e.get("expectancy_r") or 0) <= 0:
        out.append(
            "- ⚠️ **ऐतिहासिक रूपमा यी सेटअपको औसत नतिजा लागतपछि शून्य वा नकारात्मक छ।** "
            "यसलाई 'किन्ने सिग्नल' होइन, अध्ययन/स्क्रिनिङ सूची मात्र मान्नुहोस्।"
        )
    out += [
        "- नोट: उच्च स्कोरमा T1 टाढा हुने भएकाले T1 हिट दर घट्छ तर expectancy सुध्रिन्छ — दुवै सँगै हेर्नुहोस्।",
        "",
    ]
    return out


def data_quality_section(res: ScanResult) -> list[str]:
    q = res.quality_totals
    out = [
        "## डाटा गुणस्तर र चेतावनी",
        "",
        *(f"- {w}" for w in res.global_warnings),
        f"- फाइलहरूमा भेटिएका समस्या (सबै इतिहास): दोहोरिएका मिति {q.get('duplicate_date_rows', 0)}, "
        f"OHLC असङ्गत पङ्क्ति (सुधार गरिएको) {q.get('ohlc_repaired_rows', 0)}, अमान्य मूल्य पङ्क्ति हटाइएको "
        f"{q.get('non_numeric_price_rows', 0) + q.get('non_positive_price_rows', 0) + q.get('bad_date_rows', 0)}, "
        f"शून्य/हराएको भोल्युम {q.get('missing_volume_rows', 0)}",
        f"- बोनस/हकप्रद समायोजन पत्ता लागेको: {q.get('adjustment_events', 0)} पटक · अस्पष्ट मूल्य ब्रेक: {q.get('unexplained_breaks', 0)} पटक",
        "- ⚠️ स्रोत डाटा बोनस/हकप्रदका लागि समायोजित हुँदैन। यो प्रणालीले `per_change` स्तम्भबाट समायोजन पत्ता लगाउँछ; "
        "सानो बोनस वा लामो कारोबार बन्दको बेला समायोजन छुट्न सक्छ।",
        f"- डिबेन्चर (विश्लेषणबाट हटाइएको): {len(res.excluded_instruments)} · निष्क्रिय/डिलिस्टेड (१२० दिनभन्दा पुरानो डाटा): {len(res.inactive)}",
    ]
    if res.inactive:
        out.append("  - " + ", ".join(f"{s} ({d})" for s, d in res.inactive))
    if res.failures:
        out.append("- विश्लेषण हुन नसकेका: " + ", ".join(f"{s} ({m})" for s, m in sorted(res.failures.items())))
    out.append("")
    return out


def methodology_section() -> list[str]:
    out = [
        "## विधि (सेटअप स्कोरका नियम)",
        "",
        "| नियम | अङ्क | विवरण |",
        "|---|---|---|",
        *(f"| `{r[0]}` | {r[1]:+d} | {r[3]} |" for r in SCORING_RULES),
        "",
        "- स्कोर ० देखि १०० मा सीमित। ७०+ बलियो · ५५–६९ मध्यम · ४०–५४ कमजोर · ४० भन्दा कम सेटअप छैन।",
        "- **ब्रेकआउट:** बन्द मूल्य अघिल्लो २० सत्रको उच्चभन्दा माथि र SMA50 माथि। इन्ट्री जोन = ब्रेकआउट लेभलदेखि +0.5 ATR।",
        "- **पुलब्याक:** दैनिक अपट्रेन्डमा SMA20 वा सपोर्ट छोएर RSI 40–60 मा हरियो बन्द। इन्ट्री जोन = बन्द −0.5 ATR देखि बन्दसम्म।",
        "- **स्टप-लस:** नजिकको सपोर्ट −0.25 ATR, तर इन्ट्रीबाट 1–2 ATR भित्र। **T1/T2:** माथिका रेजिस्टेन्स जोन; नभए 2R/3R प्रक्षेपण।",
        "- NEPSE मा सर्ट-सेलिङ नहुने भएकाले योजना लङ (किन्ने) मात्र; बेयरिस परिदृश्य होल्डरका लागि जोखिम सङ्केत हो।",
        "",
    ]
    return out


def write_all(res: ScanResult, out_dir: Path) -> dict[str, Path]:
    """Write every Markdown report; returns {name: path}."""
    paths: dict[str, Path] = {}
    (out_dir / "agents").mkdir(parents=True, exist_ok=True)
    for r in res.agent_reports:
        p = out_dir / "agents" / f"{r.key}.md"
        p.write_text(agent_markdown(res, r), encoding="utf-8")
        paths[r.key] = p
    p = out_dir / "agents" / "unclassified.md"
    p.write_text(unclassified_markdown(res), encoding="utf-8")
    paths["unclassified"] = p
    p = out_dir / "master_np.md"
    p.write_text(master_markdown(res), encoding="utf-8")
    paths["master"] = p
    p = out_dir / "report_np.md"
    p.write_text(master_markdown(res, include_agents=True), encoding="utf-8")
    paths["report"] = p
    return paths
