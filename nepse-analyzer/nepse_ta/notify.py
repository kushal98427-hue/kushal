"""Optional phone notifications (free services). Does nothing unless configured.

Supported (set as GitHub Secrets; any combination):

* **ntfy** (no account): ``NTFY_TOPIC`` = a long random topic name you subscribe to in
  the free ntfy app. Optional ``NTFY_SERVER`` (default https://ntfy.sh).
  Anyone who knows the topic name can read it, so use a long random name.
* **Telegram**: ``TELEGRAM_BOT_TOKEN`` (from @BotFather) and ``TELEGRAM_CHAT_ID``.

A failed notification is logged and never fails the scan.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from pathlib import Path

import requests

from nepse_ta.data.fetcher import make_session

log = logging.getLogger(__name__)


def build_message(scan: dict, report_url: str | None = None) -> tuple[str, str]:
    """(title, body) from scan.json -- only facts already in the report."""
    meta, master = scan["meta"], scan["master"]
    status = {"current": "ताजा", "stale": "STALE (पुरानो)", "blocked": "BLOCKED"}.get(meta["freshness"], meta["freshness"])
    title = f"NEPSE {meta['market_date']} — {status}"
    stocks = {s["symbol"]: s for s in scan["stocks"]}
    lines = [f"डाटा मिति: {meta['market_date']} ({status}); अपेक्षित सत्र: {meta.get('expected_latest_session')}"]
    if master["top_setups"]:
        lines.append("मान्य सेटअप (सिफारिस होइन):")
        for sym in master["top_setups"][:5]:
            p = stocks[sym]["plan"]
            lines.append(f"• {sym} {p['plan_type']} इन्ट्री {p['entry_low']}–{p['entry_high']} स्टप {p['stop']} T1 {p['target1']}")
    else:
        lines.append("कुनै मान्य सेटअप छैन।")
    if meta.get("historical_expectancy_r") is not None and meta["historical_expectancy_r"] <= 0:
        lines.append(f"⚠ ऐतिहासिक नतिजा {meta['historical_expectancy_r']}R (लागतपछि) — स्क्रिनिङ मात्र।")
    if report_url:
        lines.append(report_url)
    return title, "\n".join(lines)


def send_ntfy(title: str, body: str, session: requests.Session) -> bool:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    # JSON publishing keeps UTF-8 (Nepali) titles intact.
    r = session.post(server, data=json.dumps({"topic": topic, "title": title, "message": body}).encode(), timeout=20)
    r.raise_for_status()
    return True


def send_telegram(title: str, body: str, session: requests.Session) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
    r = session.post(f"{base}/bot{token}/sendMessage", json={"chat_id": chat, "text": f"{title}\n{body}"}, timeout=20)
    r.raise_for_status()
    return True


def notify(scan_json_path: Path, report_url: str | None = None, failure: str | None = None) -> dict[str, str]:
    """Send to every configured channel. Returns {channel: 'sent'|'skipped'|'error: ...'}."""
    if failure:
        title, body = "NEPSE scan FAILED", failure + (f"\n{report_url}" if report_url else "")
    else:
        title, body = build_message(json.loads(scan_json_path.read_text(encoding="utf-8")), report_url)
    session = make_session(retries=3)
    out: dict[str, str] = {}
    for name, fn in (("ntfy", send_ntfy), ("telegram", send_telegram)):
        try:
            out[name] = "sent" if fn(title, body, session) else "skipped (not configured)"
        except requests.RequestException as exc:
            # never print the URL: the Telegram URL contains the bot token
            out[name] = f"error: {type(exc).__name__}"
            log.warning("%s notification failed: %s", name, type(exc).__name__)
    return out


def selftest_ntfy(server: str | None = None) -> dict[str, bool]:
    """Publish to a fresh random throwaway topic, then poll the server for it.

    Proves the runner can reach ntfy and that our publish format is accepted, without
    touching (or printing) the real topic. Returns booleans only.
    """
    server = (server or os.environ.get("NTFY_SERVER", "https://ntfy.sh")).rstrip("/")
    topic = "nepse-selftest-" + secrets.token_urlsafe(18)
    marker = secrets.token_hex(8)
    session = make_session(retries=3)
    out = {"published": False, "received_by_server": False}
    try:
        r = session.post(server, data=json.dumps({"topic": topic, "title": "NEPSE self-test", "message": marker}).encode(), timeout=20)
        out["published"] = r.status_code == 200
        for _ in range(5):
            time.sleep(1)
            g = session.get(f"{server}/{topic}/json", params={"poll": "1"}, timeout=20)
            if g.ok and any(json.loads(line).get("message") == marker for line in g.text.splitlines() if line.strip()):
                out["received_by_server"] = True
                break
    except requests.RequestException as exc:
        log.warning("ntfy self-test failed: %s", type(exc).__name__)
    return out


def diagnose_ntfy_secret() -> dict:
    """Describe NTFY_TOPIC WITHOUT revealing it: shape checks + a short SHA-256 fingerprint."""
    import hashlib
    import re

    raw = os.environ.get("NTFY_TOPIC")
    if raw is None or raw == "":
        return {"configured": False}
    v = raw.strip()
    return {
        "configured": True,
        "length": len(raw),
        "is_literal_text_NTFY_TOPIC": v.upper() in ("NTFY_TOPIC", "$NTFY_TOPIC", "${NTFY_TOPIC}"),
        "has_leading_or_trailing_whitespace": raw != v,
        "contains_url_or_slash": "/" in v or "ntfy.sh" in v.lower(),
        "valid_ntfy_topic_chars": bool(re.fullmatch(r"[-_A-Za-z0-9]{1,64}", v)),
        "starts_with_nepse_dash": v.startswith("nepse-"),
        "sha256_prefix": hashlib.sha256(v.encode()).hexdigest()[:12],
    }
