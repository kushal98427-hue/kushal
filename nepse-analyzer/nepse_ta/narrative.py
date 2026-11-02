"""OPTIONAL AI-written Nepali narrative on top of the deterministic master report.

Disabled unless BOTH are true:
  * the ``--narrative`` flag is passed, and
  * ``ANTHROPIC_API_KEY`` is set (GitHub Secret of the same name in CI).

The model only receives the already-computed master summary (JSON) and is told
not to introduce any number that is not in it. If anything fails (no key, SDK
not installed, network, refusal) the scan continues without the narrative.
Using it costs money per call (Anthropic API billing).
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = (
    "You are writing a short market commentary in Nepali (Devanagari) for beginner NEPSE investors. "
    "Use ONLY facts and numbers present in the JSON you are given; never add prices, probabilities, "
    "news, or predictions that are not in it. Setup scores are heuristic rankings, not probabilities - "
    "never call them probabilities. If the JSON says there is no valid setup, say so plainly and do not "
    "suggest any stock to buy. Write 120-200 words in 2-3 short paragraphs, then one line reminding "
    "readers this is not investment advice."
)


def build_payload(scan_json: dict) -> dict:
    """Small, number-bounded summary sent to the model (no per-stock dump)."""
    stocks = {s["symbol"]: s for s in scan_json["stocks"]}
    top = []
    for sym in scan_json["master"]["top_setups"]:
        s = stocks[sym]
        p = s["plan"]
        top.append(
            {
                "symbol": sym,
                "group": s["group"],
                "setup": p["plan_type"],
                "close": s["close"],
                "entry": [p["entry_low"], p["entry_high"]],
                "stop": p["stop"],
                "target1": p["target1"],
                "rr1": p["rr1"],
                "score": s["score"],
            }
        )
    return {
        "market_date": scan_json["meta"]["market_date"],
        "freshness": scan_json["meta"]["freshness"],
        "no_valid_setup": scan_json["master"]["no_valid_setup"],
        "top_setups": top,
        "sector_ranking": [
            {k: g[k] for k in ("group", "n", "pct_above_sma50", "median_return_20d", "avg_score", "n_valid_setups")}
            for g in scan_json["master"]["sector_ranking"]
        ],
        "notes": scan_json["master"]["notes"],
    }


def generate_narrative(scan_json: dict) -> str | None:
    """Return Nepali commentary, or None if disabled/unavailable."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.info("ANTHROPIC_API_KEY not set; skipping AI narrative")
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed; pip install anthropic to enable the narrative")
        return None

    model = os.environ.get("NEPSE_LLM_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            # Server-side fallback: if the model's safety classifier declines, the API retries
            # on Anthropic's recommended fallback model inside the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[
                {
                    "role": "user",
                    "content": "Market summary JSON:\n" + json.dumps(build_payload(scan_json), ensure_ascii=False),
                }
            ],
        )
    except anthropic.RateLimitError as exc:
        log.warning("AI narrative skipped (rate limited): %s", exc)
        return None
    except anthropic.APIStatusError as exc:
        log.warning("AI narrative skipped (HTTP %s): %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError as exc:
        log.warning("AI narrative skipped (connection): %s", exc)
        return None
    if response.stop_reason == "refusal":
        log.warning("AI narrative declined by model; skipping")
        return None
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
    return text or None
