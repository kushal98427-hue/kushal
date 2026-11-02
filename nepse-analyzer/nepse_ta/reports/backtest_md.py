"""Nepali Markdown summary of a backtest run."""

from __future__ import annotations

from pathlib import Path

from nepse_ta.backtest import BUCKETS


def _row(name: str, s: dict) -> str:
    if not s or not s.get("trades"):
        return f"| {name} | 0 | — | — | — | — | — | — |"
    ci = s.get("t1_hit_rate_ci95") or ("—", "—")
    return (
        f"| {name} | {s['trades']} | {s['win_rate_pct']}% | {s['t1_hit_rate_pct']}% ({ci[0]}–{ci[1]}) | "
        f"{s['avg_net_return_pct']}% | {s['expectancy_r']} | {s.get('profit_factor') or '—'} | "
        f"{s['max_drawdown_r']}R |"
    )


def write_backtest_md(result: dict, path: Path) -> None:
    wf = result.get("walk_forward", {})
    status = (
        "✅ **Calibrated** — out-of-sample त्रुटि सीमाभित्र। रिपोर्टमा 'ऐतिहासिक T1 हिट दर' देखाइनेछ (सम्भाव्यता होइन)।"
        if result.get("calibrated")
        else "❌ **Calibrated छैन** — दैनिक रिपोर्टमा सम्भाव्यता/दर देखाइँदैन, स्कोर मात्र।"
    )
    lines = [
        "# ब्याकटेस्ट रिपोर्ट (Walk-forward)",
        "",
        f"- परीक्षण गरिएका स्टक: {result.get('symbols_tested')} · अवधि: {result.get('period', {}).get('start')} → {result.get('period', {}).get('end')}",
        f"- {status}",
        f"- कारण: {wf.get('reason')}",
        "",
        "## नियम",
        "",
        "```",
        result.get("rules", ""),
        "```",
        "",
        "## नतिजा",
        "",
        "| समूह | ट्रेड | जित दर | T1 हिट दर (95% CI) | औसत नेट प्रतिफल | Expectancy (R) | Profit factor | Max drawdown (cumulative R) |",
        "|---|---|---|---|---|---|---|---|",
        _row("सबै सेटअप", result.get("summary_all", {})),
        _row("मास्टर मापदण्ड (स्कोर≥60, R:R≥1.5, तरल)", result.get("summary_eligible_rule", {})),
        *(_row(k, v) for k, v in result.get("by_setup_type", {}).items()),
        "",
        "## स्कोर समूह अनुसार (पूरा नमूना)",
        "",
        "| स्कोर | ट्रेड | T1 हिट दर | 95% CI | Expectancy (R) | पर्याप्त नमूना |",
        "|---|---|---|---|---|---|",
    ]
    for b in BUCKETS:
        d = result.get("by_bucket", {}).get(b, {})
        ci = d.get("ci95") or ("—", "—")
        lines.append(
            f"| {b} | {d.get('n', 0)} | {d.get('t1_hit_rate_pct') if d.get('t1_hit_rate_pct') is not None else '—'}% | "
            f"{ci[0]}–{ci[1]} | {d.get('expectancy_r') if d.get('expectancy_r') is not None else '—'} | {'हो' if d.get('sufficient_sample') else 'होइन'} |"
        )
    lines += ["", "## Walk-forward (हरेक वर्ष out-of-sample)", "", "| परीक्षण वर्ष | train ट्रेड | test ट्रेड | स्कोर समूह: train% → test% |", "|---|---|---|---|"]
    for fold in wf.get("folds", []):
        parts = ", ".join(f"{b}: {v['train_rate']}→{v['test_rate']} (n={v['test_n']})" for b, v in fold["buckets"].items())
        lines.append(f"| {fold['test_year']} | {fold['train_trades']} | {fold['test_trades']} | {parts or '—'} |")
    lines += [
        "",
        "## सीमाहरू",
        "",
        "- स्रोत रिपोमा सबै डिलिस्टेड कम्पनी छैनन् → केही survivorship bias बाँकी रहन सक्छ।",
        "- बोनस/हकप्रद समायोजन `per_change` बाट अनुमान गरिएको; केही घटना छुट्न सक्छन्।",
        "- शुल्क दर (कमिसन, SEBON, CGT) `nepse_ta/config.py` मा छन् — हालको दर आफ्नो ब्रोकरसँग पुष्टि गर्नुहोस्।",
        "- विगतको नतिजाले भविष्यको ग्यारेन्टी गर्दैन।",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
