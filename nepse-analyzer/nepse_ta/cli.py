"""Command-line interface.

    python -m nepse_ta scan      [--source-dir DIR] [--out reports] [--symbols NABIL,NICA] [--narrative]
    python -m nepse_ta backtest  [--source-dir DIR] [--out reports/backtest] [--workers N]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import shutil
import sys
from pathlib import Path

from nepse_ta.config import DEFAULT_SETTINGS
from nepse_ta.sectors import DEFAULT_MAP_PATH, load_sector_map

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("nepse_ta")


def _symbols(arg: str | None) -> list[str] | None:
    return [s.strip().upper() for s in arg.split(",") if s.strip()] if arg else None


def cmd_scan(args: argparse.Namespace) -> int:
    from nepse_ta.backtest import load_backtest
    from nepse_ta.reports import export, markdown_np
    from nepse_ta.scan import load_fetch, run_scan

    sector_map = load_sector_map(args.sector_map)
    fetch = load_fetch(args.source_dir, args.cache_dir, sector_map, _symbols(args.symbols))
    if not fetch.files:
        log.error("No CSV files available (failures: %d). Aborting.", len(fetch.failures))
        return 1
    backtest = load_backtest(args.calibration)
    calibration = backtest if backtest and backtest.get("calibrated") else None
    now = dt.datetime.fromisoformat(args.now) if args.now else None
    res = run_scan(fetch, sector_map, DEFAULT_SETTINGS, now_utc=now, calibration=calibration, backtest=backtest)
    if not res.analyses:
        log.error("No stock could be analysed.")
        return 1

    out_dir = args.out / (res.market_date or "unknown-date")
    out_dir.mkdir(parents=True, exist_ok=True)
    export.write_csv(res.analyses + res.unclassified, out_dir / "stocks.csv")
    export.write_json(res, out_dir / "scan.json")
    paths = markdown_np.write_all(res, out_dir)

    if args.narrative:
        from nepse_ta.narrative import generate_narrative

        text = generate_narrative(json.loads((out_dir / "scan.json").read_text(encoding="utf-8")))
        if text:
            note = "\n\n## AI सारांश (स्वचालित, केवल माथिका तथ्यमा आधारित)\n\n" + text + "\n"
            for key in ("master", "report"):
                with paths[key].open("a", encoding="utf-8") as fh:
                    fh.write(note)

    latest = args.out / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(out_dir, latest)
    m = res.master
    print(f"Market date: {res.market_date} | freshness: {res.freshness} ({res.data_age_days} days)")
    print(f"Analysed: {len(res.analyses)} | unclassified: {len(res.unclassified)} | failures: {len(res.failures)}")
    print("Top setups: " + (", ".join(a.symbol for a in m.top_setups) or "NONE (no valid setup today)"))
    print(f"Reports written to {out_dir}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from nepse_ta.backtest import run_backtest, save_backtest
    from nepse_ta.reports.backtest_md import write_backtest_md
    from nepse_ta.scan import load_fetch

    sector_map = load_sector_map(args.sector_map)
    fetch = load_fetch(args.source_dir, args.cache_dir, sector_map, _symbols(args.symbols))
    # Exclude debentures (bond prices) but keep delisted/unclassified equities to limit survivorship bias.
    files = {s: p for s, p in fetch.files.items() if not (s in sector_map and sector_map[s].agent == "excluded_non_equity")}
    result = run_backtest(files, DEFAULT_SETTINGS, workers=args.workers)
    path = save_backtest(result, args.out)
    write_backtest_md(result, args.out / "backtest_np.md")
    s = result["summary_all"]
    print(json.dumps({k: s.get(k) for k in ("trades", "win_rate_pct", "t1_hit_rate_pct", "expectancy_r", "max_drawdown_pct_at_10pct_alloc")}))
    print(f"Calibrated: {result['calibrated']} — {result.get('walk_forward', {}).get('reason')}")
    print(f"Saved {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nepse_ta", description="NEPSE 5-agent technical scanner")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--source-dir", type=Path, help="Local nepse-data/data/company-wise directory (skip download)")
        p.add_argument("--cache-dir", type=Path, default=ROOT / ".cache" / "nepse-data")
        p.add_argument("--sector-map", type=Path, default=DEFAULT_MAP_PATH)
        p.add_argument("--symbols", help="Comma-separated subset of symbols")

    ps = sub.add_parser("scan", help="Run the daily scan and write reports")
    common(ps)
    ps.add_argument("--out", type=Path, default=ROOT / "reports")
    ps.add_argument("--calibration", type=Path, default=ROOT / "reports" / "backtest" / "latest.json")
    ps.add_argument("--narrative", action="store_true", help="Add optional AI narrative (needs ANTHROPIC_API_KEY)")
    ps.add_argument("--now", help="Override current time (ISO, UTC) for reproducible runs")
    ps.set_defaults(func=cmd_scan)

    pb = sub.add_parser("backtest", help="Run the historical backtest + walk-forward calibration")
    common(pb)
    pb.add_argument("--out", type=Path, default=ROOT / "reports" / "backtest")
    pb.add_argument("--workers", type=int, default=None)
    pb.set_defaults(func=cmd_backtest)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
