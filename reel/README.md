# AI सिक्नुहोस् — reel edit

Scripted edit of `raw.mp4` (Creatify Aurora avatar) into a 1080×1920 Reels/TikTok/Shorts
video. The plan, with all timings, is in [EDIT_PLAN.md](EDIT_PLAN.md).

## Status

- Done: cuts, face reframe with keyframed zooms, grade, captions (shaping verified),
  voice chain, SFX, mastering, QC. A NoMusic preview with B-roll placeholders passes QC.
- Waiting on:
  1. **Pexels access.** Set `PEXELS_API_KEY` as an environment variable or secret, and
     allow the hosts `api.pexels.com`, `videos.pexels.com` and `images.pexels.com`.
  2. **Music.** Put one copyright-free track in `music/`.

## Run

```bash
scripts/setup.sh            # deps + face model (fonts are in fonts/)
scripts/build.sh analyse    # face track, timing check, captions, sound
scripts/build.sh broll      # Pexels -> broll_candidates.jpg (checkpoint) -> broll/ + credits.txt
scripts/build.sh final      # render + mux out/AI_Reel_Final.mp4 and out/AI_Reel_NoMusic.mp4 + QC
```

The automatic B-roll pick can be overridden in `work/broll_choice.json` (`{"<slot>": <pexels id>}`).
In-points (in the full Pexels clip) and horizontal crop offsets go in `broll_inpoints.json`
(`{"<slot>": {"start": 1.5, "xoff": -0.3}}`); `fetch_broll.py archive` trims each chosen
clip at its in-point into `broll/`, which is committed so re-renders don't need Pexels.

`python3 scripts/render.py work/preview.mp4 --preview` renders with labelled placeholders
for any B-roll slot that has no clip yet.
