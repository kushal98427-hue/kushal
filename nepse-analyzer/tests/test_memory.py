"""Phase 1: append-only memory, plan-change log and recommendation ledger."""

import datetime as dt
import gzip
import json

import pandas as pd
import pytest

from nepse_ta.analysis import TradePlan
from nepse_ta.config import CostConfig
from nepse_ta.data.fetcher import load_from_local_dir
from nepse_ta.memory import ledger as L
from nepse_ta.memory.store import AppendOnlyLog, IntegrityError, StateStore
from nepse_ta.memory.update import update_memory
from nepse_ta.scan import run_scan
from nepse_ta.sectors import SectorInfo, agent_for
from tests.conftest import make_ohlc, write_csv

NO_COST = CostConfig(commission_pct=0, sebon_fee_pct=0, dp_charge_npr=0, cgt_pct=0, slippage_pct=0)
EXEC0 = L.ExecConfig(costs=NO_COST)


# --------------------------------------------------------------------------- storage
@pytest.mark.parametrize("name", ["log.jsonl", "log.jsonl.gz"])
def test_append_only_chain_and_tamper_detection(tmp_path, name):
    log = AppendOnlyLog(tmp_path / name)
    log.append([{"a": 1}, {"a": 2}])
    log.append([{"a": 3}])
    assert [r["a"] for r in log.read()] == [1, 2, 3]
    # tamper with the first line
    p = tmp_path / name
    if name.endswith(".gz"):
        text = gzip.open(p, "rt").read().replace('"a":1', '"a":9', 1)
        p.write_bytes(gzip.compress(text.encode()))
    else:
        p.write_text(p.read_text().replace('"a":1', '"a":9', 1))
    with pytest.raises(IntegrityError):
        log.verify()
    with pytest.raises(IntegrityError):  # refuses to append on top of a broken chain
        log.append([{"a": 4}])


def test_deleting_a_line_is_detected(tmp_path):
    log = AppendOnlyLog(tmp_path / "x.jsonl")
    log.append([{"i": i} for i in range(3)])
    lines = (tmp_path / "x.jsonl").read_text().splitlines()
    (tmp_path / "x.jsonl").write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(IntegrityError):
        log.verify()


# --------------------------------------------------------------------------- daily update
def _sector(sym, sector="Commercial Banks"):
    return SectorInfo(sym, f"{sym} Ltd", sector, "Equity", "A", agent_for(sector, "Equity"), "high", "")


def _universe(tmp_path, n=320, drop_last_for=()):
    d = tmp_path / "cw"
    d.mkdir(exist_ok=True)
    for i, sym in enumerate(["AAA", "BBB", "CCC"]):
        df = make_ohlc(n=n, seed=10 + i, drift=0.002)
        if sym in drop_last_for:
            df = df.iloc[:-1]
        write_csv(df, d / f"{sym}.csv")
    return d, {s: _sector(s) for s in ("AAA", "BBB", "CCC")}


def _now_for(last: pd.Timestamp, days_later: int = 0) -> dt.datetime:
    return dt.datetime.combine(last.date() + dt.timedelta(days=days_later), dt.time(12), tzinfo=dt.timezone.utc)


def _run(d, sm, store, now):
    fetch = load_from_local_dir(d)
    res = run_scan(fetch, sm, now_utc=now)
    return res, update_memory(res, store, fetch.files, now_utc=now)


def test_duplicate_run_appends_nothing(tmp_path):
    d, sm = _universe(tmp_path)
    store = StateStore(tmp_path / "state")
    last = make_ohlc(n=320).index[-1]
    _, s1 = _run(d, sm, store, _now_for(last))
    size = {p: p.stat().st_size for p in (tmp_path / "state" / "analyses").rglob("*.gz")}
    _, s2 = _run(d, sm, store, _now_for(last) + dt.timedelta(hours=1))
    assert s1.new == 3 and s2.new == 0 and s2.duplicate == 3 and s2.revised == 0
    assert {p: p.stat().st_size for p in size} == size  # analysis files untouched
    assert len(list(store.runs.read())) == 2  # but every run is logged


def test_missing_candle_creates_no_record_and_is_reported(tmp_path):
    d, sm = _universe(tmp_path, n=319)
    store = StateStore(tmp_path / "state")
    day1 = make_ohlc(n=319).index[-1]
    _run(d, sm, store, _now_for(day1))
    (tmp_path / "day2").mkdir()
    d2, _ = _universe(tmp_path / "day2", n=320, drop_last_for=("CCC",))  # CCC has no new candle
    day2 = make_ohlc(n=320).index[-1]
    res, s = _run(d2, sm, store, _now_for(day2))
    day2_records = store.latest_by_symbol(str(day2.date()))
    assert set(day2_records) == {"AAA", "BBB"}
    assert s.no_new_candle == ["CCC"]
    run = list(store.runs.read())[-1]
    assert run["no_new_candle"] == ["CCC"]


def test_stale_rerun_is_duplicate_and_blocked_creates_no_recommendation(tmp_path):
    d, sm = _universe(tmp_path)
    store = StateStore(tmp_path / "state")
    last = make_ohlc(n=320).index[-1]
    _run(d, sm, store, _now_for(last))
    res, s = _run(d, sm, store, _now_for(last, days_later=1))  # next day, no new data
    assert res.freshness in ("stale", "blocked") and s.new == 0 and s.duplicate == 3
    # force an eligible setup while the market is blocked, on an EMPTY store (so no earlier
    # recommendation can mask the guard): no recommendation may be created
    fresh_store = StateStore(tmp_path / "state2")
    fetch = load_from_local_dir(d)
    res = run_scan(fetch, sm, now_utc=_now_for(last, days_later=30))
    assert res.freshness == "blocked"
    for a in res.analyses:
        a.eligible, a.plan = True, TradePlan("breakout", 100, 101, 100.5, 95, None, 110, None, 115, None, 1.9, 2.9)
    s = update_memory(res, fresh_store, fetch.files, now_utc=_now_for(last, days_later=30))
    assert s.recs_created == 0 and not list(fresh_store.recommendations.read())
    # control: the same forced setups on current data DO create recommendations
    res_ok = run_scan(fetch, sm, now_utc=_now_for(last))
    for a in res_ok.analyses:
        a.eligible, a.plan = True, TradePlan("breakout", 100, 101, 100.5, 95, None, 110, None, 115, None, 1.9, 2.9)
    assert update_memory(res_ok, StateStore(tmp_path / "state3"), fetch.files, now_utc=_now_for(last)).recs_created == 3


def test_revised_analysis_appends_revision_and_plan_change(tmp_path):
    d, sm = _universe(tmp_path)
    store = StateStore(tmp_path / "state")
    last = make_ohlc(n=320).index[-1]
    _run(d, sm, store, _now_for(last))
    first = store.latest_by_symbol(str(last.date()))["AAA"]
    # the source corrects AAA's last candle (much higher close)
    p = d / "AAA.csv"
    lines = p.read_text().splitlines()
    parts = lines[-1].split(",")
    parts[2] = str(float(parts[2]) * 1.08)  # high
    parts[4] = str(float(parts[4]) * 1.07)  # close
    lines[-1] = ",".join(parts)
    p.write_text("\n".join(lines) + "\n")
    _, s = _run(d, sm, store, _now_for(last) + dt.timedelta(hours=2))
    assert s.revised == 1 and s.duplicate == 2
    rows = [r for r in store.analyses(str(last.date())).read() if r["symbol"] == "AAA"]
    assert [r["revision"] for r in rows] == [0, 1]
    assert rows[0] == first  # original untouched
    assert rows[1]["supersedes"] == first["record_id"]
    assert "source price/volume data for this date changed" in rows[1]["revision_reason"]


def test_recommendation_created_once_and_tracked_separately(tmp_path):
    d, sm = _universe(tmp_path)
    store = StateStore(tmp_path / "state")
    last = make_ohlc(n=320).index[-1]
    fetch = load_from_local_dir(d)
    res = run_scan(fetch, sm, now_utc=_now_for(last))
    a = next(x for x in res.analyses if x.symbol == "AAA")
    c = a.close
    a.eligible = True
    a.plan = TradePlan("breakout", c, c * 1.01, c * 1.005, c * 0.95, "test", c * 1.10, "test", c * 1.15, "test", 1.9, 2.9)
    s = update_memory(res, store, fetch.files, now_utc=_now_for(last))
    s2 = update_memory(res, store, fetch.files, now_utc=_now_for(last) + dt.timedelta(hours=1))
    rows = list(store.recommendations.read())
    created = [r for r in rows if r["type"] == "created"]
    assert s.recs_created == 1 and s2.recs_created == 0 and len(created) == 1
    assert created[0]["kind"] == "system_recommendation_hypothetical"
    assert L.replay(rows)[created[0]["rec_id"]].status == "pending"  # no future bars yet


# --------------------------------------------------------------------------- outcomes
def bars(rows, start="2025-01-01", adj=None):
    idx = pd.bdate_range(start, periods=len(rows))
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["adj_factor"] = adj if adj is not None else 1.0
    return df


REC = {
    "trading_date": "2025-01-01",
    "plan": {"plan_type": "breakout", "entry_low": 100.0, "entry_high": 101.0, "stop": 95.0, "target1": 110.0, "target2": 115.0},
}
F = (100.0, 101.0, 99.0, 100.0)


def test_triggered_then_target_with_costs():
    df = bars([F, F, F, F, (100, 111, 99, 108), F])
    ev = L.evaluate(REC, df, L.ExecConfig())
    assert [e["type"] for e in ev] == ["triggered", "closed"]
    closed = ev[-1]
    assert closed["exit_reason"] == "target1"
    assert closed["net_return_pct"] < closed["raw_return_pct"]  # costs applied
    # exact cost model: fees + DP + CGT on top of slippage-adjusted fills
    from nepse_ta.backtest import net_return
    assert closed["net_return_pct"] == pytest.approx(net_return(ev[0]["entry_price"], closed["exit_price"], CostConfig()), abs=0.01)  # prices rounded to 0.01
    assert closed["net_return_pct"] < (closed["exit_price"] / ev[0]["entry_price"] - 1) * 100  # fees+tax beyond slippage
    assert closed["realized_r"] == pytest.approx(closed["net_return_pct"] / closed["risk_pct"], abs=1e-3)
    assert closed["mfe_r"] > 0 and closed["mae_r"] <= 0


def test_limit_fill_when_open_gaps_above_zone():
    df = bars([F, (104, 105, 100.5, 104), F, F, F])
    ev = L.evaluate(REC, df, EXEC0)
    assert ev[0]["type"] == "triggered" and ev[0]["fill"] == "limit" and ev[0]["entry_price"] == 101.0


def test_not_triggered_cases():
    assert L.evaluate(REC, bars([F, (94, 96, 93, 94)]), EXEC0)[0]["type"] == "invalidated_before_entry"
    up = (105, 112, 104, 111)  # never trades back into the zone, reaches T1
    assert L.evaluate(REC, bars([F, up]), EXEC0)[0]["type"] == "missed_without_entry"
    hi = (104, 106, 103, 105)
    assert L.evaluate(REC, bars([F, hi, hi, hi]), EXEC0)[0]["type"] == "expired_not_triggered"
    assert L.evaluate(REC, bars([F, hi]), EXEC0) == []  # still pending
    gap = pd.DataFrame([F, F], columns=["open", "high", "low", "close"], index=pd.DatetimeIndex(["2025-01-01", "2025-01-20"]))
    gap["adj_factor"] = 1.0
    assert L.evaluate(REC, gap, EXEC0)[0]["type"] == "expired_stale"


def test_bonus_adjustment_is_not_counted_as_loss():
    # 10% bonus after entry: history (incl. signal day) is back-adjusted by 1/1.1.
    f = 1 / 1.1
    raw = [F, F, F, F, (100, 101, 99, 100), (100, 101, 99, 100)]
    df = bars([tuple(x * f for x in r) for r in raw[:4]] + [(91, 101 * f, 90, 91), (91, 101 * f * 1.25, 90, 100)])
    df["adj_factor"] = [f] * 4 + [1.0, 1.0]
    ev = L.evaluate(REC, df, EXEC0)
    assert ev[0]["price_adjustment_factor"] == pytest.approx(f, abs=1e-6)
    assert ev[0]["entry_price"] == pytest.approx(100 * f, abs=0.01)  # same economics as an unadjusted 100
    assert ev[-1]["exit_reason"] == "target1"  # not stopped out by the mechanical drop to ~91


def test_events_are_idempotent_and_corrections_append():
    df = bars([F, F, F, F, (100, 111, 99, 108)])
    state = L.RecState("X", {**REC, "rec_id": "X", "type": "created"})
    computed = L.evaluate(REC, df, EXEC0)
    assert L.new_outcome_events(state, computed) == computed
    state.events = [dict(e) for e in computed]
    assert L.new_outcome_events(state, computed) == []  # re-run: nothing new
    revised = L.evaluate(REC, bars([F, (100, 101, 99, 100.5), F, F, (100, 111, 99, 108)]), EXEC0)
    revised[0]["entry_price"] = 100.5
    out = L.new_outcome_events(state, revised)
    assert out[0]["type"] == "correction" and out[0]["recomputed_events"] == revised


def test_withdrawn_and_status_replay():
    rows = [
        {"rec_id": "R", "type": "created", **REC},
        {"rec_id": "R", "type": "withdrawn", "reason": "x"},
    ]
    st = L.replay(rows)["R"]
    assert st.status == "withdrawn" and not st.active
    summary = L.summarize_ledger({"R": st})
    assert summary["recommendations"] == 1 and summary["triggered"] == 0
    assert "hypothetical" in summary["label"]


def test_records_store_required_fields(tmp_path):
    d, sm = _universe(tmp_path)
    store = StateStore(tmp_path / "state")
    last = make_ohlc(n=320).index[-1]
    _run(d, sm, store, _now_for(last))
    rec = store.latest_by_symbol(str(last.date()))["AAA"]
    for k in ("run_id", "generated_at_kst", "data_timestamp", "freshness", "trading_date", "record_id"):
        assert k in rec
    c = rec["content"]
    for k in ("price", "volume", "technical", "smc", "events", "plan", "thesis", "confirmation_conditions",
              "invalidation_conditions", "strategy_version", "classification"):
        assert k in c
    assert c["smc"]["status"] == "not_available" and c["events"]["status"] == "not_available"
    json.dumps(rec)  # serialisable


def test_no_buying_below_the_entry_zone():
    below = (97, 98.5, 96, 98)  # opens below entry_low 100, never trades back into the zone
    assert L.evaluate(REC, bars([F, below, below, below]), EXEC0)[0]["type"] == "expired_not_triggered"
    back = (97, 100.5, 96, 100)  # opens below, trades back up into the zone, stop untouched
    ev = L.evaluate(REC, bars([F, back]), EXEC0)
    assert ev[0]["fill"] == "back_into_zone" and ev[0]["entry_price"] == 100.0
    whipsaw = (97, 100.5, 94, 99)  # also touched the stop on the same bar: unknown order -> invalidated
    assert L.evaluate(REC, bars([F, whipsaw]), EXEC0)[0]["type"] == "invalidated_before_entry"


def test_plan_change_rules():
    from nepse_ta.memory.records import diff_fields

    base = {"plan_type": "watch_breakout", "entry_low": 100.0, "entry_high": 101.0, "stop": 95.0,
            "target1": 110.0, "target2": 115.0, "classification": "D_avoid_no_trade"}
    assert diff_fields(base, {**base, "stop": 90.0}) == []  # no-trade stock: levels irrelevant
    assert diff_fields(base, {**base, "plan_type": "none"}) == []  # ...and so is its plan type
    assert diff_fields(base, {**base, "classification": "B_watchlist_waiting_confirmation"}) == ["classification"]
    watch = {**base, "classification": "B_watchlist_waiting_confirmation"}
    assert diff_fields(watch, {**watch, "stop": 95.5}) == []  # 0.5% ATR jitter
    assert diff_fields(watch, {**watch, "stop": 93.0}) == ["stop"]  # 2% move
    assert diff_fields(watch, {**watch, "plan_type": "breakout"}) == ["plan_type"]
