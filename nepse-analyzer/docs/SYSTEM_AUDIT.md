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

---

## 9. Phase 1 implemented — analysis memory & recommendation ledger (branch `nepse-v2`)

**Production untouched:** `.github/workflows/nepse-daily-scan.yml` on `nepse-v2` is byte-identical to the
production branch; no change to the 21:00 KST schedule, `nepse-reports` publishing or ntfy.

### Where data lives
Branch **`nepse-v2-state`** (separate from `nepse-reports`), written by `.github/workflows/v2-memory.yml`.
Nothing depends on runner disk: each run checks the branch out, verifies it, appends, commits and pushes.

```
state/analyses/<YYYY>/<YYYY-MM-DD>.jsonl.gz   one record per stock per trading date (+ revisions), gzip members
state/plan_changes.jsonl                      meaningful plan changes with old plan, new plan, reason
state/recommendations.jsonl                   recommendation events (created → triggered → closed, …)
state/runs.jsonl                              one line per run: counts, freshness, missing/failed symbols
```

### Rules (all unit-tested)
| Rule | How |
|---|---|
| Never overwrite | Files are opened in append mode only. Every line stores `_prev` + `_hash` (SHA-256 chain); an edited or deleted line raises `IntegrityError`, and the writer refuses to append to a broken file. Git history keeps every version as a second layer. |
| Duplicate run | Record content is hashed; identical content for the same stock and trading date is counted as a duplicate and **not appended**. CI runs the update twice per job and fails unless the second run appends 0 records. |
| Revised analysis | Different content for the same stock/date → new line with `revision`, `supersedes` and a factual `revision_reason` (which sections changed, whether source data or strategy version changed). The original line is never touched. |
| Missing data | A stock with no new candle gets no record and is listed in `runs.jsonl → no_new_candle`; failed files are listed under `failed`. |
| Stale data | Records are keyed by the data's trading date, so a stale re-run only produces duplicates; staleness itself lives in the record's `context`, not in the hashed analysis. No recommendation is created when market data is `blocked`. |
| Plan changes | Logged when classification changes, or — for actionable stocks (A/B/C/E) — when the plan type changes or a level moves > 1 %. (Daily ATR jitter on no-trade stocks is ignored; it produced ~310 meaningless "changes"/day before this rule.) |
| Recommendations ≠ trades | `kind: system_recommendation_hypothetical`. The system never records or assumes a user execution. |
| One active rec per stock | A new eligible setup on a stock with a pending/open recommendation is skipped and logged. |
| Every record carries | trading date, run id, KST/UTC timestamps, source commit/date, freshness, `strategy_version` (`v1.0`), `execution_model` (`exec-1`), code commit. |

### Stored per stock per day
Price (close, change, 20-day return, 52-week range), volume (volume, relative volume, reliability, turnover,
liquidity flag), technicals (trends, status, SMAs, RSI, MACD, ATR, candle, patterns, support/resistance
zones), plan (type, entry zone, entry trigger, stop + basis, T1/T2 + basis, T3 = null, R:R, **`target_is_projection`**),
thesis, confirmation and invalidation conditions, scenarios, heuristic score, A–E classification, eligibility
with reasons, warnings. `smc` and `events` are stored as `{"status": "not_available", "reason": …}` until
Phases 2 and 5 — never as empty "nothing found".

### Outcome model `exec-1` (paper trading)
Entry window 3 sessions; fill at the open inside the zone, limit fill at the zone top after a gap up,
**no buying below the zone** (only a fill at entry_low if price trades back into it without touching the
stop); stop touched first → `invalidated_before_entry`; target reached without a fill → `missed_without_entry`
(never a win); stock not trading for > 5 days → `expired_stale`; T+2 lock (3 sessions), stop before target
inside one bar, gaps fill at the open, full exit at T1, time exit after 20 sessions; commission, SEBON, DP,
slippage and CGT; MFE/MAE in % and R; bonus/right adjustments rescale stored levels so a mechanical price
drop is not a loss. Data revisions append a `correction` event instead of editing history.

### Verification
* 76 unit tests pass (17 new in `tests/test_memory.py`: chain + tamper + deletion, duplicate run, missing candle,
  stale/blocked, revision, recommendation creation, all entry/exit outcomes, bonus rescale, corrections,
  plan-change rules, required fields).
* Mutation check: deliberately breaking 9 key lines (no bonus rescale, no duplicate check, overwrite instead
  of append, no chain check, counting untriggered targets, recommending on blocked data, ignoring costs,
  self-reclassification, silent overwrite on revision) — every mutant is caught by at least one test.
  Two tests were too weak at first and were strengthened.
* Real-data replay of the last 15 sessions (`scripts/replay_memory.py`, `mode: replay`, scratch dir only):
  325 records on day 1, then ~315 new + duplicates per day, 5–24 plan changes/day, 30 recommendations,
  24 triggered, 10 closed. **Replay results are a mechanics check, not evidence of edge** (10 trades).
* Storage: ≈130 KB per trading day (≈33 MB/year).

### Limitations (Phase 1)
* **No daily v2 schedule yet.** GitHub runs scheduled workflows only from the default branch, so the v2 job
  runs only when `nepse-v2` is pushed. Recording "every day from today" needs one approved change: adding the
  v2 step to the production workflow (or merging `nepse-v2`). Until then, days without a push are not recorded
  live (they can be replayed, but replayed records are labelled `mode: replay`).
* Content quality is still v1: template thesis, synthetic 2R/3R targets (now flagged), no SMC/events.
* `exec-1` exits fully at T1 (no scaling out), ignores order-book depth and circuit queues, and counts holding
  time in the stock's own bars.
* Actual user executions are not tracked (by design); a separate user-trade log can be added if wanted.
* The hash chain proves files were not edited in place; someone with push rights could still rewrite the whole
  branch. Protecting `nepse-v2-state` with a branch rule (no force-push) would close that.

---

## 10. Phase 2 implemented — market structure & SMC (`smc-1`, branch `nepse-v2`)

Rules: `docs/SMC_SPEC.md` (approved 2026-11-03). **Pre-registered, not tuned, not proven profitable.** Output is an
OHLCV-based price-structure interpretation; it never claims institutional orders, "smart money" or stop orders.

### What was added
* `nepse_ta/smc.py` — streaming engine: bar *t* is processed using bars ≤ t only, in the fixed order of spec §3.13.
  Swings (k=3 daily / 2 weekly, 1-ATR filter, alternation/replacement), HH/HL/LH/LL and state, BOS / CHoCH (MSS-like) /
  range break with close-vs-wick, displacement, volume and failure states, equal highs/lows, sweeps with reaction
  states, order blocks (primary [low, high] + body, symmetric, leg after the broken swing, fresh/tested/invalidated/
  expired), FVGs (fill %, expiry, circuit/long-gap flags), premium/discount (only for a clear ≥ 2 ATR range), weekly
  structure from **completed weeks only**, up/down-day volume ratio, and Nepali explanation items built only from
  computed fields.
* Memory records now carry `analysis_version: "smc-1"` and the `smc` section; the v1.0 plan, stop, targets,
  eligibility and recommendation rules are byte-for-byte unchanged (`strategy_version: v1.0`). Ledger summaries are
  split by `strategy_version` (v2.0 recommendations only after Phase 6).

### Implementation-time clarification (disclosed)
Unit tests showed the approved OB leg window ("lowest low in j−10..j") picks a low from *before* the broken swing in
an HH/HL uptrend, i.e. the wrong candle. The window now starts after the broken swing (spec §3.12 note). Logic fix
found by tests before any result was looked at; no parameter changed.

### Bugs found and fixed during Phase 2
| Bug | Effect | Fix |
|---|---|---|
| Unclassified stocks processed twice per run (`res.unclassified` ⊂ `res.analyses`) — **present since Phase 1** | 4 symbols (HEIP, HIDCLP, NIMBPO, RBCLPO) have duplicate lines in the live `2026-11-02` file (16 of 640 lines). Append-only: they stay; readers use the latest line per symbol, so meaning is unchanged. | Unique symbols per run; test + mutation check |
| Revision reason compared fresh (tuples) vs stored (lists) content | Reason text listed sections that had not changed (hash was correct) | Compare canonical JSON |
| Staleness-derived ineligible reasons in hashed content | Stale stocks re-revised as days pass | Moved to record `context` |
| Empty weekly frames had object dtype | 1 false weekly "mismatch" in the causality replay | Typed empty frame |
| Engine O(n²) loops | 0.94 s per long series | Age-bounded newest-first iteration (exact) → 0.37 s |

Production note (not changed, v1 scope): `nepse_ta/cli.py scan` writes `res.analyses + res.unclassified` to the v1
CSV, so the 4 unclassified stocks appear twice in the production `stocks.csv` too.

### Verification
* **117 tests pass** (35 SMC + memory/other); lint clean.
* Mandatory look-ahead tests: snapshot from one pass over the full series == fresh engine on data truncated at t;
  multiplying all future prices ×3 leaves t unchanged; scaling all prices ×0.9 leaves every label/event unchanged;
  incomplete week never used; mirror-image (bullish ↔ bearish) test for swings, BOS, CHoCH, OB.
* Mutation check: 12 rule mutations (BOS on wick, peeking 2 future bars, non-strict tie, no swing filter, no OB
  displacement, old OB window, no FVG minimum, incomplete week, CHoCH labelled BOS, no sweep minimum, keep duplicate
  stocks, …) are all caught; one mutation (break of a not-yet-confirmed swing) is *equivalent* — swings are only
  appended after confirmation, so the guard cannot be reached.
* **Causality replay on real data** (30 random stocks, every 5th session 2025-01 → 2026-10): **2,515 daily checks,
  0 mismatches; 2,515 weekly checks, 0 mismatches** (after the dtype fix).
* **Descriptive statistics** (244 stocks, 413 stock-years, 2025–26; *no performance claim*): per stock-year ≈ 37
  swings, 1.3 bullish / 2.3 bearish BOS, 1.9 / 2.0 CHoCH, 3.0 / 3.5 range breaks, 1.9 / 1.8 OBs, 11 / 7 FVGs,
  14–16 sweeps per side, 2–3.5 equal-high/low zones. A break event occurs on 5.7 % of bars. Outcomes: BOS 1,289 failed
  vs 196 intact; CHoCH 860 failed, 699 structure-confirmed; FVG mostly filled (4,202) or invalidated (2,419). Flags:
  528 FVGs on circuit-like days, 1,135 across long gaps — warnings, not removed.
* Live v2 run (`41566921932`): 325 revisions once (`analysis_version_changed (v1-only → smc-1)`), second run 325
  duplicates, 0 new recommendations, v1 plans identical; hash chain ok.

### Limitations
* Daily resolution only: intraday order of sweep vs break is unknown; no lower timeframe.
* Volume has no buy/sell split; "accumulation-like" is an up-day/down-day ratio only.
* Circuit-limit days and holidays create artificial gaps/zones (flagged).
* Many BOS fail and many FVGs fill — whether any of this helps trading is untested until Phase 7.
* Record size roughly doubled (~245 KB per trading day gzip, ≈ 60 MB/year).
