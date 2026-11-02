# NEPSE 5-Agent Daily Technical Analysis System

A deterministic, tested scanner for Nepal Stock Exchange (NEPSE) stocks. Every day at
**21:00 Korea time** it downloads public OHLC data, validates it, analyses every stock through
five sector agents plus a master agent, and publishes Nepali Markdown, CSV and JSON reports.

> ⚠️ Educational technical analysis, not investment advice. The **setup score is a heuristic
> ranking, not a probability.** The backtest (below) shows these setups have had roughly zero
> or negative average results after trading costs — treat the output as a screening list.

---

## What it does

| Part | Module | What happens |
|---|---|---|
| Data fetching | `nepse_ta/data/fetcher.py` | Lists CSVs via the GitHub API, downloads from `raw.githubusercontent.com` with retries, git-blob-SHA + ETag caching. One failed ticker is logged, never fatal. |
| Validation | `nepse_ta/data/validation.py` | Sorts, de-duplicates, drops malformed/invalid rows, repairs inconsistent high/low (flagged), keeps missing volume as *missing* (never 0), **detects bonus/right-share price adjustments**, flags unexplained jumps. |
| Indicators | `nepse_ta/indicators.py` | SMA 20/50/100/200, Wilder RSI(14), MACD(12,26,9), Wilder ATR(14), relative volume, weekly bars, swing pivots — all causal (no look-ahead, tested). |
| Patterns & levels | `patterns.py`, `levels.py` | Engulfing, hammer, shooting star, doji, inside bar, marubozu, morning/evening star; support/resistance zones from confirmed swing pivots. |
| Per-stock analysis | `analysis.py` | Trend (daily/weekly), breakout/breakdown/consolidation, long-only trade plan (entry zone, invalidation, stop, T1, T2, R:R), bullish/bearish scenarios, warnings. |
| Scoring | `scoring.py` | Transparent 0–100 setup score; every rule and point value is printed in the report. |
| Sector agents | `agents/sector_agent.py` | 5 agents: breadth per group, ranked valid setups, watchlist, breakdowns. Agent 4 compares life vs non-life insurance. |
| Master agent | `agents/master.py` | Cross-sector ranking; prints **"No valid setup today"** instead of forcing picks. |
| Backtest | `backtest.py` | Same `analyze_at()` as the live scan, next-open entries, T+2 settlement lock, NEPSE costs + CGT, walk-forward calibration. |
| Reports | `reports/` | `stocks.csv`, `scan.json`, `master_np.md`, `report_np.md`, `agents/*.md`, `backtest_np.md`. |
| Optional AI text | `narrative.py` | Nepali summary via the Claude API, only if `ANTHROPIC_API_KEY` is set. |

### Verified facts about the source data (checked 2026-11-02)

* Repo `Aabishkar2/nepse-data`, branch **`main`**, files `data/company-wise/<SYMBOL>.csv` (372 files).
* Columns: `published_date,open,high,low,close,per_change,traded_quantity,traded_amount,status`.
* Ticker naming = NEPSE trading symbol (e.g. `NABIL.csv`); includes debentures (`NBLD87`),
  mutual funds (`NMB50`), promoter shares (`NIMBPO`) and delisted/merged banks (`NIB`, `BOKL`).
* **No sector column** → validated mapping in `config/sector_map.csv` ([sources](config/SECTOR_MAP_SOURCES.md)).
* **Prices are not adjusted for bonus/right shares**, e.g. NABIL shows −20% "drops" on book-closure
  days. `per_change` is computed against NEPSE's adjusted previous close, so the system recovers the
  adjustment factor (example: NABIL 2026-09-30, factor 0.952 = 5% bonus) and back-adjusts history.
* Quality issues found: duplicate dates in 122 files, unsorted rows in 104, ~40k rows (mostly
  2011–2018) where high/low do not contain open/close, 14 non-positive prices.
* Trading days are Sunday–Thursday (plus some Fridays in 2022 and 2026).
* The source updates itself 13:00–17:00 UTC (18:45–22:45 Nepal time).

---

## Setup on your computer (step by step)

You need **Python 3.12 or newer** and **git**.

```bash
# 1. Get the code
git clone <your-repo-url>
cd <your-repo>/nepse-analyzer

# 2. Create an isolated Python environment (recommended)
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install libraries
pip install -r requirements.txt

# 4. Run the tests (should print "40 passed")
python -m pytest -q

# 5. Run a real scan (downloads ~40 MB the first time, then only changed files)
python -m nepse_ta scan

# 6. (Optional) run the historical backtest, ~2-5 minutes
python -m nepse_ta backtest
python -m nepse_ta scan            # re-run so the report includes backtest evidence
```

Reports appear in `reports/<data-date>/` and a copy in `reports/latest/`. Open
`reports/latest/master_np.md` first.

Useful options:

```bash
python -m nepse_ta scan --symbols NABIL,NICA,UPPER     # only some stocks
python -m nepse_ta scan --source-dir ../nepse-data/data/company-wise   # use a local clone, no download
python -m nepse_ta scan --narrative                    # add AI summary (needs ANTHROPIC_API_KEY)
python -m nepse_ta -v scan                             # verbose logging
```

---

## Daily automation on GitHub Actions

Workflow: [`.github/workflows/nepse-daily-scan.yml`](../.github/workflows/nepse-daily-scan.yml)

* **Schedule:** `cron: "0 12 * * *"` → 12:00 UTC = **21:00 KST** (UTC+9). South Korea has no
  daylight-saving time and GitHub cron always runs in UTC, so the time never shifts. (Nepal has no
  DST either.) GitHub can start scheduled jobs a few minutes late at busy times.
* **Important timing note:** at 21:00 KST it is 17:45 in Nepal, *before* the source repo's first
  update attempt (18:45 NPT). So the 21:00 run analyses the **previous** trading session. The report
  always shows the exact data date. If you want same-day data, change the cron to e.g.
  `"30 18 * * *"` (03:30 KST next morning).
* **Manual run:** GitHub → *Actions* → *NEPSE daily technical scan* → *Run workflow* (options:
  re-run backtest, subset of symbols).
* **Outputs:** (1) a downloadable artifact on each run (kept 30 days), and (2) commits to a dedicated
  **`nepse-reports`** branch under `reports/`. A separate branch keeps your main branch clean and
  avoids triggering a Netlify build of the other app in this repository every day.
* **Backtest** re-runs every Saturday (UTC), on request, or if no previous result exists.
* **Permissions:** only `contents: write` (to push the reports branch). Source data is only read.
* **Scheduled workflows run from the default branch**, so this file must be on the repository's
  default branch for the 21:00 schedule to start.

### Optional AI narrative (paid, off by default)

The scanner never needs an API key. To add a short AI-written Nepali summary:

1. Get an Anthropic API key (billed per use).
2. GitHub repo → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*
   → name `ANTHROPIC_API_KEY`.

The model only sees the already-computed summary and is instructed not to add numbers.
Default model `claude-opus-5-5` (override with env `NEPSE_LLM_MODEL`).

---

## How to read the report

* **Setup types** (long-only, because NEPSE has no short selling):
  * *Breakout*: close above the prior 20-session high while above SMA50. Entry zone = level to
    level + 0.5 ATR (do not chase above it).
  * *Pullback*: daily uptrend, price touched SMA20 or support, RSI 40–60, green close.
  * *Watch (निगरानी)*: not a setup — a trigger level to watch.
* **Stop-loss**: just under the nearest support (−0.25 ATR), kept between 1 and 2 ATR from entry.
* **Targets**: next resistance zones; if none exist, 2R / 3R projections (marked as such).
* **Master-list rules**: active setup, R:R to T1 ≥ 1.5, score ≥ 60, adequate liquidity
  (median 20-day turnover ≥ NPR 20 lakh), fresh data, known sector.
* All thresholds live in `nepse_ta/config.py`.

## Backtest and probabilities

* Rules: signal on bar *t* (data ≤ *t* only) → buy next open + slippage → no selling for 3 sessions
  (T+2 settlement) → exit at stop or T1 (stop assumed first if both inside one candle; gaps fill at
  the open) or after 20 sessions.
* Costs (verify with your broker — rates change): commission 0.36 %, SEBON 0.015 %, DP NPR 25,
  slippage 0.25 % per side, CGT 7.5 % on gains.
* Walk-forward: each year from 2022 is tested out-of-sample against all earlier years. Only if the
  out-of-sample error of the T1 hit rate per score bucket is ≤ 10 percentage points over ≥ 300 trades
  is the run marked *calibrated*. Then the report shows a **historical T1 hit rate with a 95 %
  confidence interval and expectancy** — still not called a probability.
* Survivorship bias: delisted companies present in the source repo are included; companies the repo
  never had cannot be.

**Result on real data (2019-01 → 2026-10, 346 stocks, 12,307 trades):** calibration passed
(5.2 pp OOS error), but the average result after costs is negative for all setups
(−0.16 R) and about break-even for master-list setups (−0.014 R, profit factor 0.95, 2,153 trades).
Higher scores do have better expectancy (−0.38 R → −0.04 R). Full table: `sample-output/backtest_np.md`.

## Tests

`python -m pytest -q` — 40 tests covering indicators (vs. reference RSI, causality), data validation
(duplicates, malformed rows, OHLC repair, bonus adjustment, breaks), scoring, backtest mechanics
(stop-first, gap fills, T+2 lock, costs, walk-forward, no look-ahead) and an end-to-end scan.

## Known limitations

* Small bonus issues during long trading halts (> 14 days) may not be detected.
* If the GitHub API is unreachable, only symbols in `sector_map.csv` are downloaded (new listings
  appear after the next sector-map rebuild).
* Cost rates are configurable defaults, not live values.
* Technical analysis only — no fundamentals, news, or corporate announcements.
