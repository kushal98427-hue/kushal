# System audit — NEPSE scanner before the v2 upgrade

Audit date: 2026-11-03 · audited code: `claude/busy-cori-0u6n0g` @ `c347ee3` · audit branch: `nepse-v2`
Everything marked ✅ was checked by running it (locally or on GitHub Actions), not by reading code alone.

---

## 1. What the system is today (v1)

```
GitHub Actions (daily cron 12:00 UTC = 21:00 KST)
  └─ python -m nepse_ta scan
       1. fetch      data/fetcher.py      372 CSVs from Aabishkar2/nepse-data (tree API + blob-SHA cache)
       2. validate   data/validation.py   dedupe, bad rows, OHLC repair, bonus/right back-adjustment
       3. freshness  freshness.py         data date vs expected latest closed session
       4. analyse    analysis.py          per stock: trend, MAs, RSI/MACD/ATR, pivots→zones, plan, score
       5. agents     agents/*.py          5 sector agents + master ranking
       6. report     reports/*.py         Nepali Markdown, CSV, JSON
       7. publish    workflow             nepse-reports branch + artifact
       8. notify     notify.py            ntfy / Telegram (optional secrets)
  └─ weekly: python -m nepse_ta backtest  (walk-forward, costs, T+2)
```

4,266 lines of Python, 59 unit tests, one workflow (`.github/workflows/nepse-daily-scan.yml`).

## 2. What works (verified)

| Area | Evidence |
|---|---|
| Data fetch | Runs #3–#7 on GitHub: 372 files; second fetch in the same run = 372 cache hits (blob SHA). |
| Data validation | 59 tests incl. duplicates, malformed rows, OHLC repair, bonus adjustment, breaks. |
| **Bonus adjustment** | Cross-checked against an independent dividend dataset (§5): **473 of 493 bonus book-closures since 2021 detected with the correct factor (±2 %)**, 2 treated as breaks, 17 missed, 1 wrong factor. |
| Freshness | Report says `STALE … आज … को बजारको होइन` when the latest session is missing; trading weekdays inferred from data (NEPSE moved Sun–Thu → Mon–Fri in 2026). |
| Sector map | 360/372 symbols agree in two NEPSE-API snapshots; 12 left Unclassified. |
| Backtest mechanics | No look-ahead (tested by multiplying all future prices ×3), next-open entry, stop-first ordering, T+2 lock, costs, capital-constrained portfolio. See `docs/BACKTEST_AUDIT.md`. |
| Publishing | `nepse-reports` branch updated by runs #3–#7 (latest `6b4d7a5`). |
| ntfy | Runs #6/#7: `"ntfy": "sent"`; secret fingerprint matches the generated topic. Runner self-test: published and read back from ntfy.sh. Phone receipt depends on the app being subscribed to the right topic (user's side). |
| Schedule | Workflow `active` on the default branch, cron `0 12 * * *`. |

## 3. What is incorrect or unreliable

| # | Finding | Impact |
|---|---|---|
| 1 | **Synthetic targets.** When no resistance exists above entry, T1 = entry + 2R, T2 = 3R. **56 % of master-list backtest trades (1,207 of 2,164)** used this. Live example: CZBIL and GBIME on 2026-10-30 both had R:R exactly 2.00 / 3.00. | Violates "targets must be technically plausible"; the R:R filter is partly circular. |
| 2 | **No profitable configuration.** After costs: all setups −0.16R, master list −0.02R, 10-slot portfolio −33.5 % (max DD −64.6 %), holdout 2025–26 −0.26R. | The current rules should not drive real money. |
| 3 | **Min R:R 1.5 was never tested.** Sweep on existing trades (score ≥ 60, liquid): 2019–24 expectancy −0.005R … +0.046R for thresholds 1.0–2.0 (CIs include 0); 2.5 and 3.0 are worse (−0.17R, −0.23R); **every threshold is negative in the 2025–26 holdout** (−0.15R … −0.57R). | No threshold shows reliable positive expectancy. |
| 4 | **Scheduled runs are late.** The first scheduled run (#5) started 20:57 UTC — **8 h 57 m after 12:00 UTC** (05:57 KST next morning). | "Daily at 21:00 KST" is not reliable on GitHub's free scheduler. |
| 5 | **Report overwrites.** `reports/<data-date>/` is replaced by every later run on the same data date (runs #6 and #7 both rewrote `2026-11-02`). Old versions survive only in git history. | No auditable memory of what was said when. |
| 6 | Circuit-lock modelling is a no-op (only 2 locked bars since 2019 in this data). | Execution risk on limit days is under-modelled. |
| 7 | Market regime uses a home-made equal-weight index; the official NEPSE index is not used. | Regime labels are a proxy. |
| 8 | Repository is **public**: code and daily reports are visible to anyone (secrets are not). | Privacy, not security. |

## 4. What is missing (against the v2 specification)

| Spec item | Status in v1 |
|---|---|
| Market structure HH/HL/LH/LL, structure shifts | ❌ only SMA-based trend labels |
| SMC: BOS, CHoCH/MSS, liquidity sweeps, equal highs/lows, order blocks, FVG, premium/discount | ❌ none |
| Multi-timeframe (weekly + daily) | ⚠️ weekly trend label only |
| Volume behaviour (accumulation/distribution, volume at levels) | ⚠️ relative volume only |
| Relative strength vs NEPSE index / sector | ❌ |
| Evidence chain (observation → evidence → interpretation → confirm/invalidate) | ❌ template sentences |
| News & upcoming events with sources | ❌ |
| Financial-report timing | ❌ |
| Corporate-action calendar (announce/book close/adjustment), economic-return accounting | ⚠️ adjustment inferred from prices only |
| Lock-in expiry & supply | ❌ |
| T3, per-target R:R, holding period | ⚠️ T1/T2 only |
| Position sizing & portfolio limits | ❌ |
| Classification A–E | ⚠️ valid setup / watchlist / breakdown only |
| **Daily analysis memory & yesterday-vs-today** | ❌ |
| **Recommendation tracking (triggered?, MFE/MAE, realized R), paper-trading ledger** | ❌ |
| Strategy versioning | ❌ |
| Analytical confidence (not probability) | ⚠️ heuristic score + T1 hit rate |
| Failure handling (no misleading partial report) | ⚠️ publish step is skipped on failure; failure ntfy exists |

## 5. Data sources (checked 2026-11-03)

| Source | Reachable from GitHub runner | Contents verified | Use in v2 |
|---|---|---|---|
| `Aabishkar2/nepse-data` | ✅ | Daily OHLCV, 372 symbols, latest 2026-11-02; no index, no intraday | Primary prices (keep) |
| `Shubhamnpk/yonepse` (third-party mirror of NEPSE API data, updated daily) | ✅ raw.githubusercontent | NEPSE index **1997→2026-10** · dividend/bonus history **2,514 records** with announce + book-close dates · **14,288 financial-report submission dates since 2021-04** · NEPSE disclosures (rolling ~3 months: AGM, book close, dividend, lock-in open notices with official nepalstock PDF links) · exchange messages (bonus listing, promoter→public conversion) · floor sheet with broker IDs since 2024-01 | Index & regime, corporate-action calendar, report timing, lock-in events. **Unofficial mirror: validate, record provenance, fail safe if stale.** |
| ShareSansar, Merolagani | ✅ HTTP 200 | HTML pages (news, announcements) | News for shortlisted stocks, cross-check |
| SEBON, CDSC | ✅ HTTP 200 | HTML | Right-share approvals, official notices |
| NEPSE official API | ❌ HTTP 401 (auth handshake) | — | Not used directly; reached through the mirror |
| NepseAlpha | ❌ HTTP 403 (bot block) | — | Not used |

Not available anywhere checked: market consensus estimates, intraday candles, official adjustment-price records as structured data, full lock-in schedules with share counts (only in individual notices).

## 6. What to preserve

Data fetch + cache, validation and bonus detection, freshness check, sector map, causal indicators, backtest engine and audit tooling, report publishing to `nepse-reports`, ntfy, the 21:00 KST cron, all 59 tests.

## 7. What to improve / build (v2 plan, summary)

1. **Shadow mode first.** v2 runs inside the same workflow and writes to `reports/v2/…`; v1 stays the production report until v2 is backtested, paper-traded and approved.
2. **Memory** (`state/` on the `nepse-reports` branch): append-only daily analysis records (JSONL per day) + a recommendation ledger + plan-change log. Never overwrite.
3. **Structure & SMC module** with explicit, unit-tested rules: swing points, HH/HL labels, BOS (close-confirmed), CHoCH, equal highs/lows, sweeps, order blocks (with displacement + mitigation), FVGs (fill state), dealing range & premium/discount, weekly/daily alignment.
4. **Events module**: corporate actions, report timing (historical cadence + last submission), lock-in notices, news links — each item with source, date, status (confirmed / estimated / unavailable). Point-in-time only (announce/submission dates) for backtests.
5. **Trade planner**: entries from structure, stops beyond invalidation, T1–T3 only from real levels (resistance, liquidity, FVG, measured move — each labelled), reject when no plausible target; per-target R:R; position size from a configurable risk budget, liquidity cap.
6. **Classification A–E**, analytical confidence with listed reasons.
7. **Backtest v2 vs v1** with the same engine; R:R thresholds and filters compared walk-forward; untouched holdout 2025–26.
8. **Report** in the 9-part Nepali structure; ntfy summary.
9. **Reliability**: no partial publish, failure alert, mirror-staleness guard; scheduled-run lateness check.

## 8. Risks

* The strongest negative: v1 has no edge after costs. v2 may not have one either; the backtest will say so plainly.
* The mirror can stop updating or change format; v2 must detect this and mark event data "unavailable".
* Scraping ShareSansar/Merolagani is fragile; keep it to shortlisted stocks, cache results, and never fill gaps with guesses.
* GitHub schedule delays (finding #4) are outside our control.
