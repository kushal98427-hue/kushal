# Sector map: sources and validation

`sector_map.csv` maps every symbol in `Aabishkar2/nepse-data/data/company-wise/` to a NEPSE
sector, instrument type and analysis agent. The OHLC repository itself has **no sector data**,
and NEPSE / ShareSansar / Merolagani websites were not reachable from the build environment, so
the map is built from two independent public snapshots of NEPSE's official security API:

| Source | What it is | Used for |
|---|---|---|
| A — `Shubhamnpk/yonepse` → `data/other/securities.json` | Snapshot of NEPSE `/api/nots/security` (650 records: `sectorName`, `instrumentType`, `status`) | sector, instrument type, company name, listing status |
| B — `coprashant/DasKitta` → `backend/data/nepse/company-sectors.json` | Snapshot of NEPSE `/api/nots/security/classification` (648 records, `updatedAt` 2026-09-08) | independent sector check |

SHA-256 hashes of the exact files used, the build time and the per-agent counts are in
`sector_map_provenance.json`.

## Rules

1. A symbol is classified **only if source A and source B report the same sector** and source A
   has an instrument type. Otherwise it is `Unclassified` (never guessed).
2. NEPSE files mutual funds and debentures under their sponsor's sector (e.g. a bank's
   debenture has `sectorName = "Commercial Banks"`). So the instrument type is checked first:
   * `Mutual Funds` → Agent 5 (own "Mutual Fund" group)
   * `Non-Convertible Debentures` → excluded from technical analysis (bond prices)
   * `Equity` → agent by sector (banks → 1, development banks & finance → 2, hydro → 3,
     life & non-life insurance → 4, everything else → 5)
3. `nepse_status` `D` (delisted) / `S` (suspended) is kept as a warning; stale price data
   is detected separately from the CSV dates.

## Result (2026-11-02 build)

360 of 372 symbols agree in both sources. The 12 unclassified are 7 merged/delisted companies
(LBL, NIB, PLI, PLIC, RHPC, SLI, SLICL — no longer in NEPSE's list) and 5 promoter-share
symbols (HEIP, HIDCLP, NIMBPO, RBCLPO, SLBBLP).

## Rebuilding

```bash
python scripts/build_sector_map.py                                   # downloads both sources
python scripts/build_sector_map.py --symbols-dir /path/to/nepse-data/data/company-wise
```

Review the diff of `sector_map.csv` before committing — a sector change for a listed company
is rare and worth a manual check on nepalstock.com.
