"""Track the avatar's face on every source frame with MediaPipe FaceLandmarker.

Writes work/face_track.json: per-frame face box (all 478 landmarks), eye centre,
mouth centre and chin point, in source pixels (512x768).
"""
import json
import sys

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision

SRC = sys.argv[1] if len(sys.argv) > 1 else "raw.mp4"
OUT = sys.argv[2] if len(sys.argv) > 2 else "work/face_track.json"
MODEL = "work/models/face_landmarker.task"

opts = vision.FaceLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path=MODEL),
    running_mode=vision.RunningMode.VIDEO,
    num_faces=1,
)
lm = vision.FaceLandmarker.create_from_options(opts)
cap = cv2.VideoCapture(SRC)
fps = cap.get(cv2.CAP_PROP_FPS)
frames = []
i = 0
while True:
    ok, bgr = cap.read()
    if not ok:
        break
    h, w = bgr.shape[:2]
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    res = lm.detect_for_video(img, int(i * 1000 / fps))
    rec = {"i": i}
    if res.face_landmarks:
        p = np.array([[q.x * w, q.y * h] for q in res.face_landmarks[0]])
        x0, y0 = p.min(0)
        x1, y1 = p.max(0)
        eyes = (p[33] + p[263]) / 2  # outer eye corners
        mouth = (p[13] + p[14]) / 2
        chin = p[152]
        rec.update(box=[float(x0), float(y0), float(x1), float(y1)],
                   eyes=eyes.tolist(), mouth=mouth.tolist(), chin=chin.tolist(),
                   centre=[float((x0 + x1) / 2), float((y0 + y1) / 2)])
    frames.append(rec)
    i += 1
lm.close()
json.dump({"fps": fps, "w": w, "h": h, "frames": frames}, open(OUT, "w"))
ok = [f for f in frames if "box" in f]
b = np.array([f["box"] for f in ok])
print(f"frames {len(frames)}, detected {len(ok)}")
print("box x0 %.0f-%.0f  y0 %.0f-%.0f  x1 %.0f-%.0f  y1(chin) %.0f-%.0f" % (
    b[:, 0].min(), b[:, 0].max(), b[:, 1].min(), b[:, 1].max(), b[:, 2].min(), b[:, 2].max(), b[:, 3].min(), b[:, 3].max()))
c = np.array([f["centre"] for f in ok])
print("centre x %.0f..%.0f (mean %.0f)  y %.0f..%.0f (mean %.0f)" % (c[:, 0].min(), c[:, 0].max(), c[:, 0].mean(), c[:, 1].min(), c[:, 1].max(), c[:, 1].mean()))
