# Backtest audit — NEPSE 5-agent scanner

Audit date 2026-11-02 · data `Aabishkar2/nepse-data@main` up to 2026-10-30 · signals 2019-01-01 → 2026-10-29
· 331 symbols traded (debentures excluded) · reproduce with
`python scripts/run_audit.py --source-dir <nepse-data>/data/company-wise` then `python scripts/write_audit_md.py`.

**Bottom line.** Before costs the rules show a small positive edge (all setups +0.13R, master list +0.24R).
After realistic NEPSE costs the edge is gone: all setups **−0.16R** (95% CI −0.26…−0.07), master list
**−0.02R** (CI −0.20…+0.16, i.e. indistinguishable from zero). A capital-constrained 10-slot portfolio of
master-list trades lost **−33.5 %** over 2019–2026 (CAGR −5.2 %, max drawdown **−64.6 %**). The untouched
2025–2026 holdout is the worst period (master −0.26R, win rate 32 %). This is a screening tool, not a
profitable strategy.

No strategy parameter was tuned on these results. All rule parameters (20-day breakout, SMA periods, RSI
bands, ATR stops, score weights) were fixed before the first backtest and are unchanged. One *data-cleaning*
parameter was changed after inspecting 2025 data (bonus-detection gap 7 → 14 days, to cover Dashain closures);
that is disclosed here.

## 1. Assumption-by-assumption audit

| # | Assumption / mechanism | Verdict | Evidence |
|---|---|---|---|
| 1 | **No look-ahead in indicators** | ✅ Correct | SMA/EMA/RSI/MACD/ATR are recursive or trailing; `test_indicators_are_causal` recomputes on truncated data and gets identical values at bar *t*. |
| 2 | **No future-data leakage in the decision** | ✅ Correct | `analyze_at(frame, t)` reads rows ≤ *t*; swing pivots are used only after their confirmation bar (pivot + 5); weekly bars are built from rows ≤ *t*; `test_analysis_has_no_lookahead` multiplies all future prices by 3 and the analysis at *t* is identical. |
| 3 | Bonus/right back-adjustment uses *later* factors | ✅ Acceptable | Adjustment rescales history by a ratio; returns inside a trade are unchanged and no rule uses absolute price levels. Trades that span an adjustment (159) give −0.162R vs −0.161R overall — no effect. |
| 4 | **Next-day entry** | ✅ Correct (fixed) | Signal at close *t*, buy at open *t+1* + slippage; skipped if the open is > 1 % above the entry zone, at/below the stop, or at/above T1. **Defect fixed:** an illiquid stock whose next bar came weeks later was still entered; now skipped if the next bar is > 5 calendar days away. |
| 5 | **Stop/target ordering** | ✅ Correct, conservative | Gap through stop → fill at the open; gap above T1 → fill at the open; if stop and T1 are both inside one candle, the stop is assumed first. Tested. |
| 6 | **Bonus/right detection** | ⚠️ Mostly correct | 738 events since 2019; implied bonus % clusters at 10 %, 5 %, 14 %, 15 %, 8 % (typical NEPSE bonus ratios); 61 % lie within 0.15 pp of an integer %. 268 of 387,105 rows still move > 10.5 % after adjustment (handled as segment breaks). Could not cross-check against official book-closure data (sites blocked). Small bonuses during > 14-day halts can still be missed. |
| 7 | **Transaction costs** | ⚠️ Correct formula, rates unverified | Commission 0.36 % (the smallest-trade slab; ~0.33 % applies at NPR 100k, so slightly conservative), SEBON 0.015 %, DP NPR 25, slippage 0.25 %/side, CGT 7.5 % on gains, no loss offset. Round trip ≈ 1.25 % + tax. Current SEBON/broker rates could not be verified online from this environment. |
| 8 | **Capital & overlapping positions** | ❌ was wrong → fixed | Old “max drawdown at 10 % per trade” compounded 12k trades sequentially, ignoring that dozens overlap → the reported −100 % was meaningless. Replaced by (a) cumulative-R drawdown and (b) a daily mark-to-market portfolio with 10 equal slots, highest score first when signals exceed slots. |
| 9 | **T+2 settlement** | ✅ Modelled, assumption documented | No exit before the 3rd session after entry; a stop breached while locked exits at the first allowed open if still below. Sensitivity “sell from 2nd session”: −0.161R (all), −0.018R (master) → result does not depend on it. |
| 10 | **Circuit limits** | ⚠️ Modelled but data can't show locks | Added: no buy on an upper-circuit single-price bar, no sell on a lower-circuit single-price bar. Since 2019 only 2 such bars exist in the data, so the model changes nothing (identical results). NEPSE OHLC does not reveal unfilled queues, so circuit-lock risk is **under-modelled**. |
| 11 | **Liquidity** | ⚠️ Partial | 3,509 of 12,349 trades are in stocks with median 20-day turnover < NPR 20 lakh; excluding them: −0.152R (no better). Fill size vs volume is not modelled (NPR 100k notional assumed fillable). |
| 12 | **Delisted stocks / survivorship** | ⚠️ Partial | 17 delisted/suspended symbols in the source *are* traded in the backtest (e.g. BOKL, CBL, NBB, GLICL). Companies the source never had cannot be included; the source holds ~370 of ~650 historical NEPSE securities. |
| 13 | **Missing / stale data** | ✅ fixed | Unexplained jumps split history into segments. **Defect fixed:** trades cut by such a break were silently dropped (biasing results upward); now closed at the last close as `data_break` and counted (5 trades). Only 66 trades still open at the data end are excluded. 40 trades took > 2×sessions+7 calendar days (trading gaps). |
| 14 | **Multiple signals per stock** | ✅ Correct | One position per stock; a new signal is considered only after the previous trade's exit bar. Across stocks overlap is allowed per-trade and handled by the portfolio simulation. |
| 15 | **R vs % consistency** | ✅ Consistent | R = net % ÷ planned risk % (entry incl. slippage → stop). Costs are inside the net %, so a stop-out is typically −1.1R…−1.3R. Raw/gross/net are all reported. |
| 16 | **Holding period unit** | ⚠️ Limitation | Counted in the stock's own bars, not market sessions; differs only for stocks with trading gaps (see #13). |
| 17 | **Market regime** | ✅ fixed in audit | Regime = equal-weight index (mean daily return, clipped ±10 %) vs its SMA200 and SMA50 slope, using data up to the signal date. A first median-based index was rejected because compounding medians drifts down (it labelled 2019–2026 mostly “bear”). Not the official NEPSE index (not in the source). |
| 18 | **Calibration claim** | ⚠️ Narrow meaning | Walk-forward T1-hit-rate error 5.1 pp over 9,041 OOS trades → “calibrated”, but that only means hit rates are *stable*; it says nothing about profitability, and per-fold errors reach 21 pp (2022). |
| 19 | **Confidence intervals** | ✅ | Win rate: Wilson. Expectancy: 1,000-rep bootstrap resampling whole calendar months (signals on the same day are correlated, so per-trade CIs would be too narrow). |

## 2. Performance breakdowns

All figures are per trade, net of costs unless the row says otherwise. Max DD (cum. R) is the largest
peak-to-trough fall of the cumulative R curve when trades are ordered by exit date (it is large for big
samples simply because many trades are summed; compare slices of similar size).

### Costs: raw (no costs) vs gross (after slippage) vs net (slippage + fees + DP + CGT)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| All setups — raw, no costs | 12283 | 55.8% | 5.84% | -6.252% | 0.5% | **0.13R** (0.028 … 0.228) | 1.18 | -448.96R | 6.7 |
| All setups — gross (slippage only) | 12283 | 54.3% | 5.464% | -6.505% | -0.001% | **0.029R** (-0.073 … 0.126) | 1.0 | -653.03R | 6.7 |
| All setups — net | 12283 | 50.2% | 4.69% | -6.653% | -0.964% | **-0.161R** (-0.257 … -0.068) | 0.71 | -2230.28R | 6.7 |
| Master list — raw, no costs | 2152 | 44.5% | 12.236% | -7.273% | 1.412% | **0.239R** (0.048 … 0.426) | 1.35 | -130.12R | 8.9 |
| Master list — gross (slippage only) | 2152 | 44.1% | 11.776% | -7.685% | 0.906% | **0.157R** (-0.032 … 0.344) | 1.21 | -181.74R | 8.9 |
| Master list — net | 2152 | 42.8% | 10.415% | -8.217% | -0.235% | **-0.021R** (-0.2 … 0.156) | 0.95 | -282.21R | 8.9 |

### Sensitivity to execution assumptions (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| All — baseline (circuit locks modelled, sell from 3rd session) | 12283 | 50.2% | 4.69% | -6.653% | -0.964% | **-0.161R** (-0.257 … -0.068) | 0.71 | -2230.28R | 6.7 |
| All — circuit locks NOT modelled | 12283 | 50.2% | 4.69% | -6.653% | -0.964% | **-0.161R** (-0.257 … -0.068) | 0.71 | -2230.28R | 6.7 |
| All — sell from 2nd session (T+2 optimistic) | 12863 | 50.7% | 4.382% | -6.452% | -0.964% | **-0.161R** (-0.244 … -0.079) | 0.7 | -2221.17R | 6.0 |
| All — excluding trades spanning a bonus/right adjustment | 12125 | 50.2% | 4.684% | -6.665% | -0.971% | **-0.162R** (-0.26 … -0.069) | 0.71 | -2210.95R | 6.7 |
| All — excluding low-liquidity stocks | 8791 | 49.6% | 5.064% | -7.088% | -1.065% | **-0.152R** (-0.26 … -0.045) | 0.7 | -1626.75R | 6.9 |
| Master — circuit locks NOT modelled | 2152 | 42.8% | 10.415% | -8.217% | -0.235% | **-0.021R** (-0.2 … 0.156) | 0.95 | -282.21R | 8.9 |
| Master — sell from 2nd session | 2235 | 43.2% | 10.116% | -8.102% | -0.227% | **-0.018R** (-0.198 … 0.154) | 0.95 | -285.22R | 8.5 |

### Market regime — all setups (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| bull | 9293 | 50.3% | 5.032% | -6.784% | -0.841% | **-0.14R** (-0.257 … -0.019) | 0.75 | -1736.75R | 7.0 |
| sideways | 1670 | 49.4% | 3.665% | -6.56% | -1.509% | **-0.242R** (-0.503 … 0.007) | 0.55 | -403.64R | 6.0 |
| bear | 1320 | 50.2% | 3.553% | -5.855% | -1.137% | **-0.202R** (-0.448 … 0.041) | 0.61 | -344.99R | 5.7 |

### Market regime — master list (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| bull | 1942 | 42.6% | 10.768% | -8.322% | -0.192% | **-0.032R** (-0.235 … 0.164) | 0.96 | -273.5R | 9.1 |
| sideways | 135 | 39.3% | 8.815% | -7.649% | -1.186% | **0.022R** (-0.563 … 0.583) | 0.74 | -34.03R | 7.5 |
| bear | 75 | 56.0% | 5.468% | -6.095% | 0.38% | **0.179R** (-0.283 … 0.541) | 1.14 | -8.21R | 7.2 |

### Setup type — all (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| breakout | 5352 | 46.7% | 6.005% | -7.045% | -0.957% | **-0.173R** (-0.313 … -0.032) | 0.75 | -1044.63R | 6.1 |
| pullback | 6931 | 52.9% | 3.794% | -6.311% | -0.969% | **-0.151R** (-0.255 … -0.047) | 0.67 | -1195.1R | 7.2 |

### Setup type — master list (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| breakout | 1460 | 43.3% | 10.828% | -8.489% | -0.127% | **0.019R** (-0.21 … 0.214) | 0.97 | -191.41R | 8.0 |
| pullback | 692 | 41.9% | 9.514% | -7.657% | -0.461% | **-0.104R** (-0.332 … 0.127) | 0.9 | -138.12R | 10.9 |

### Score range — all setups (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| 0-39 | 562 | 46.3% | 2.606% | -5.318% | -1.652% | **-0.386R** (-0.553 … -0.237) | 0.42 | -217.68R | 6.1 |
| 40-49 | 1938 | 52.1% | 3.283% | -5.896% | -1.117% | **-0.184R** (-0.289 … -0.076) | 0.6 | -368.96R | 6.1 |
| 50-59 | 3685 | 52.3% | 3.408% | -6.396% | -1.269% | **-0.21R** (-0.302 … -0.117) | 0.58 | -805.28R | 6.3 |
| 60-69 | 3168 | 50.0% | 4.691% | -6.772% | -1.044% | **-0.157R** (-0.266 … -0.047) | 0.69 | -603.97R | 7.1 |
| 70-100 | 2930 | 47.2% | 7.896% | -7.539% | -0.259% | **-0.043R** (-0.212 … 0.113) | 0.94 | -392.25R | 7.4 |

### Holding period (sessions) — all setups (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| 3-5 | 7583 | 55.7% | 4.367% | -6.403% | -0.4% | **-0.098R** (-0.211 … -0.003) | 0.86 | -883.86R | 3.4 |
| 6-10 | 2386 | 43.1% | 4.941% | -7.333% | -2.045% | **-0.315R** (-0.434 … -0.195) | 0.51 | -758.58R | 7.5 |
| 11-15 | 881 | 43.6% | 6.091% | -8.32% | -2.039% | **-0.248R** (-0.415 … -0.079) | 0.57 | -282.12R | 12.8 |
| 16-20 | 1433 | 36.4% | 5.782% | -5.653% | -1.487% | **-0.181R** (-0.299 … -0.059) | 0.59 | -312.11R | 19.2 |

### Sector — all setups (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| Hydro Power (जलविद्युत) | 3390 | 53.3% | 5.674% | -7.917% | -0.673% | **-0.074R** (-0.199 … 0.034) | 0.82 | -436.0R | 6.8 |
| Microfinance (लघुवित्त) | 2289 | 48.2% | 4.898% | -6.799% | -1.158% | **-0.185R** (-0.328 … -0.032) | 0.67 | -484.39R | 6.5 |
| Mutual Fund (म्युचुअल फण्ड) | 1636 | 52.1% | 2.333% | -4.366% | -0.873% | **-0.22R** (-0.362 … -0.077) | 0.58 | -407.52R | 7.0 |
| Commercial Banks (वाणिज्य बैंक) | 1010 | 47.4% | 3.45% | -5.669% | -1.344% | **-0.248R** (-0.401 … -0.109) | 0.55 | -283.56R | 6.7 |
| Development Banks (विकास बैंक) | 974 | 51.7% | 5.348% | -6.935% | -0.579% | **-0.12R** (-0.251 … -0.002) | 0.83 | -137.33R | 6.6 |
| Finance (फाइनान्स) | 814 | 51.8% | 6.3% | -7.717% | -0.45% | **-0.041R** (-0.211 … 0.136) | 0.88 | -110.39R | 6.5 |
| Non Life Insurance (निर्जीवन बीमा) | 445 | 46.1% | 4.243% | -6.116% | -1.344% | **-0.209R** (-0.403 … -0.018) | 0.59 | -99.16R | 6.8 |
| Life Insurance (जीवन बीमा) | 408 | 44.4% | 3.638% | -6.253% | -1.865% | **-0.308R** (-0.496 … -0.128) | 0.46 | -135.84R | 6.9 |
| Manufacturing And Processing (उत्पादन तथा प्रशोधन) | 289 | 43.6% | 3.508% | -5.846% | -1.768% | **-0.411R** (-0.58 … -0.244) | 0.46 | -125.84R | 6.6 |
| Investment (लगानी) | 267 | 50.2% | 4.835% | -6.74% | -0.931% | **-0.116R** (-0.274 … 0.058) | 0.72 | -40.98R | 6.5 |
| Unclassified (वर्गीकरण नभएको) | 267 | 44.9% | 5.336% | -6.712% | -1.297% | **-0.354R** (-0.573 … -0.156) | 0.65 | -96.56R | 6.5 |
| Hotels And Tourism (होटल तथा पर्यटन) | 246 | 48.0% | 3.703% | -6.201% | -1.45% | **-0.159R** (-0.356 … 0.08) | 0.55 | -40.61R | 7.9 |
| Others (अन्य) | 167 | 46.1% | 5.315% | -6.592% | -1.102% | **-0.136R** (-0.389 … 0.161) | 0.69 | -36.21R | 7.4 |
| Tradings (व्यापार) | 81 | 38.3% | 4.331% | -6.369% | -2.274% | **-0.159R** (-0.525 … 0.328) | 0.42 | -29.1R | 7.6 |

### Sector — master list (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| Hydro Power (जलविद्युत) | 684 | 42.4% | 11.354% | -9.007% | -0.374% | **-0.038R** (-0.257 … 0.195) | 0.93 | -114.08R | 9.2 |
| Microfinance (लघुवित्त) | 420 | 42.6% | 9.898% | -7.685% | -0.191% | **-0.011R** (-0.312 … 0.267) | 0.96 | -65.0R | 9.1 |
| Development Banks (विकास बैंक) | 227 | 48.9% | 10.94% | -8.995% | 0.753% | **0.07R** (-0.235 … 0.349) | 1.16 | -30.67R | 8.4 |
| Commercial Banks (वाणिज्य बैंक) | 201 | 40.3% | 6.612% | -6.871% | -1.438% | **-0.316R** (-0.597 … -0.068) | 0.65 | -72.96R | 8.5 |
| Finance (फाइनान्स) | 173 | 48.0% | 14.556% | -9.848% | 1.86% | **0.373R** (-0.044 … 0.869) | 1.36 | -28.83R | 9.2 |
| Non Life Insurance (निर्जीवन बीमा) | 116 | 41.4% | 7.46% | -7.651% | -1.398% | **-0.115R** (-0.506 … 0.289) | 0.69 | -27.95R | 8.0 |
| Life Insurance (जीवन बीमा) | 66 | 40.9% | 7.851% | -6.934% | -0.886% | **0.027R** (-0.385 … 0.397) | 0.78 | -12.51R | 8.4 |
| Investment (लगानी) | 60 | 48.3% | 9.901% | -7.416% | 0.954% | **0.155R** (-0.271 … 0.563) | 1.25 | -8.31R | 8.3 |
| Unclassified (वर्गीकरण नभएको) | 45 | 46.7% | 11.736% | -7.646% | 1.399% | **0.092R** (-0.352 … 0.499) | 1.34 | -9.22R | 9.5 |
| Manufacturing And Processing (उत्पादन तथा प्रशोधन) | 44 | 25.0% | 8.383% | -6.936% | -3.106% | **-0.642R** (-0.961 … -0.278) | 0.4 | -30.19R | 7.8 |
| Hotels And Tourism (होटल तथा पर्यटन) | 39 | 35.9% | 7.957% | -6.409% | -1.252% | **-0.121R** (-0.652 … 0.408) | 0.7 | -12.69R | 10.8 |
| Others (अन्य) | 36 | 41.7% | 11.829% | -8.044% | 0.236% | **0.274R** (-0.442 … 1.244) | 1.05 | -9.66R | 8.9 |
| Mutual Fund (म्युचुअल फण्ड) | 25 | 32.0% | 6.157% | -5.39% | -1.695% | **-0.114R** (n<30) | 0.54 | -9.77R | 9.4 |
| Tradings (व्यापार) | 16 | 31.2% | 9.164% | -8.922% | -3.27% | **-0.45R** (n<30) | 0.47 | -7.19R | 10.7 |

### Out-of-sample: 2019-2024 vs untouched holdout 2025-2026 — all (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| 2019-2024 | 8595 | 50.8% | 5.371% | -7.037% | -0.734% | **-0.115R** (-0.245 … 0.012) | 0.79 | -1219.5R | 6.8 |
| holdout 2025-2026 | 3688 | 48.7% | 3.034% | -5.796% | -1.499% | **-0.267R** (-0.432 … -0.12) | 0.5 | -1068.59R | 6.5 |

### Out-of-sample: 2019-2024 vs untouched holdout 2025-2026 — master (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| 2019-2024 | 1786 | 45.1% | 10.668% | -8.407% | 0.19% | **0.029R** (-0.174 … 0.211) | 1.04 | -182.76R | 9.0 |
| holdout 2025-2026 | 366 | 32.0% | 8.673% | -7.468% | -2.308% | **-0.262R** (-0.542 … 0.066) | 0.55 | -133.67R | 8.6 |

### By signal year — all setups (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| 2019 | 781 | 40.8% | 2.768% | -4.99% | -1.821% | **-0.473R** (-0.656 … -0.338) | 0.38 | -382.53R | 6.9 |
| 2020 | 1135 | 59.6% | 6.217% | -7.678% | 0.61% | **0.194R** (-0.164 … 0.541) | 1.2 | -249.63R | 6.6 |
| 2021 | 1326 | 55.6% | 8.02% | -8.18% | 0.824% | **0.107R** (-0.195 … 0.357) | 1.23 | -225.39R | 7.4 |
| 2022 | 998 | 40.7% | 3.848% | -7.197% | -2.704% | **-0.405R** (-0.744 … -0.099) | 0.37 | -547.31R | 6.1 |
| 2023 | 1670 | 47.9% | 4.108% | -6.86% | -1.606% | **-0.233R** (-0.494 … -0.046) | 0.55 | -557.39R | 6.3 |
| 2024 | 2685 | 53.1% | 5.325% | -7.067% | -0.481% | **-0.069R** (-0.283 … 0.178) | 0.85 | -417.77R | 7.3 |
| 2025 | 1997 | 50.6% | 3.144% | -6.092% | -1.416% | **-0.23R** (-0.436 … -0.044) | 0.53 | -513.99R | 6.8 |
| 2026 | 1691 | 46.4% | 2.891% | -5.475% | -1.596% | **-0.312R** (-0.524 … -0.067) | 0.46 | -643.96R | 6.3 |

### By signal year — master list (net)

| Slice | Trades | Win rate | Avg win | Avg loss | Avg return | Expectancy (95% CI, monthly block bootstrap) | Profit factor | Max DD (cum. R) | Avg hold (sessions) |
|---|---|---|---|---|---|---|---|---|---|
| 2019 | 48 | 33.3% | 3.775% | -5.29% | -2.269% | **-0.591R** (-1.057 … -0.087) | 0.36 | -36.43R | 11.4 |
| 2020 | 265 | 47.5% | 10.064% | -8.726% | 0.208% | **0.118R** (-0.279 … 0.56) | 1.05 | -87.02R | 8.9 |
| 2021 | 546 | 49.6% | 12.718% | -9.055% | 1.752% | **0.154R** (-0.272 … 0.535) | 1.38 | -94.49R | 8.9 |
| 2022 | 63 | 34.9% | 6.783% | -6.591% | -1.921% | **-0.225R** (-0.793 … 0.33) | 0.55 | -29.22R | 8.2 |
| 2023 | 149 | 38.3% | 8.498% | -6.917% | -1.02% | **-0.183R** (-0.652 … 0.135) | 0.76 | -40.83R | 8.7 |
| 2024 | 715 | 43.8% | 10.156% | -8.628% | -0.405% | **0.008R** (-0.308 … 0.33) | 0.92 | -182.76R | 9.1 |
| 2025 | 243 | 33.3% | 9.337% | -7.685% | -2.011% | **-0.276R** (-0.594 … 0.046) | 0.61 | -92.81R | 9.0 |
| 2026 | 123 | 29.3% | 7.178% | -7.064% | -2.896% | **-0.234R** (-0.675 … 0.717) | 0.42 | -56.22R | 7.7 |

### Capital-constrained portfolio: portfolio master 10 slots

- Trades taken 997 · skipped for lack of capital/slots 1155
- Total return -33.5% · CAGR -5.2% · **max drawdown -64.6%** (daily mark-to-market) · avg positions open 6.1
- Yearly return %: {'2019': -9.0, '2020': -7.1, '2021': 38.1, '2022': -12.7, '2023': -9.9, '2024': 12.0, '2025': -25.1, '2026': -13.8}

### Capital-constrained portfolio: portfolio all 10 slots

- Trades taken 2116 · skipped for lack of capital/slots 10167
- Total return -92.9% · CAGR -28.72% · **max drawdown -94.9%** (daily mark-to-market) · avg positions open 8.48
- Yearly return %: {'2019': -45.1, '2020': 30.5, '2021': -0.0, '2022': -53.3, '2023': -38.9, '2024': -11.7, '2025': -40.5, '2026': -34.1}

### Walk-forward calibration of T1 hit rate (expanding window)

| Test year | Train trades | Test trades | Bucket: train% → test% (n) |
|---|---|---|---|
| 2022 | 3242 | 998 | 0-39: 53.1→48.5 (66), 40-49: 62.8→42.4 (262), 50-59: 60.2→44.2 (369), 60-69: 53.5→45.8 (203), 70-100: 46.3→42.9 (98) |
| 2023 | 4240 | 1670 | 0-39: 51.9→57.8 (109), 40-49: 55.6→55.2 (346), 50-59: 55.0→50.0 (558), 60-69: 52.0→46.4 (403), 70-100: 46.0→46.1 (254) |
| 2024 | 5910 | 2685 | 0-39: 53.7→47.9 (73), 40-49: 55.5→64.8 (293), 50-59: 53.4→63.3 (687), 60-69: 50.4→53.7 (771), 70-100: 46.0→43.6 (861) |
| 2025 | 8595 | 1997 | 0-39: 52.7→53.8 (78), 40-49: 57.5→60.1 (306), 50-59: 56.2→60.1 (725), 60-69: 51.6→51.3 (501), 70-100: 45.0→41.1 (387) |
| 2026 | 10592 | 1691 | 0-39: 52.9→55.9 (59), 40-49: 57.9→66.3 (252), 50-59: 57.1→57.7 (570), 60-69: 51.5→47.6 (487), 70-100: 44.5→37.8 (323) |

Weighted OOS error 5.09 pp over 9041 trades → calibrated = True


## 3. What the numbers say

* **Costs decide everything.** Gross of costs the master list earns +0.24R; slippage alone halves it; fees and
  tax take it to −0.02R. Any improvement must beat ~1.25 % per round trip.
* **Regime matters only weakly** and confidence intervals overlap; master-list trades are mostly taken in bull
  regimes (1,942 of 2,152) because the rules require an uptrend.
* **Score ranks expectancy** (−0.39R at 0–39 → −0.04R at 70+), so the score is informative but not sufficient.
* **Short holds lose least**; trades that run to the time stop are weak.
* **Holdout 2025–2026 is the worst period**; the 2020–2021 bull market is the only clearly positive stretch.
* Sector slices with positive point estimates (e.g. Finance +0.37R, n=173) have intervals that include zero —
  not evidence of an edge, and selecting them now would be fitting to this sample.

## 4. Remaining limitations

Circuit-lock and order-book depth are under-modelled; cost rates are configurable defaults, not verified live
values; bonus/right detection is inferred, not taken from official corporate-action data; the regime index is a
proxy; survivorship bias is reduced but not removed.
