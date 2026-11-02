import datetime as dt
import json

import pandas as pd

from nepse_ta.data.fetcher import git_blob_sha, load_from_local_dir
from nepse_ta.reports import export, markdown_np
from nepse_ta.scan import run_scan
from nepse_ta.sectors import (
    AGENT_BANKS,
    AGENT_DEVFIN,
    AGENT_HYDRO,
    AGENT_INSURANCE,
    AGENT_OTHERS,
    EXCLUDED,
    UNCLASSIFIED,
    SectorInfo,
    agent_for,
    load_sector_map,
)
from tests.conftest import make_ohlc, write_csv


def test_agent_mapping_rules():
    assert agent_for("Commercial Banks", "Equity") == AGENT_BANKS
    assert agent_for("Commercial Banks", "Mutual Funds") == AGENT_OTHERS  # bank-sponsored fund
    assert agent_for("Commercial Banks", "Non-Convertible Debentures") == EXCLUDED
    assert agent_for("Finance", "Equity") == AGENT_DEVFIN
    assert agent_for("Hydro Power", "Equity") == AGENT_HYDRO
    assert agent_for("Non Life Insurance", "Equity") == AGENT_INSURANCE
    assert agent_for("Microfinance", "Equity") == AGENT_OTHERS
    assert agent_for("Unclassified", "Equity") == UNCLASSIFIED
    assert agent_for("Hydro Power", "") == UNCLASSIFIED


def test_sector_map_file_is_consistent():
    m = load_sector_map()
    assert len(m) > 300
    for info in m.values():
        assert info.agent == agent_for(info.sector, info.instrument_type)
        if info.agent != UNCLASSIFIED:
            assert info.confidence == "high"


def test_git_blob_sha_matches_git():
    # `printf 'hello\n' | git hash-object --stdin`
    assert git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def _sector(sym: str, sector: str, instr: str = "Equity") -> SectorInfo:
    return SectorInfo(sym, f"{sym} Ltd", sector, instr, "A", agent_for(sector, instr), "high", "")


def _setup_dir(tmp_path):
    d = tmp_path / "company-wise"
    d.mkdir()
    write_csv(make_ohlc(n=320, seed=1, drift=0.003), d / "UPB.csv")  # trending up
    write_csv(make_ohlc(n=320, seed=2, drift=-0.003), d / "DNH.csv")  # trending down
    old = make_ohlc(n=320, seed=3)
    write_csv(old.iloc[:-10], d / "STL.csv")  # stale: 10 sessions behind
    write_csv(make_ohlc(n=320, seed=4), d / "UNK.csv")  # not in sector map
    write_csv(make_ohlc(n=320, seed=5), d / "DEB.csv")  # debenture -> excluded
    sm = {
        "UPB": _sector("UPB", "Commercial Banks"),
        "DNH": _sector("DNH", "Hydro Power"),
        "STL": _sector("STL", "Life Insurance"),
        "DEB": _sector("DEB", "Commercial Banks", "Non-Convertible Debentures"),
    }
    return d, sm


def test_end_to_end_scan_and_reports(tmp_path):
    d, sm = _setup_dir(tmp_path)
    fetch = load_from_local_dir(d)
    last = pd.Timestamp(make_ohlc(n=320).index[-1])
    now = dt.datetime.combine(last.date() + dt.timedelta(days=1), dt.time(12), tzinfo=dt.timezone.utc)
    res = run_scan(fetch, sm, now_utc=now)

    syms = {a.symbol: a for a in res.analyses}
    assert res.freshness == "ok"
    assert "DEB" in res.excluded_instruments and "DEB" not in syms
    assert syms["STL"].stale and not syms["STL"].eligible
    assert [a.symbol for a in res.unclassified] == ["UNK"]
    assert not syms["UNK"].eligible and "सेक्टर वर्गीकरण नभएको" in syms["UNK"].ineligible_reasons
    assert syms["DNH"].daily_trend in ("downtrend", "sideways")
    for a in res.analyses:  # every eligible setup satisfies the published rules
        if a.eligible:
            assert a.plan.rr1 >= 1.5 and a.score >= 60 and a.plan.stop < a.plan.entry_low

    out = tmp_path / "out"
    export.write_csv(res.analyses, out / "stocks.csv")
    export.write_json(res, out / "scan.json")
    paths = markdown_np.write_all(res, out)
    data = json.loads((out / "scan.json").read_text(encoding="utf-8"))
    assert data["meta"]["probability_status"] == "not_calibrated"
    assert len(data["stocks"]) == len(res.analyses)
    assert {"agent1_commercial_banks", "agent4_insurance", "master", "report"} <= set(paths)
    text = paths["report"].read_text(encoding="utf-8")
    assert "सम्भाव्यता (probability) होइन" in text
    assert "nan" not in (out / "stocks.csv").read_text(encoding="utf-8-sig").lower().replace("nanda", "")


def test_stale_market_blocks_all_setups(tmp_path):
    d, sm = _setup_dir(tmp_path)
    fetch = load_from_local_dir(d)
    now = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    res = run_scan(fetch, sm, now_utc=now)
    assert res.freshness == "blocked"
    assert res.master.no_valid_setup and not res.master.top_setups
    assert not any(a.eligible for a in res.analyses)
    md = markdown_np.master_markdown(res)
    assert "आज कुनै मान्य सेटअप छैन" in md
