"""Replay the last N trading sessions through the v2 memory, one day at a time.

For each session date D, every CSV is truncated to rows <= D (what was known that
evening) and ``update_memory`` runs with ``mode="replay"``. Writes ONLY to the given
scratch state directory -- never use it for the live state branch.

    python scripts/replay_memory.py --source-dir <nepse-data>/data/company-wise --state-dir /tmp/x --sessions 15
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_ta.data.fetcher import load_from_local_dir  # noqa: E402
from nepse_ta.memory.ledger import replay, summarize_ledger  # noqa: E402
from nepse_ta.memory.store import StateStore  # noqa: E402
from nepse_ta.memory.update import update_memory  # noqa: E402
from nepse_ta.scan import run_scan  # noqa: E402
from nepse_ta.sectors import load_sector_map  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", type=Path, required=True)
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--sessions", type=int, default=15)
    args = ap.parse_args()
    sm = load_sector_map()
    nabil = pd.read_csv(args.source_dir / "NABIL.csv", usecols=["published_date"])["published_date"]
    dates = sorted(set(nabil))[-args.sessions :]
    for d in dates:
        day_dir = args.work_dir / d
        if day_dir.exists():
            shutil.rmtree(day_dir)
        day_dir.mkdir(parents=True)
        for p in args.source_dir.glob("*.csv"):
            lines = p.read_text(encoding="utf-8").splitlines()
            keep = [lines[0]] + [ln for ln in lines[1:] if ln[:10] <= d]
            (day_dir / p.name).write_text("\n".join(keep) + "\n", encoding="utf-8")
        now = dt.datetime.fromisoformat(f"{d}T12:00:00+00:00")
        fetch = load_from_local_dir(day_dir)
        res = run_scan(fetch, sm, now_utc=now)
        s = update_memory(res, StateStore(args.state_dir), fetch.files, now_utc=now, mode="replay")
        print(f"{d} {res.freshness:8s} new={s.new:3d} dup={s.duplicate:3d} rev={s.revised} plan_changes={s.plan_changes:3d} "
              f"recs+={s.recs_created} events+={s.rec_events} no_new_candle={len(s.no_new_candle)}")
        shutil.rmtree(day_dir)
    print(json.dumps(summarize_ledger(replay(list(StateStore(args.state_dir).recommendations.read())), mode="replay"), indent=1))


if __name__ == "__main__":
    main()
