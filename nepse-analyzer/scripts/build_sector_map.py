"""Build ``config/sector_map.csv`` by cross-validating two independent NEPSE sector sources.

Why two sources?
    The OHLC repository (Aabishkar2/nepse-data) contains no sector information, and
    NEPSE's own website is not always reachable from CI. Both sources below are
    snapshots of NEPSE's official security API (``/api/nots/security`` and
    ``/api/nots/security/classification``) published in public GitHub repos.
    A symbol is classified only when BOTH sources agree on the sector. Anything
    else goes to "Unclassified" -- we never guess.

Usage::

    python scripts/build_sector_map.py                 # download sources and rebuild
    python scripts/build_sector_map.py --symbols-dir /path/to/nepse-data/data/company-wise

The output records the SHA-256 of each source file so the mapping is auditable.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_ta.sectors import agent_for  # noqa: E402

SOURCE_A_URL = "https://raw.githubusercontent.com/Shubhamnpk/yonepse/HEAD/data/other/securities.json"
SOURCE_B_URL = (
    "https://raw.githubusercontent.com/coprashant/DasKitta/HEAD/backend/data/nepse/company-sectors.json"
)
OHLC_RAW_BASE = "https://raw.githubusercontent.com/Aabishkar2/nepse-data/main/data/company-wise/"


def _download(url: str) -> bytes:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def build(symbols: list[str], raw_a: bytes, raw_b: bytes) -> tuple[list[dict], dict]:
    """Cross-validate the two sources for ``symbols``. Returns (rows, provenance)."""
    a_list = json.loads(raw_a)
    b_doc = json.loads(raw_b)
    a = {d["symbol"]: d for d in a_list}
    b: dict[str, str] = b_doc["sectors"]

    rows: list[dict] = []
    for sym in sorted(symbols):
        rec = a.get(sym)
        sec_a = rec.get("sectorName") if rec else None
        sec_b = b.get(sym)
        instrument = rec.get("instrumentType") if rec else None
        if sec_a and sec_b and sec_a == sec_b and instrument:
            sector, confidence, note = sec_a, "high", "both sources agree"
        else:
            sector, confidence = "Unclassified", "none"
            if not sec_a and not sec_b:
                note = "not in either source (possibly delisted/merged or promoter share)"
            elif sec_a != sec_b:
                note = f"sources disagree or one missing: A={sec_a!r} B={sec_b!r}"
            else:
                note = "instrument type unknown"
        rows.append(
            {
                "symbol": sym,
                "company_name": (rec or {}).get("companyName", ""),
                "sector": sector,
                "instrument_type": instrument or "",
                "nepse_status": (rec or {}).get("status", ""),
                "agent": agent_for(sector, instrument or ""),
                "confidence": confidence,
                "note": note,
            }
        )
    provenance = {
        "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_a": {"url": SOURCE_A_URL, "sha256": hashlib.sha256(raw_a).hexdigest(), "records": len(a)},
        "source_b": {
            "url": SOURCE_B_URL,
            "sha256": hashlib.sha256(raw_b).hexdigest(),
            "records": len(b),
            "source_updated_at": b_doc.get("updatedAt"),
        },
        "rule": "classified only if source A sectorName == source B sector and A has instrumentType",
    }
    return rows, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols-dir", type=Path, help="Local data/company-wise dir to read symbols from")
    parser.add_argument("--symbols-file", type=Path, help="Text file with one symbol per line")
    parser.add_argument("--source-a", type=Path, help="Local copy of source A (skip download)")
    parser.add_argument("--source-b", type=Path, help="Local copy of source B (skip download)")
    parser.add_argument("--out", type=Path, default=ROOT / "config" / "sector_map.csv")
    args = parser.parse_args()

    if args.symbols_dir:
        symbols = [p.stem for p in args.symbols_dir.glob("*.csv")]
    elif args.symbols_file:
        symbols = [s.strip() for s in args.symbols_file.read_text().splitlines() if s.strip()]
    else:
        from nepse_ta.data.fetcher import list_remote_symbols

        symbols = list_remote_symbols()
    if not symbols:
        sys.exit("No symbols found")

    raw_a = args.source_a.read_bytes() if args.source_a else _download(SOURCE_A_URL)
    raw_b = args.source_b.read_bytes() if args.source_b else _download(SOURCE_B_URL)
    rows, prov = build(symbols, raw_a, raw_b)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    prov_path = args.out.with_name("sector_map_provenance.json")
    prov["counts"] = {}
    for r in rows:
        prov["counts"][r["agent"]] = prov["counts"].get(r["agent"], 0) + 1
    prov_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} rows to {args.out}")
    print(json.dumps(prov["counts"], indent=2))


if __name__ == "__main__":
    main()
