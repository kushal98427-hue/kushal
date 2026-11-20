# Edit report — "AI सिक्नुहोस्" reel

**Delivered:** `out/AI_Reel_NoMusic.mp4`: 1080×1920, 25 fps, H.264 High CRF 18, yuv420p
(BT.709), AAC 256 kbps 48 kHz stereo, faststart, 26.00 s.
**Not built yet:** `out/AI_Reel_Final.mp4` needs a copyright-free track in `music/`. Then
run `scripts/build.sh final`; ducking, breakdown, lift and the end fade are already wired up.

## What was done
- **Cuts:** six kept ranges, every edge in silence (−51 to −65 dBFS), 12 ms fades, no
  clicks. One change from the brief: 23.28 → 23.32, to drop an inhale. Plus a 0.8 s held
  last frame. Full table in `EDIT_PLAN.md`.
- **Reframe:** 9:16 crop around the MediaPipe-tracked face (all 686 frames), Lanczos-4
  upscale + unsharp 0.5. Smoothstep zooms alternate close (1.10→1.14) / wide (1.00→1.04)
  on every jump cut, and the CTA has a slow push 1.02→1.08. Max zoom is 1.14, with no
  face retouching.
- **Grade:** +5 % S-curve, teal shadows / warm highlights, −5 % saturation, light
  vignette, fine luma grain, shared by the face shots and the B-roll. Each B-roll clip is
  first pulled halfway to the studio exposure.
- **Captions:** 27 Devanagari chunks, word-for-word the script, Noto Sans Devanagari Bold
  86/96 px (true em size), gold `#FFC24D` highlights, 150 ms pop-in, centred at y≈1250.
- **Sound:** HPF 75 Hz, light denoise, −1.5 dB @ 280 Hz, +2 dB @ 3.4 kHz, +1.5 dB shelf
  @ 9.5 kHz, de-ess, 2.5:1 compression. Generated SFX: 4 whooshes, a riser into
  "एक कदम अगाडि", a pop on "मेसेज", all 13–17 dB under the voice. Mastered to −14 LUFS.

## B-roll (Pixabay; Pexels keys were paused)

| out (s) | line | clip | creator |
|---|---|---|---|
| 1.80–4.36 | एउटा कम्प्युटरले … केही सेकेन्डमै | [3160](https://pixabay.com/videos/id-3160/) fingers typing, close-up | Coverr-Free-Footage |
| 6.16–7.60 | अहिले AI ले ठ्याक्कै यही | [88223](https://pixabay.com/videos/id-88223/) robot arm in a lab | Digital_Expert |
| 8.40–9.48 | टेक्स्ट लेख्ने | [78640](https://pixabay.com/videos/id-78640/) hands typing, wood desk | Engin_Akyurt |
| 9.48–10.56 | फोटो बनाउने | [42967](https://pixabay.com/videos/id-42967/) retouching a photo on a tablet | MaxMedyk |
| 10.56–11.96 | भिडियो तयार गर्ने | [26533](https://pixabay.com/videos/id-26533/) laptop in a production booth | ninosouza |
| 16.16–17.80 | आजको समयमा AI | [139802](https://pixabay.com/videos/id-139802/) student studying in a library | Sang_Soi |
| 18.76–20.36 | आफूलाई एक कदम अगाडि | [152203](https://pixabay.com/videos/id-152203/) climbing temple stairs | u_87zyvw82yc |

Picks were reviewed by eye. 36 rejected candidates are listed with reasons in
`broll_rejects.json` (visible text, brand marks, CGI, off-topic). Sources: `credits.txt`.

## QC (`scripts/qc.py`)
- The face was detected on all 380 face-shot frames. The tightest face→caption gap is
  **153 px** (needs ≥ 60).
- The captions match the script exactly. Worst caption lead vs its word is **0.15 s**.
- Loudness is **−14.0 LUFS**, true peak **−1.8 dBTP**.
- I reviewed the 1 fps contact sheet. Full-resolution checks of the gold captions over
  the brightest B-roll confirm they stay legible.

## Known compromises
- B-roll 1 runs 2.56 s, over the brief's 2.4 s max. It starts on the jump cut so no
  5-frame face flash is left before it.
- Four clips are 1080p landscape, so their 9:16 crop is upscaled about 1.8×. That's
  still sharper than the 512 px source avatar.
- The source audio clips the final "छ" slightly. It has a 40 ms fade.
- The studio background shows a YouTube plaque from the avatar render. It's left as is.
