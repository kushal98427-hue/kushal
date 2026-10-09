#!/usr/bin/env bash
# Full pipeline. Stages can be run one at a time:
#   scripts/build.sh analyse    face track + timing check + captions + sound (no external deps)
#   scripts/build.sh broll      Pexels search/score -> broll_candidates.jpg (checkpoint), download, conform
#   scripts/build.sh final      render picture once, mux both deliverables, QC
set -euo pipefail
cd "$(dirname "$0")/.."
stage="${1:-all}"

if [[ $stage == analyse || $stage == all ]]; then
  python3 scripts/track_face.py raw.mp4 work/face_track.json
  python3 scripts/verify_timing.py
  python3 scripts/captions.py
  python3 scripts/audio.py
fi

if [[ $stage == broll || $stage == all ]]; then
  python3 scripts/fetch_broll.py search
  python3 scripts/fetch_broll.py analyze
  python3 scripts/fetch_broll.py download
  python3 scripts/fetch_broll.py archive
  python3 scripts/prep_broll.py
fi

if [[ $stage == final || $stage == all ]]; then
  python3 scripts/audio.py
  python3 scripts/render.py work/video.mp4
  enc=(-c:v copy -c:a aac -b:a 256k -ar 48000 -ac 2 -movflags +faststart)
  ffmpeg -v error -y -i work/video.mp4 -i work/mix_nomusic.wav -map 0:v -map 1:a "${enc[@]}" out/AI_Reel_NoMusic.mp4
  if [[ -f work/mix_final.wav ]]; then
    ffmpeg -v error -y -i work/video.mp4 -i work/mix_final.wav -map 0:v -map 1:a "${enc[@]}" out/AI_Reel_Final.mp4
  else
    echo "no music in music/ — only AI_Reel_NoMusic.mp4 was built"
  fi
  for f in out/AI_Reel_*.mp4; do python3 scripts/qc.py "$f"; done
fi
