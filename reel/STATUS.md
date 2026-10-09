# Status — B-roll checkpoint (Pixabay)

B-roll comes from the Pixabay Videos API, because the Pexels keys are paused. The search
queries, the 7 slots and the selection rules are unchanged from the brief; see
`scripts/timeline.py` and `scripts/fetch_broll.py`.

Pixabay differs from Pexels in a few ways, and the script handles each:
- There's no orientation filter, so orientation is checked client-side. Portrait is
  preferred, then 4K landscape (its 9:16 crop is still ≥1080 px wide), then 1080p landscape,
  whose crop gets upscaled about 1.8× and takes a score penalty.
- Search matches *any* word, so a clip's tags must contain the query's content words
  (at most one missing on 3+ word queries). Thin slots also review half-matches.
- `video_type=film` is set, and anything flagged `isAiGenerated` or `isLowQuality` is
  dropped, which keeps the footage real.

Picks were reviewed by eye (`broll_choice.json`), and rejections are recorded with
reasons (`broll_rejects.json`). In-points and crop offsets are in `broll_inpoints.json`.
The trimmed 1080×1920 clips are committed in `broll/`, and the sources are in `credits.txt`.

| slot | line | Pixabay id | creator | source |
|---|---|---|---|---|
| 1 | एउटा कम्प्युटरले … केही सेकेन्डमै | 3160 | Coverr-Free-Footage | 1080p, ×1.8 crop |
| 2 | अहिले AI ले ठ्याक्कै यही | 88223 | Digital_Expert | 4K |
| 3 | टेक्स्ट लेख्ने | 78640 | Engin_Akyurt | 4K |
| 4 | फोटो बनाउने | 42967 | MaxMedyk | 1080p, ×1.8 crop |
| 5 | भिडियो तयार गर्ने | 26533 | ninosouza | 1080p, ×1.8 crop |
| 6 | आजको समयमा AI | 139802 | Sang_Soi | 4K |
| 7 | आफूलाई एक कदम अगाडि | 152203 | u_87zyvw82yc | 1080p, ×1.8 crop |

The match grade now pulls each clip halfway toward the studio exposure, with gamma
capped at 1.35. The earlier 60 % pull with a 1.6 cap crushed the typing close-up.

Next: `scripts/build.sh final` (render + QC). Music is still missing, so only
`out/AI_Reel_NoMusic.mp4` can be built until a track is added to `music/`.
