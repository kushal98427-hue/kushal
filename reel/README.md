# AI सिक्नुहोस् — reel edit

Scripted edit of `raw.mp4` (Creatify Aurora avatar) into a 1080×1920 Reels/TikTok/Shorts
video. The plan, with all timings, is in [EDIT_PLAN.md](EDIT_PLAN.md).

## Status

- Done: cuts, face reframe with keyframed zooms, grade, captions (shaping verified),
  voice chain, SFX, mastering, QC; B-roll picked, trimmed and conformed (see STATUS.md).
- B-roll comes from the Pixabay Videos API (Pexels keys are paused): needs
  `PIXABAY_API_KEY` in the environment and the hosts `pixabay.com` + `cdn.pixabay.com`.
- Waiting on: **music** — one copyright-free track in `music/` for `AI_Reel_Final.mp4`.

## Run

```bash
scripts/setup.sh            # deps + face model (fonts are in fonts/)
scripts/build.sh analyse    # face track, timing check, captions, sound
scripts/build.sh broll      # Pixabay -> broll_candidates.jpg (checkpoint) -> broll/ + credits.txt
scripts/build.sh final      # render + mux out/AI_Reel_Final.mp4 and out/AI_Reel_NoMusic.mp4 + QC
```

The reviewed B-roll pick per slot is in `broll_choice.json` (`{"<slot>": <pixabay id>}`); slots left out are auto-picked by score.
In-points (in the full downloaded clip) and horizontal crop offsets go in `broll_inpoints.json`
(`{"<slot>": {"start": 1.5, "xoff": -0.3}}`); `fetch_broll.py archive` trims each chosen
clip at its in-point into `broll/`, which is committed so re-renders don't need the API.

`python3 scripts/render.py work/preview.mp4 --preview` renders with labelled placeholders
for any B-roll slot that has no clip yet.
