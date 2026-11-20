# Edit plan — "AI सिक्नुहोस्" reel (checkpoint)

Raw: `raw.mp4`, 512×768, 25 fps, 27.44 s. Output: 1080×1920, 25 fps, **26.00 s**
(25.20 s of cut + 0.80 s held last frame). Every number below is computed in
`scripts/timeline.py`, which the render, captions, sound and QC all read from.

## 1. Cuts (all edges verified in silence: −51 to −65 dBFS, `scripts/verify_timing.py`)

| # | source | output | note |
|---|---|---|---|
| 1 | 0.00–1.80 | 0.00–1.80 | hook |
| 2 | 2.04–5.92 | 1.80–5.68 | |
| 3 | 6.76–9.48 | 5.68–8.40 | |
| 4 | 9.80–16.68 | 8.40–15.28 | |
| 5 | 17.00–22.80 | 15.28–21.08 | |
| 6 | **23.32**–27.44 | 21.08–25.20 | 23.28 → 23.32 drops the tail of an inhale |
| hold | last frame | 25.20–26.00 | captions stay, music resolves |

12 ms raised-cosine fades on every edge; measured sample jumps at the splices are
< 0.001 (no clicks).

## 2. Picture timeline

| out (s) | picture | framing / clip |
|---|---|---|
| 0.00–1.80 | **face** (hook) | close 1.10→1.14 |
| 1.80–4.36 | B-roll 1 — "एउटा कम्प्युटरले … केही सेकेन्डमै" | typing on laptop / hands typing keyboard night / fast typing |
| 4.36–5.68 | face — "गरिदियो भने कस्तो लाग्ला??" | close 1.10→1.14 |
| 5.68–6.16 | face — "अहिले" | wide 1.00→1.04 (jump cut changes framing) |
| 6.16–7.60 | B-roll 2 — "AI ले ठ्याक्कै यही" | artificial intelligence / robot hand / digital brain / futuristic technology |
| 7.60–8.40 | face — "गरिरहेको छ।" | close |
| 8.40–9.48 | B-roll 3 — "टेक्स्ट लेख्ने" | writing on laptop / typing message laptop / chatbot |
| 9.48–10.56 | B-roll 4 — "फोटो बनाउने" | photo editing / graphic designer tablet / editing photos computer |
| 10.56–11.96 | B-roll 5 — "भिडियो तयार गर्ने" | video editing / video editor timeline / editing video computer |
| 11.96–15.28 | face — "यी सबै काम … सजिलो बनाइदिएको छ।" | wide 1.00→1.04 |
| 15.28–16.16 | face — "त्यसैले" | close |
| 16.16–17.80 | B-roll 6 — "आजको समयमा AI" | student studying laptop / young man learning online / studying at night laptop |
| 17.80–18.76 | face — "सिक्नु भनेको" | wide |
| 18.76–20.36 | B-roll 7 — "आफूलाई एक कदम अगाडि" | walking up stairs / climbing stairs / stepping up stairs |
| 20.36–21.08 | face — "लैजानु हो।" | close |
| 21.08–26.00 | face — CTA | slow push 1.02→1.08 (continues gently over the hold) |

Zooms are smoothstep ramps anchored on the face (MediaPipe 478-point mesh, all 686
frames tracked); the "camera" centre is fixed per shot so it never chases the head.
Max zoom is 1.14, and eyes, mouth and chin stay in frame on every frame. B-roll gets a
1.00→1.06 push-in, a match grade, then the same grade and grain as the studio. Cuts
are hard cuts on word onsets.

## 3. Captions — Noto Sans Devanagari Bold, white, gold `#FFC24D` highlights

27 chunks exactly as in your table (the script re-assembles word-for-word; QC
checks it). They're centred at y≈1250 and the ink spans y 1194–1326, so they stay clear
of the bottom 300 px. 86 px / 96 px (emphasis) are true em sizes. libass sizes by line
metrics, which would otherwise make Devanagari ~half that, so the script converts
them. There's a 3 px dark outline plus a soft blurred shadow layer, and a 150 ms pop-in
(92→100 %, 12 px rise, fade). Highlights: सेकेन्डमै (96), AI, सजिलो, एक कदम अगाडि
(96), मेसेज (96). Each chunk shows one frame before its word, or snaps to a visual cut
just before it. Worst lead is 0.15 s. Shaping is verified (कम्प्युटरले, ठ्याक्कै,
सक्नुहुन्छ, टेक्स्ट, गर्ने all join).

## 4. Grade

+5 % S-curve around a low pivot (endpoints fixed, no clipping) and a 1 % black lift.
Teal goes into the shadows and warmth into the highlights. Skin midtones keep their
hue (measured: about 2 % brighter and 5 % less saturated, with no orange push). −5 % saturation, a light vignette, and fine
luma grain (std 0.0065). Upscale: Lanczos-4 + unsharp 0.5. I skipped Real-ESRGAN:
its weights aren't reachable from this sandbox, and the brief rules out anything that
could change the face.

## 5. Sound

Voice: HPF 75 Hz → light FFT denoise → −1.5 dB @ 280 Hz → +2 dB @ 3.4 kHz → +1.5 dB
shelf @ 9.5 kHz → de-ess → 2.5:1 compressor (processed before cutting, so no filter
state crosses a cut). SFX are generated in numpy: 4 whooshes (B-roll 1, 2, 3, 6 entries,
peaking on the cut, L→R), a 0.9 s riser into "एक कदम अगाडि" (out 19.44), and a soft
pop on "मेसेज" (out 23.89). They peak 13–17 dB under the voice. Music (when supplied)
sits 12 LU under the voice plus 4.5 dB of sidechain ducking under words (≈15–17 dB
below speech). There's a −4 dB breakdown under "त्यसैले आजको समयमा…" (15.28→19.44),
a +1 dB lift at "एक कदम अगाडि", and a 0.6 s fade at the end. If the track is long
enough, its natural ending is back-timed onto the last frame. Master: −14.0 LUFS,
−1.8 dBTP (4× oversampled look-ahead limiter), 48 kHz stereo.

## Deviations from the brief (and why)

1. **B-roll 1 is 2.56 s** (brief: ≤ 2.4). It starts on the 1.80 s jump cut instead of
   2.25 s src. Otherwise a 5-frame flash of the face would sit between the cut and the
   cutaway. The alternative is to trim it to 2.4 s by ending it 4 frames early, inside
   "सेकेन्डमै".
2. **B-roll edges moved to the measured word onsets** (±0.1–0.2 s):
   #2 7.24–8.68, #3 9.80–10.88, #4 10.88–11.96, #5 11.96–13.36 (cuts back on "यी"),
   #6 17.88–19.52 ("आजको" really starts at 17.96; it ends right after "AI", so the
   face says "सिक्नु भनेको"), #7 20.48–22.08. #3→#4→#5 butt together with no face
   flashes between them.
3. **Source audio ends 64 ms before the picture**, and the final "छ" of सक्नुहुन्छ
   is slightly clipped in the AI render itself. I put a 40 ms fade on it so it doesn't
   click, and the music covers the hold.
4. The studio background has a **YouTube play-button plaque** (it's in the avatar
   render, visible in the face shots). The no-logo rule was for B-roll, so I left it.
   I can blur it if you'd prefer.
