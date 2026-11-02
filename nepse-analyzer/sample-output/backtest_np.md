# ब्याकटेस्ट रिपोर्ट (Walk-forward)

- परीक्षण गरिएका स्टक: 346 · अवधि: 2019-01-01 → 2026-10-29
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

| समूह | ट्रेड | जित दर | T1 हिट दर (95% CI) | औसत नेट प्रतिफल | Expectancy (R) | Profit factor | Max drawdown (10% प्रति ट्रेड) |
|---|---|---|---|---|---|---|---|
| सबै सेटअप | 12307 | 50.2% | 52.5% (51.6–53.4) | -0.966% | -0.16 | 0.71 | -100.0% |
| मास्टर मापदण्ड (स्कोर≥60, R:R≥1.5, तरल) | 2153 | 43.0% | 35.1% (33.1–37.1) | -0.215% | -0.014 | 0.95 | -90.8% |
| breakout | 5373 | 46.7% | 47.9% (46.6–49.2) | -0.952% | -0.17 | 0.75 | -99.8% |
| pullback | 6934 | 52.9% | 56.1% (54.9–57.2) | -0.976% | -0.152 | 0.67 | -100.0% |

## स्कोर समूह अनुसार (पूरा नमूना)

| स्कोर | ट्रेड | T1 हिट दर | 95% CI | Expectancy (R) | पर्याप्त नमूना |
|---|---|---|---|---|---|
| 0-39 | 568 | 53.5% | 49.4–57.6 | -0.376 | हो |
| 40-49 | 1938 | 59.0% | 56.8–61.1 | -0.186 | हो |
| 50-59 | 3697 | 57.2% | 55.6–58.8 | -0.212 | हो |
| 60-69 | 3173 | 50.9% | 49.1–52.6 | -0.16 | हो |
| 70-100 | 2931 | 43.9% | 42.1–45.7 | -0.035 | हो |

## Walk-forward (हरेक वर्ष out-of-sample)

| परीक्षण वर्ष | train ट्रेड | test ट्रेड | स्कोर समूह: train% → test% |
|---|---|---|---|
| 2022 | 3249 | 999 | 0-39: 53.6→48.5 (n=66), 40-49: 63.0→42.2 (n=263), 50-59: 60.0→44.2 (n=369), 60-69: 53.4→45.8 (n=203), 70-100: 46.6→42.9 (n=98) |
| 2023 | 4248 | 1672 | 0-39: 52.2→58.2 (n=110), 40-49: 55.6→55.2 (n=346), 50-59: 54.9→49.9 (n=559), 60-69: 51.9→46.4 (n=403), 70-100: 46.2→46.1 (n=254) |
| 2024 | 5920 | 2691 | 0-39: 54.1→47.9 (n=73), 40-49: 55.5→65.0 (n=294), 50-59: 53.3→63.2 (n=690), 60-69: 50.3→53.8 (n=773), 70-100: 46.2→43.6 (n=861) |
| 2025 | 8611 | 2000 | 0-39: 53.0→53.8 (n=78), 40-49: 57.5→59.8 (n=306), 50-59: 56.1→60.2 (n=727), 60-69: 51.6→51.2 (n=502), 70-100: 45.2→41.3 (n=387) |
| 2026 | 10611 | 1696 | 0-39: 53.1→56.7 (n=60), 40-49: 57.9→66.1 (n=251), 50-59: 57.1→57.7 (n=572), 60-69: 51.5→47.4 (n=489), 70-100: 44.6→38.0 (n=324) |

## सीमाहरू

- स्रोत रिपोमा सबै डिलिस्टेड कम्पनी छैनन् → केही survivorship bias बाँकी रहन सक्छ।
- बोनस/हकप्रद समायोजन `per_change` बाट अनुमान गरिएको; केही घटना छुट्न सक्छन्।
- शुल्क दर (कमिसन, SEBON, CGT) `nepse_ta/config.py` मा छन् — हालको दर आफ्नो ब्रोकरसँग पुष्टि गर्नुहोस्।
- विगतको नतिजाले भविष्यको ग्यारेन्टी गर्दैन।
