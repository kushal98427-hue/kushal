# Phase 2 specification — Market Structure र SMC (v2, review को लागि)

स्थिति: **प्रस्ताव मात्र — implementation सुरु भएको छैन।** Branch: `nepse-v2`. Version label: `smc-1`.
सबै parameter तलको तालिकामा छन्; approval पछि मात्र code लेखिनेछ।

---

## 0. आधारभूत सिद्धान्त

1. **Data:** validated, bonus/right-adjusted **daily OHLCV** (`prepare_series().live`) र त्यसैबाट बनेको
   **weekly** bar मात्र। Intraday, order book, buy/sell volume split उपलब्ध छैन।
2. हरेक element (swing, BOS, OB, FVG …) सँग `formed_at` हुन्छ: **कुन candle को close मा त्यो पहिलो पटक थाहा
   हुन सक्थ्यो।** मिति `t` को analysis ले `formed_at ≤ t` भएका element र `≤ t` का bar मात्र प्रयोग गर्छ।
3. हामी **price pattern** मात्र पत्ता लगाउँछौँ। Report मा "institution ले किन्यो/smart money आयो" जस्तो दाबी
   कहिल्यै हुँदैन; शब्दहरू: "potential liquidity zone", "price behaviour consistent with a liquidity sweep",
   "potential order block (price-based definition)"।
4. Rule पूरा नभए element **बन्दैन** (invent हुँदैन)। Data नपुगे `status: "unavailable"` वा `"insufficient_history"`।
5. Price scale-invariance: सबै threshold ATR वा % मा। Bonus adjustment ले पुरानो सबै bar लाई एउटै factor ले
   गुणन गर्छ, त्यसैले structure को नतिजा बदलिँदैन (test गरिनेछ)।

## 1. Data ले के सक्छ / सक्दैन

| Concept | चाहिने data | NEPSE daily OHLCV ले | टिप्पणी |
|---|---|---|---|
| Swing high/low, HH/HL/LH/LL | High, low | ✅ सक्छ | Daily resolution मा; intraday swing देखिँदैन |
| BOS / CHoCH | Close, high, low | ✅ सक्छ | Close-confirmed vs wick-only छुट्याउन सकिन्छ |
| Displacement | OHLC, ATR | ✅ सक्छ | Body/range ATR मा |
| Volume confirmation | Volume | ⚠️ आंशिक | कुल volume मात्र; buy vs sell छुट्याउन सकिँदैन |
| Equal highs/lows | High, low | ✅ सक्छ | Tolerance-आधारित |
| Liquidity sweep | High/low + close | ⚠️ आंशिक | Wick-beyond + close-back देखिन्छ; वास्तवमा stop हानियो कि भनेर देखिँदैन |
| Order block | OHLC sequence + structure break | ⚠️ आंशिक | Price-based definition मात्र; institutional order देखिँदैन |
| FVG | 3 candle high/low | ✅ सक्छ | NEPSE मा ±10% circuit र लामो बिदाले कृत्रिम gap बनाउन सक्छ → flag |
| Premium/discount | Dealing range (swing pair) | ✅ सक्छ जब range स्पष्ट | Range अस्पष्ट भए लागू हुँदैन |
| Weekly/daily alignment | Weekly bar | ✅ सक्छ | Completed week मात्र |
| Lower timeframe entry | Intraday | ❌ सक्दैन | `unavailable` लेखिन्छ |
| Order flow, delta, real liquidity | Order book/tick | ❌ सक्दैन | कहिल्यै दाबी हुँदैन |
| Broker concentration | Floor sheet (mirror मा छ) | Phase 2 मा छैन | पछि अलग evidence, "smart money" होइन |

हालको data quality (2024–2026, 276 equity): OHLC-repaired bar 0.07 %, missing volume 0, ±9.5 %+ दिन 1.35 %,
median ATR 3.86 %, raw k=3 pivot high ≈ 24/stock/वर्ष, 3-candle bullish gap ≥ 0.25 ATR ≈ 12/stock/वर्ष
(14 % मा ~10 % को दिन संलग्न)।

## 2. Parameter तालिका (प्रस्तावित — approval चाहिन्छ)

| Parameter | Value | कारण |
|---|---|---|
| `swing_k_daily` | 3 | दायाँ-बायाँ 3 bar; swing trading (दिनदेखि हप्ता) को लागि; k=5 ले धेरै ढिलो confirm गर्छ |
| `swing_k_weekly` | 2 | Weekly मा bar कम |
| `min_swing_atr` | 1.0 × ATR(14) | यो भन्दा सानो उतारचढाव "noise" मानेर swing बनाउँदैन |
| `equal_tol` | max(0.10 × ATR, 0.3 % price) | Equal highs/lows र HH vs EH छुट्याउन |
| `structure_tol` | equal_tol | HH/LH निर्धारण गर्दा पनि यही |
| `displacement_body_atr` | ≥ 1.0 × ATR **वा** range ≥ 1.5 × ATR | "Strong" displacement |
| `break_volume_mult` | ≥ 1.5 × 20-दिन औसत | Volume-supported break (volume भरपर्दो भए) |
| `sweep_min_wick_atr` | ≥ 0.10 × ATR level भन्दा पर | झिनो छोइलाई sweep नमान्न |
| `ob_lookback` | break bar बाट पछाडि 10 bar | Order block खोज्ने दायरा |
| `ob_min_move_atr` | ≥ 2.0 × ATR (OB low बाट break close सम्म) | Displacement बिना OB हुँदैन |
| `zone_max_age` | 120 bar | पुराना zone अप्रासंगिक |
| `fvg_min_atr` | ≥ 0.25 × ATR | सानो gap ignore |
| `pd_min_range_atr` | ≥ 2.0 × ATR | Dealing range सानो भए premium/discount लागू हुँदैन |
| `circuit_pct` | ≥ 9.5 % दैनिक परिवर्तन | Circuit-like bar flag |
| `long_gap_days` | > 5 calendar दिन | बिदा/halt पछिको gap flag |

कुनै पनि parameter backtest हेरेर फेरबदल गरिने छैन जबसम्म Phase 7 मा walk-forward + holdout मा परीक्षण हुँदैन।

## 3. Rules (exact)

ATR = ATR(14) at the relevant bar. सबै तुलना adjusted price मा।

### 3.1 Swing points (आधार)
* **Candidate swing high** at bar *i*: `high[i] > max(high[i-k .. i-1])` र `high[i] ≥ max(high[i+1 .. i+k])`।
  (बायाँ strict, दायाँ non-strict ⇒ बराबर दुई high मा पहिलो मात्र swing।) Swing low mirror।
* **थाहा हुने समय:** `formed_at = i + k` (दायाँका k bar close भएपछि)।
* **Alternation + size filter** (bar अनुसार, formed_at क्रममा): accepted swing हरू high/low पालैपालो हुनुपर्छ।
  - नयाँ candidate उही प्रकारको (e.g. high पछि फेरि high) भए: बढी extreme भए पुरानोलाई **replace** (replace
    को घटना नयाँ candidate को formed_at मा दर्ता), नभए ignore।
  - विपरीत प्रकारको भए: अघिल्लो accepted swing बाट दूरी `≥ min_swing_atr × ATR[formed_at]` भए accept, नत्र ignore।
* **Edge cases:** पहिलो k र अन्तिम k bar कहिल्यै swing हुँदैनन् (अन्तिम k bar को swing "pending" हुन्छ — report मा
  "अझै confirm नभएको")। OHLC-repaired bar भएको swing `quality: "repaired_bar"` flag।
* **False-signal जोखिम:** sideways बजारमा धेरै साना swing — size filter ले घटाउँछ तर हटाउँदैन।

### 3.2 HH / HL / LH / LL र structure state
* हरेक accepted swing high लाई अघिल्लो accepted swing high सँग: `> prev + tol` → **HH**, `< prev − tol` → **LH**,
  नत्र **EH** (equal)। Lows: **HL / LL / EL**।
* **State (as of t):** अन्तिम swing high र अन्तिम swing low को label हेरेर —
  `HH + HL` → **bullish**; `LH + LL` → **bearish**; अरू (HH+LL, LH+HL, EH/EL) → **transition/range**।
  दुवै प्रकारको कम्तीमा 2 accepted swing नभए → **insufficient**।
* Report मा: अन्तिम 4 swing (मिति, मूल्य, label)।

### 3.3 BOS (Break of Structure — trend continuation)
* **Bullish BOS:** state bullish हुँदा, bar *j* को **close > अन्तिम accepted swing high** (जसको formed_at < j)।
  सोही level को पहिलो close-break मात्र गनिन्छ। `formed_at = j`।
* **Wick-only:** high > level तर close ≤ level → BOS होइन; §3.6 मा sweep candidate।
* **Displacement:** break bar को body ≥ 1.0 ATR वा range ≥ 1.5 ATR → `strong`, नत्र `weak`।
  Volume: rel. volume ≥ 1.5 → `volume_supported`; volume अविश्वसनीय भए `volume_unknown`।
* **HTF alignment:** weekly state सँग मिल्छ/मिल्दैन (§3.9)।
* **Invalidation:** break पछि **close broken level − 0.5 ATR तल** → `failed_bos`।
* Bearish BOS mirror (bearish state, close < अन्तिम swing low)।

### 3.4 CHoCH / MSS (structure परिवर्तन)
* **Bullish CHoCH:** state **bearish** हुँदा, close > अन्तिम accepted swing high (अन्तिम LH)। Bearish CHoCH mirror
  (bullish state मा close < अन्तिम HL)।
* **MSS label:** CHoCH + strong displacement मात्र "MSS-like"। Displacement नभए "CHoCH (weak)"।
* **Status:**
  - `tentative` — wick ले मात्र level पार (close भित्र)। यो CHoCH होइन, "सम्भावित" मात्र।
  - `confirmed_close` — close ले level पार।
  - `structure_confirmed` — त्यसपछि नयाँ **HL** (CHoCH पछिको पहिलो accepted swing low, CHoCH को origin low भन्दा
    माथि) confirm भयो। यो formed_at पछि मात्र।
* **Invalidation:** CHoCH origin low (CHoCH अघिको अन्तिम LL) तल close → `failed_choch`।
* **Minor movement रोक्ने:** state पहिले स्पष्ट bearish (LH+LL, size-filtered) हुनुपर्छ; transition/range मा
  भएको break लाई CHoCH होइन "range break" भनिन्छ।

### 3.5 Equal highs / equal lows (potential liquidity)
* Lookback 60 bar भित्र दुई वा बढी accepted swing high जसको फरक ≤ `equal_tol` → **EQH zone** = [min, max]।
  `formed_at` = दोस्रो swing को formed_at। Equal lows mirror।
* **Status:** `intact` (त्यसपछि कुनै high zone max भन्दा माथि गएको छैन) / `swept` (§3.6) / `broken` (close माथि)।
* Wording: "potential buy-side liquidity above equal highs" — निश्चित stop order छन् भन्ने दाबी होइन।

### 3.6 Liquidity sweep
* **Levels:** intact swing high/low (zone_max_age भित्र), EQH/EQL zone, अघिल्लो completed week को high/low।
* **Bearish-implication sweep (buy-side):** bar *j*: `high[j] ≥ level + 0.10 ATR` **र** `close[j] < level`।
  Bullish-implication (sell-side) mirror: `low[j] ≤ level − 0.10 ATR` र `close[j] > level`।
* **Reaction confirmation** (later, आफ्नै formed_at): अर्को 3 bar भित्र price sweep bar को विपरीत छेउ पार गर्छ
  (bullish sweep: close > sweep bar high) → `reaction_confirmed`; 3 bar भित्र level पार close (accept) →
  `accepted` (sweep असफल, BOS तर्फ)। नत्र `unconfirmed`।
* **Edge cases:** circuit-like bar (±9.5 %) मा sweep `flag: circuit_bar` (मूल्य सीमाले कृत्रिम rejection)।
  एउटै bar ले दुवै छेउ sweep गरे दुवै दर्ता, `flag: two_sided`।

### 3.7 Order block (price-based definition)
* **Bullish OB** बन्छ जब bullish BOS वा CHoCH bar *j* मा हुन्छ र:
  1. leg origin *L* = `j−ob_lookback .. j` भित्र सबैभन्दा कम low भएको bar;
  2. OB candle = *L* वा त्यसभन्दा पहिलेका 3 bar भित्र **अन्तिम bearish candle** (close < open);
     त्यस्तो candle नभए **OB बन्दैन**;
  3. displacement: `close[j] − low[OB] ≥ 2.0 ATR`।
* **Zone:** [low, high] of OB candle (body range पनि साथै रेकर्ड)। `formed_at = j` (break नभई OB थाहा हुँदैन)।
* **Status (as of t):** `fresh` (j पछि कुनै low ≤ zone high छैन) → `tested` (zone भित्र छोयो, close zone low माथि)
  → `invalidated` (close < zone low)। `tested` पछि दोस्रो test लाई कमजोर मानिन्छ। Age > 120 bar → `expired`।
* Bearish OB mirror। Wording: "potential order block"।
* **False-signal जोखिम:** NEPSE मा ठूलो candle धेरै (circuit) — displacement नियमले मात्र छान्छ; FVG/sweep सँग
  confluence भए मात्र report मा "relevant" भनिन्छ।

### 3.8 Fair value gap (3-candle imbalance)
* **Bullish FVG** at bar *i*: `low[i] > high[i−2]` र gap ≥ 0.25 ATR। Zone = [high[i−2], low[i]]। `formed_at = i`।
  Bearish mirror: `high[i] < low[i−2]`।
* **Fill state (as of t):** `unfilled` / `partially_filled` (fill % = कति भित्र छिर्यो) / `filled` (bullish: low ≤
  zone bottom) / `invalidated` (bullish: close < zone bottom)।
* **Flags:** `circuit_move` (i−1 वा i मा ±9.5 %+), `long_gap` (i−2 र i बीच > 5 calendar दिन — बिदा/halt)।
  Flag भएको FVG entry/target मा प्रयोग गर्दा report ले चेतावनी दिन्छ।
* **Relevance:** structure (BOS/CHoCH leg भित्र), OB/EQ zone सँग overlap → `confluence`।

### 3.9 Premium / discount
* **Dealing range:** अन्तिम BOS/CHoCH को leg — bullish मा: leg origin swing low → त्यसपछिको उच्चतम high
  (confirmed swing high नभए "range_open")। Range ≥ 2.0 ATR र दुवै छेउ confirmed हुनुपर्छ; नत्र
  `status: "range_unclear"` र premium/discount **लागू हुँदैन**।
* Equilibrium = midpoint। Price < 50 % → **discount**, > 50 % → **premium**। (OTE/Fibonacci प्रयोग हुँदैन।)

### 3.10 Multi-timeframe
* Weekly bar = W-SAT, **completed week मात्र** (t हप्ताको अन्तिम trading day नभए चालु हप्ता बाहिर)।
* Weekly मा §3.1–3.4 (k=2)। Daily = primary।
* **Alignment:** weekly bullish + daily bullish → `aligned_bullish`; daily bullish तर weekly bearish →
  `countertrend` — यस्तो setup लाई Phase 6 मा थप प्रमाण (sweep + fresh OB/FVG + discount) चाहिनेछ।
* Lower timeframe: `unavailable (no intraday data)`।

### 3.11 Volume behaviour (SMC सँगै)
* Break bar rel. volume (≥ 1.5 supported, ≥ 3 abnormal)।
* 20-bar up-day volume ÷ down-day volume: > 1.5 → "accumulation-like (up-day volume dominance)",
  < 0.67 → "distribution-like"; बीचमा neutral। (Buy/sell volume छुट्याउन नसकिने भएकाले यति मात्र।)

## 4. Look-ahead रोक्ने उपाय

1. हरेक element मा `formed_at`; analysis at t ले `formed_at ≤ t` मात्र लिन्छ; status (fresh/tested/filled)
   पनि bars ≤ t बाट मात्र।
2. Swing replacement र alternation formed_at क्रममा मात्र — भविष्यको pivot ले पुरानो state बदल्दैन।
3. Weekly: completed week मात्र।
4. Bonus adjustment: as-of window का सबै bar एउटै factor ले scale हुने भएकाले structure invariant (test)।
5. **Tests:** (a) full data बाट निकालेको `smc_at(t)` र `t` सम्म काटेको data बाट निकालेको नतिजा **हुबहु** उस्तै;
   (b) t पछिका सबै price ×3 गर्दा `smc_at(t)` नबदलिने; (c) सबै price ×0.9 गर्दा label उस्तै।

## 5. Output (हरेक stock को record मा `smc` section)

```json
{"status":"ok","version":"smc-1",
 "daily":{"state":"bullish","swings":[{"date":"…","type":"high","price":…,"label":"HH","formed_at":"…"}],
          "last_event":{"type":"BOS","direction":"bullish","level":…,"date":"…","close_confirmed":true,
                        "displacement":"strong","volume":"volume_supported","status":"intact"}},
 "weekly":{"state":"…"}, "alignment":"aligned_bullish",
 "liquidity":[{"type":"EQH","zone":[…],"status":"intact"}], "sweeps":[…],
 "order_blocks":[{"direction":"bullish","zone":[…],"status":"fresh","formed_at":"…"}],
 "fvgs":[{"direction":"bullish","zone":[…],"fill":"partially_filled","fill_pct":40,"flags":["circuit_move"]}],
 "premium_discount":{"status":"ok","range":[…],"equilibrium":…,"position":"discount"},
 "explanation":[{"observation":"…","evidence":"…","interpretation":"…","confirm":"…","invalidate":"…","implication":"…"}],
 "unavailable":["lower_timeframe","order_flow"]}
```
Explanation वाक्य computed field बाट मात्र बन्छन् (Nepali, सरल)।

## 6. Target नियम (Phase 6 लाई तयारी)
* SMC ले **candidate target level** मात्र दिन्छ: intact opposing liquidity (swing high/EQH), फरक दिशाको fresh
  OB/FVG, अघिल्लो weekly high। प्रत्येकमा `source` लेखिन्छ।
* Real level नभए target `projection: true` (v1 जस्तै flag) — v2.0 को trade planner (Phase 6) ले यस्तो setup लाई
  default रूपमा **no-trade** राख्ने प्रस्ताव।

## 7. Version र paper-tracking अलगाव
* Phase 2 ले trade plan बदल्दैन: v1.0 recommendation rule जस्ताको तस्तै, `strategy_version: v1.0`।
  Record मा `analysis_version: "smc-1"` थपिन्छ। (पहिलो पटक smc थपिँदा उही मितिको record मा एक पटक revision
  बन्छ — कारण "analysis version changed" लेखिन्छ।)
* v2.0 recommendation Phase 6 पछि मात्र; ledger र summary `strategy_version` अनुसार छुट्टै (mix हुँदैन) —
  `summarize_ledger(strategy_version=…)` र test।

## 8. Test plan

**Unit tests (हात-ले बनाएका bar sequence, अपेक्षित नतिजा पहिल्यै लेखिएको):**
* Swing: strict/non-strict tie, अन्तिम k bar pending, size filter ले सानो swing हटाउने, replacement, alternation।
* HH/HL/LH/LL: tolerance सीमामा (EH/EL), insufficient history।
* BOS: close-break vs wick-only, पहिलो break मात्र, displacement strong/weak, volume missing → `volume_unknown`,
  failed BOS।
* CHoCH: bearish→bullish, tentative vs confirmed vs structure_confirmed, range मा "range break" (CHoCH होइन),
  failed CHoCH।
* EQH/EQL: tolerance भित्र/बाहिर, swept/broken।
* Sweep: wick ≥ 0.1 ATR सीमा, close-back, reaction_confirmed/accepted/unconfirmed, circuit flag, two-sided bar।
* OB: displacement नभए OB नबन्ने, bearish candle नभए नबन्ने, fresh→tested→invalidated, expired।
* FVG: न्यूनतम size, fill states, circuit/long-gap flag।
* Premium/discount: range unclear → not applied, midpoint।
* Weekly: चालु (incomplete) हप्ता बाहिर।
* **Causality:** truncation equality, future ×3, scale ×0.9 — swing, BOS, CHoCH, OB, FVG सबैमा।
* Explanation: हरेक वाक्य मा प्रयोग भएका अंक record का field सँग मिल्नुपर्छ (invented number नहोस्)।

**Historical replay:**
1. Causality replay: 30 stock × 2025–26 का हरेक दिनमा `smc_at(t)` = truncated-data नतिजा (pass/fail गणना)।
2. Descriptive statistics (optimization होइन): प्रति stock-वर्ष swing, BOS, CHoCH, OB, FVG संख्या; status बाँडफाँड —
   "हरेक bar मा signal" जस्तो असामान्य नतिजा भए rule review।
3. Memory replay (15 session, scratch dir, `mode: replay`): smc थपेपछि revision/plan-change noise, record size।
4. Manual spot-check: 3 stock (एउटा trend, एउटा range, एउटा circuit-heavy) को text/table output review को लागि।
5. (Performance test Phase 7 मा मात्र — Phase 2 मा कुनै edge दाबी हुँदैन।)

## 9. ज्ञात सीमाहरू
* Daily resolution: एकै दिनभित्रको sweep/BOS क्रम थाहा हुँदैन।
* Volume buy/sell split छैन; accumulation/distribution "like" मात्र।
* Circuit-limit बजारमा OB/FVG/sweep धेरै कृत्रिम हुन सक्छन् — flag गरिन्छ, हटाइँदैन।
* SMC को कुनै concept को लाभदायकता अहिलेसम्म प्रमाणित छैन; Phase 7 मा परीक्षण हुनेछ।
