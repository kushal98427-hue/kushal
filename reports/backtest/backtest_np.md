# ब्याकटेस्ट रिपोर्ट (Walk-forward)

- परीक्षण गरिएका स्टक: 346 · अवधि: 2019-01-01 → 2026-11-19
- ✅ **Calibrated** — out-of-sample त्रुटि सीमाभित्र। रिपोर्टमा 'ऐतिहासिक T1 हिट दर' देखाइनेछ (सम्भाव्यता होइन)।
- कारण: passed

## नियम

```
identical to the live scanner, because both call ``analyze_at``):

* **Signal**: bar ``t`` where ``analyze_at`` returns a ``breakout`` or ``pullback``
  plan, using only data ``<= t`` (indicators are causal; pivots are used only
  after confirmation).
* **Entry**: next session's open, plus slippage. Skipped if the open gaps more
  than ``max_entry_gap_pct`` above the entry zone or opens at/below the stop.
* **Settlement lock**: NEPSE settles T+2, so no exit is possible for the first
  ``min_hold_sessions`` sessions. If the stop was breached while locked, the
  trade exits at the first allowed open if it is still below the stop.
* **Exit**: stop-loss or Target 1, whichever is touched first. If both are
  inside one bar's range, the *stop* is assumed first (conservative). Gaps
  through a level fill at the open. Time exit at the close after
  ``max_hold_sessions``.
* **Costs**: commission + SEBON fee per side, DP charge on sell, slippage on
  both fills, capital-gains tax on profitable trades.
* **One position per stock at a time** (no overlapping trades on one symbol).
```

## नतिजा

| समूह | ट्रेड | जित दर | T1 हिट दर (95% CI) | औसत नेट प्रतिफल | Expectancy (R) | Profit factor | Max drawdown (cumulative R) |
|---|---|---|---|---|---|---|---|
| सबै सेटअप | 12373 | 50.0% | 52.4% (51.5–53.2) | -0.978% | -0.164 | 0.71 | -2245.86R |
| मास्टर मापदण्ड (स्कोर≥60, R:R≥1.5, तरल) | 2159 | 42.8% | 34.8% (32.8–36.9) | -0.251% | -0.025 | 0.95 | -282.21R |
| breakout | 5400 | 46.5% | 47.7% (46.4–49.0) | -0.979% | -0.179 | 0.74 | -1066.25R |
| pullback | 6973 | 52.8% | 56.0% (54.8–57.1) | -0.978% | -0.153 | 0.67 | -1195.09R |

## स्कोर समूह अनुसार (पूरा नमूना)

| स्कोर | ट्रेड | T1 हिट दर | 95% CI | Expectancy (R) | पर्याप्त नमूना |
|---|---|---|---|---|---|
| 0-39 | 567 | 53.3% | 49.1–57.3 | -0.382 | हो |
| 40-49 | 1953 | 59.0% | 56.8–61.1 | -0.186 | हो |
| 50-59 | 3715 | 57.0% | 55.4–58.6 | -0.215 | हो |
| 60-69 | 3194 | 50.8% | 49.1–52.6 | -0.16 | हो |
| 70-100 | 2944 | 43.6% | 41.8–45.4 | -0.048 | हो |

## Walk-forward (हरेक वर्ष out-of-sample)

| परीक्षण वर्ष | train ट्रेड | test ट्रेड | स्कोर समूह: train% → test% |
|---|---|---|---|
| 2022 | 3242 | 998 | 0-39: 53.1→48.5 (n=66), 40-49: 62.8→42.4 (n=262), 50-59: 60.2→44.2 (n=369), 60-69: 53.5→45.8 (n=203), 70-100: 46.3→42.9 (n=98) |
| 2023 | 4240 | 1670 | 0-39: 51.9→57.8 (n=109), 40-49: 55.6→55.2 (n=346), 50-59: 55.0→50.0 (n=558), 60-69: 52.0→46.4 (n=403), 70-100: 46.0→46.1 (n=254) |
| 2024 | 5910 | 2685 | 0-39: 53.7→47.9 (n=73), 40-49: 55.5→64.8 (n=293), 50-59: 53.4→63.3 (n=687), 60-69: 50.4→53.7 (n=771), 70-100: 46.0→43.6 (n=861) |
| 2025 | 8595 | 1997 | 0-39: 52.7→53.8 (n=78), 40-49: 57.5→60.1 (n=306), 50-59: 56.2→60.1 (n=725), 60-69: 51.6→51.3 (n=501), 70-100: 45.0→41.1 (n=387) |
| 2026 | 10592 | 1781 | 0-39: 52.9→56.2 (n=64), 40-49: 57.9→65.5 (n=267), 50-59: 57.1→56.3 (n=600), 60-69: 51.5→47.4 (n=513), 70-100: 44.5→36.8 (n=337) |

## सीमाहरू

- स्रोत रिपोमा सबै डिलिस्टेड कम्पनी छैनन् → केही survivorship bias बाँकी रहन सक्छ।
- बोनस/हकप्रद समायोजन `per_change` बाट अनुमान गरिएको; केही घटना छुट्न सक्छन्।
- शुल्क दर (कमिसन, SEBON, CGT) `nepse_ta/config.py` मा छन् — हालको दर आफ्नो ब्रोकरसँग पुष्टि गर्नुहोस्।
- विगतको नतिजाले भविष्यको ग्यारेन्टी गर्दैन।
