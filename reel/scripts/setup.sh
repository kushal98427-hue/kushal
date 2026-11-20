#!/usr/bin/env bash
# One-time setup: Python deps, EGL for MediaPipe, face-landmark model.
# Fonts (Noto Sans Devanagari Bold instanced from the google/fonts variable font,
# Poppins Bold/Medium) are committed in fonts/.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v ffmpeg >/dev/null || { echo "ffmpeg (with libass) is required"; exit 1; }
ffmpeg -hide_banner -filters 2>/dev/null | grep -q " ass " || { echo "ffmpeg lacks libass"; exit 1; }
pip3 install -q opencv-python-headless soundfile scipy requests numpy fonttools pyloudnorm mediapipe
if ! ldconfig -p | grep -q libEGL.so.1; then
  (apt-get install -y -q libegl1 libgles2 || (apt-get update -q && apt-get install -y -q libegl1 libgles2)) >/dev/null
fi
mkdir -p work/models broll music out
[ -f work/models/face_landmarker.task ] || curl -sSfL -o work/models/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
echo "setup ok"
