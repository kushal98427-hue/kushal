"""Daily memory update: store analyses, record plan changes, maintain the ledger.

Rules
-----
* One record per stock per trading date. Identical content on a re-run is a
  **duplicate** (nothing appended). Different content for the same date is a
  **revision** (new line with ``revision``, ``supersedes`` and a factual reason).
* A stock with no new candle gets no new record; it is listed in the run log as
  ``no_new_candle``. Stocks that failed validation are listed as ``failed``.
* Stale market data never creates a new trading day: records are keyed by the
  data's trading date, so a stale re-run only produces duplicates. When the
  market data is ``blocked`` no recommendation is created.
* Plan changes (vs the previous trading date, or vs the previous revision of the
  same date) are logged with old plan, new plan, changed fields and reason.
* Recommendations are created only for eligible setups on a fresh-enough,
  current-date candle, at most one active recommendation per stock.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from nepse_ta.analysis import SETUP_TYPES
from nepse_ta.config import DEFAULT_SETTINGS, SEOUL_TZ, STRATEGY_VERSION
from nepse_ta.data.validation import prepare_series
from nepse_ta.memory import ledger as L
from nepse_ta.memory.records import (
    build_content,
    classify,
    run_context,
    diff_fields,
    explain_change,
    plan_view,
    record_id,
)
from nepse_ta.memory.store import StateStore
from nepse_ta.scan import ScanResult
from nepse_ta.smc import smc_snapshot

PREVIOUS_LOOKBACK_DATES = 15


@dataclass
class UpdateSummary:
    run_id: str
    market_date: str | None
    freshness: str
    new: int = 0
    duplicate: int = 0
    revised: int = 0
    plan_changes: int = 0
    no_new_candle: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    recs_created: int = 0
    rec_events: int = 0
    recs_skipped_active: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _code_version() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parent,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _previous_record(store: StateStore, symbol: str, before: str, cache: dict) -> dict | None:
    """Latest stored record of ``symbol`` on a trading date earlier than ``before``."""
    dates = [d for d in store.analysis_dates() if d < before][-PREVIOUS_LOOKBACK_DATES:]
    for d in reversed(dates):
        if d not in cache:
            cache[d] = store.latest_by_symbol(d)
        if symbol in cache[d]:
            return cache[d][symbol]
    return None


def update_memory(
    res: ScanResult,
    store: StateStore,
    files: dict[str, Path],
    now_utc: dt.datetime | None = None,
    exec_cfg: L.ExecConfig = L.ExecConfig(),
    mode: str = "live",
) -> UpdateSummary:
    """Apply one scan result to the persistent state. Safe to run repeatedly."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    run_id = now_utc.strftime("%Y%m%dT%H%M%SZ")
    summ = UpdateSummary(run_id=run_id, market_date=res.market_date, freshness=res.freshness)
    summ.failed = dict(res.failures)
    store.verify_all()  # refuse to work on a tampered/corrupted state
    # One store = one mode. Replayed (historical) and live records must never share a store,
    # so replay results can never leak into live recommendations or performance.
    seen_modes = {r.get("mode") for r in store.runs.read()}
    if seen_modes and seen_modes != {mode}:
        raise ValueError(f"state dir already holds mode(s) {sorted(map(str, seen_modes))}; refusing to write mode={mode!r}")

    if mode not in ("live", "replay", "test"):
        raise ValueError(f"unknown mode {mode!r}")
    meta = {
        "mode": mode,  # "replay" = historical simulation, never mixed with live results
        "run_id": run_id,
        "generated_at_utc": now_utc.isoformat(timespec="seconds"),
        "generated_at_kst": now_utc.astimezone(ZoneInfo(SEOUL_TZ)).strftime("%Y-%m-%d %H:%M KST"),
        "data_timestamp": res.source.commit_date_utc,
        "data_source": {"repo": "Aabishkar2/nepse-data", "commit": res.source.commit_sha, "listing": res.source.listing},
        "freshness": res.freshness,
        "market_date": res.market_date,
        "code_version": _code_version(),
    }

    rec_rows = list(store.recommendations.read())
    states = L.replay(rec_rows)
    # symbols with an active recommendation from an EARLIER trading date (a recommendation
    # created from today's candle must not reclassify today's own analysis)
    active_before = {(s.created["symbol"], s.created["trading_date"]) for s in states.values() if s.active}
    active_syms = {sym for sym, _ in active_before}
    watch = {a.symbol for r in res.agent_reports for a in r.watchlist}

    by_date: dict[str, list[dict]] = {}
    plan_rows: list[dict] = []
    rec_new: list[dict] = []
    date_cache: dict[str, dict[str, dict]] = {}
    prev_cache: dict[str, dict[str, dict]] = {}
    stored_now: dict[str, dict] = {}

    series_cache: dict[str, object] = {}

    def series_of(sym: str):
        if sym not in series_cache:
            path = files.get(sym)
            try:
                series_cache[sym] = prepare_series(sym, path, DEFAULT_SETTINGS.data) if path else None
            except Exception:  # noqa: BLE001 - reported as unavailable
                series_cache[sym] = None
        return series_cache[sym]

    # res.unclassified is a SUBSET of res.analyses (kept separately only for reports):
    # iterate unique symbols so no stock is stored twice in one run.
    unique: dict[str, object] = {}
    for a in res.analyses + res.unclassified:
        unique.setdefault(a.symbol, a)
    for a in unique.values():
        earlier_open = {sym for sym, d0 in active_before if d0 < a.date}
        content = build_content(a, classify(a, watch, earlier_open), smc=_smc_for(a, series_of(a.symbol)))
        rid = record_id(content)
        d = a.date
        if d not in date_cache:
            date_cache[d] = store.latest_by_symbol(d)
        existing = date_cache[d].get(a.symbol)
        if existing and existing["record_id"] == rid:
            summ.duplicate += 1
            stored_now[a.symbol] = existing
            continue
        rec = {**meta, "record_id": rid, "symbol": a.symbol, "trading_date": d, "context": run_context(a), "content": content}
        if existing:
            rec |= {
                "revision": existing["revision"] + 1,
                "supersedes": existing["record_id"],
                "revision_reason": explain_change(existing["content"], content, same_date=True),
            }
            summ.revised += 1
            prev = existing
        else:
            rec |= {"revision": 0, "supersedes": None, "revision_reason": None}
            summ.new += 1
            prev = _previous_record(store, a.symbol, d, prev_cache)
        if prev is not None:
            old, new = plan_view(prev["content"]), plan_view(content)
            changed = diff_fields(old, new)
            if changed:
                plan_rows.append(
                    {
                        "run_id": run_id,
                        "recorded_at_utc": meta["generated_at_utc"],
                        "symbol": a.symbol,
                        "trading_date": d,
                        "previous_trading_date": prev["trading_date"],
                        "previous_record_id": prev["record_id"],
                        "record_id": rid,
                        "same_date_revision": bool(existing),
                        "changed_fields": changed,
                        "previous_plan": old,
                        "new_plan": new,
                        "reason": explain_change(prev["content"], content, same_date=bool(existing)),
                    }
                )
        by_date.setdefault(d, []).append(rec)
        stored_now[a.symbol] = rec

    # stocks without a candle on the market date: analysed but last traded earlier, plus
    # stocks stored on the previous date that are absent from this run entirely.
    # (Defined from this run's data, so repeated runs report the same list.)
    if res.market_date:
        everyone = list(unique.values())
        lagging = {a.symbol for a in everyone if a.date < res.market_date}
        present = {a.symbol for a in everyone}
        prev_date = store.previous_date(res.market_date)
        vanished: set[str] = set()
        if prev_date:
            if prev_date not in date_cache:
                date_cache[prev_date] = store.latest_by_symbol(prev_date)
            vanished = set(date_cache[prev_date]) - present
        summ.no_new_candle = sorted(lagging | vanished)

    for d, rows in sorted(by_date.items()):
        store.analyses(d).append(rows)
    summ.plan_changes = store.plan_changes.append(plan_rows)

    # ---- recommendations -------------------------------------------------
    created_ids = {s.rec_id for s in states.values()}
    stamp = {"mode": mode, "run_id": run_id, "recorded_at_utc": meta["generated_at_utc"]}
    for sym, rec in stored_now.items():
        c = rec["content"]
        rec_id = f"{sym}-{c['trading_date']}-{c['strategy_version']}"
        st = states.get(rec_id)
        if st is not None:  # same-date revision of an existing recommendation
            if st.status == "pending" and rec["record_id"] != st.created["analysis_record_id"]:
                if not c["eligible"]:
                    rec_new.append({**stamp, "rec_id": rec_id, "type": "withdrawn", "reason": "revised analysis no longer eligible", "analysis_record_id": rec["record_id"]})
                else:
                    new_plan = L.created_event(rec, run_id)["plan"]
                    if new_plan != st.plan_event["plan"]:
                        rec_new.append({**stamp, "rec_id": rec_id, "type": "plan_revised", "new_plan": new_plan, "analysis_record_id": rec["record_id"]})
            continue
        eligible_today = (
            c["eligible"]
            and c["plan"]["plan_type"] in SETUP_TYPES
            and c["trading_date"] == res.market_date
            and res.freshness != "blocked"
            and c["strategy_version"] == STRATEGY_VERSION
        )
        if not eligible_today or rec_id in created_ids:
            continue
        if sym in active_syms:
            summ.recs_skipped_active.append(sym)
            continue
        rec_new.append({**L.created_event(rec, run_id), "mode": mode, "recorded_at_utc": meta["generated_at_utc"]})
        summ.recs_created += 1
    if rec_new:
        store.recommendations.append(rec_new)
        states = L.replay(list(store.recommendations.read()))

    # ---- outcomes for every non-terminal recommendation ---------------------
    out_rows: list[dict] = []
    for st in states.values():
        if st.status not in ("pending", "open"):
            continue
        sym = st.created["symbol"]
        series = series_of(sym)
        if series is None:
            summ.notes.append(f"{sym}: outcome not evaluated (no data this run)")
            continue
        computed = L.evaluate(st.plan_event, series.df, exec_cfg)  # type: ignore[attr-defined]
        for ev in L.new_outcome_events(st, computed):
            out_rows.append({**stamp, "rec_id": st.rec_id, **ev})
    summ.rec_events = store.recommendations.append(out_rows) + len(rec_new) - summ.recs_created

    store.runs.append(
        [
            {
                **meta,
                "strategy_version": STRATEGY_VERSION,
                "execution_model": exec_cfg.version,
                "counts": {
                    "new": summ.new,
                    "duplicate": summ.duplicate,
                    "revised": summ.revised,
                    "plan_changes": summ.plan_changes,
                    "recs_created": summ.recs_created,
                    "rec_events": summ.rec_events,
                },
                "expected_session": str(res.fresh.expected_session) if res.fresh else None,
                "no_new_candle": summ.no_new_candle,
                "failed": summ.failed,
                "recs_skipped_active": summ.recs_skipped_active,
                "notes": summ.notes,
            }
        ]
    )
    return summ


def _smc_for(a, series) -> dict:
    """smc-1 section for the stock's own trading date, or an explicit 'unavailable'."""
    if series is None:
        return {"status": "unavailable", "reason": "price series could not be loaded"}
    live = series.live
    if not len(live) or live.index[-1].strftime("%Y-%m-%d") != a.date:
        return {"status": "unavailable", "reason": "series date does not match the analysis date"}
    try:
        return smc_snapshot(live)
    except Exception as exc:  # noqa: BLE001 - never block the memory update
        return {"status": "unavailable", "reason": f"smc error: {type(exc).__name__}"}
