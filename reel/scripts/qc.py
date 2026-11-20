"""Quality control for a rendered reel.

  python3 scripts/qc.py VIDEO.mp4 [MIX.wav]

1. Face detection on every output frame of the face segments; captions must
   keep >= 60 px clear of the face box (forehead..chin from the 478-point mesh).
2. Caption chunks re-assemble into the script exactly; every chunk appears
   within 0.15 s of its measured word onset.
3. Loudness / true peak of the delivered file.
4. Contact sheet (1 frame per second) -> work/qc_contact_<name>.png
"""
import json
import os
import re
import subprocess
import sys

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision

sys.path.insert(0, "scripts")
from timeline import (BROLL, CAPTION_LEAD, CAPTIONS, FPS, SCRIPT, caption_events,  # noqa: E402
                      src_to_out)

VIDEO = sys.argv[1]
name = os.path.splitext(os.path.basename(VIDEO))[0]
MIN_GAP = 60
problems = []

# --- caption geometry: measured once from the static caption sheet (work/caption_tops.json)
tops = json.load(open("work/caption_tops.json"))

# --- 1. face vs caption
opts = vision.FaceLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path="work/models/face_landmarker.task"),
                                    running_mode=vision.RunningMode.VIDEO, num_faces=1)
lm = vision.FaceLandmarker.create_from_options(opts)
events = caption_events()
cap = cv2.VideoCapture(VIDEO)
n = 0
worst = (1e9, None)
face_frames = 0
while True:
    ok, bgr = cap.read()
    if not ok:
        break
    t = n / FPS
    in_broll = any(b["out"][0] - 1e-6 <= t < b["out"][1] - 1e-6 for b in BROLL)
    if not in_broll:
        face_frames += 1
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        res = lm.detect_for_video(img, int(n * 1000 / FPS))
        if not res.face_landmarks:
            problems.append(f"no face found at {t:.2f}s")
        else:
            ys = np.array([q.y for q in res.face_landmarks[0]]) * bgr.shape[0]
            bottom = ys.max()
            ev = [e for e in events if e[0] - 1e-6 <= t < e[1] - 1e-6]
            if ev:
                gap = tops[ev[0][2]] - bottom
                if gap < worst[0]:
                    worst = (gap, t)
                if gap < MIN_GAP:
                    problems.append(f"caption '{ev[0][2]}' only {gap:.0f}px below the face at {t:.2f}s")
    n += 1
lm.close()
print(f"frames {n}; face frames checked {face_frames}; tightest face->caption gap {worst[0]:.0f}px at {worst[1]:.2f}s")

# --- 2. script + sync
words = " ".join(c[1] for c in CAPTIONS).split()
script_words = SCRIPT.split()
if words != script_words:
    problems.append("caption words differ from the script")
print("caption text == script:", words == script_words)
worst_sync = 0.0
for (src_t, text, *_), (s, e, *_r) in zip(CAPTIONS, events):
    d = src_to_out(src_t) - s  # lead (+) of caption over the voice
    worst_sync = max(worst_sync, abs(d))
    if abs(d) > 0.15 + 1e-6:
        problems.append(f"'{text}' off by {d:.2f}s")
print(f"worst caption lead vs word onset: {worst_sync:.2f}s")

# --- 3. loudness of the delivered file
r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", VIDEO, "-af", "ebur128=peak=true", "-f", "null", "-"],
                   capture_output=True, text=True).stderr
if "Summary:" in r:
    summ = r[r.rfind("Summary:"):]
    I = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summ).group(1))
    tp = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ).group(1))
    print(f"loudness {I} LUFS, true peak {tp} dBTP")
    if abs(I + 14) > 0.5:
        problems.append(f"loudness {I} LUFS")
    if tp > -1.5:
        problems.append(f"true peak {tp} dBTP")

# --- 4. contact sheet
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", VIDEO, "-vf", "fps=1,scale=270:480,tile=9x3:padding=4",
                "-frames:v", "1", f"work/qc_contact_{name}.png"], check=True)
print("contact sheet:", f"work/qc_contact_{name}.png")
print("QC PASS" if not problems else "QC FAIL:\n  " + "\n  ".join(problems[:30]))
sys.exit(1 if problems else 0)
