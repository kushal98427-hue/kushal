"""Render the picture: 9:16 face reframe with keyframed zooms, B-roll cutaways,
grade, vignette, grain, then libass captions -> H.264.

  python3 scripts/render.py OUT.mp4 [--preview]

--preview: B-roll slots whose clip is missing are filled with a labelled
placeholder (dimmed face) so framing, captions and grade can be checked
before the B-roll exists. The final render refuses to run with missing clips.
"""
import json
import os
import subprocess
import sys
from multiprocessing import Pool

import cv2
import numpy as np

sys.path.insert(0, "scripts")
from timeline import (BROLL, DURATION, FPS, H, N_FRAMES, SRC_H, SRC_W, W,  # noqa: E402
                      framing_plan, out_frame_to_src_frame)

PREVIEW = "--preview" in sys.argv
OUT = [a for a in sys.argv[1:] if not a.startswith("--")][0]
UNSHARP = 0.5
VIGNETTE = 0.22
GRAIN = 0.0065  # luma grain std (0-1 scale); 0.016 pushed CRF 18 to ~27 Mbps
GRAIN_SIZE = 0.8
BROLL_PUSH = (1.00, 1.06)

# ------------------------------------------------------------------ inputs
SRC = None  # all source frames, loaded once and shared with workers via fork
TRACK = json.load(open("work/face_track.json"))["frames"]
PLAN = framing_plan()
BROLL_META = json.load(open("work/broll_meta.json")) if os.path.exists("work/broll_meta.json") else {}


def load_source():
    cap = cv2.VideoCapture("raw.mp4")
    fr = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        fr.append(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
    return np.stack(fr)


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


# fixed camera centre per face run (mean face centre over the run) — a static
# "camera" plus the keyframed zoom reads better than a crop that chases the face
for r in PLAN:
    a, b = r["out"]
    idx = sorted({out_frame_to_src_frame(n) for n in range(round(a * FPS), round(b * FPS))})
    c = np.array([TRACK[i]["centre"] for i in idx])
    r["cx"], r["cy"] = float(c[:, 0].mean()), float(c[:, 1].mean())


def run_at(t):
    for r in PLAN:
        if r["out"][0] - 1e-6 <= t < r["out"][1] - 1e-6:
            return r
    return PLAN[-1]


def broll_at(t):
    for b in BROLL:
        if b["out"][0] - 1e-6 <= t < b["out"][1] - 1e-6:
            return b
    return None


# ------------------------------------------------------------------ picture
def face_window(t, r):
    a, b = r["out"]
    z0, z1 = r["zoom"]
    z = z0 + (z1 - z0) * smoothstep((t - a) / max(b - a, 1e-6))
    w, h = (SRC_H * 9 / 16) / z, SRC_H / z
    x0 = np.clip(r["cx"] - w / 2, 0, SRC_W - w)
    y0 = np.clip(r["cy"] * (1 - 1 / z), 0, SRC_H - h)  # zoom anchored on the face
    return x0, y0, w, h, z


def face_frame(n, t, r):
    src = SRC[out_frame_to_src_frame(n)]
    x0, y0, w, h, _ = face_window(t, r)
    s = W / w
    M = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
    img = cv2.warpAffine(src, M, (W, H), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
    f = img.astype(np.float32) / 255
    blur = cv2.GaussianBlur(f, (0, 0), 1.4)
    return np.clip(f + UNSHARP * (f - blur), 0, 1)


_BROLL_CACHE = {}


def broll_frames(slot):
    if slot["id"] not in _BROLL_CACHE:
        p = f"work/broll_{slot['id']}.npy"
        _BROLL_CACHE[slot["id"]] = np.load(p, mmap_mode="r") if os.path.exists(p) else None
    return _BROLL_CACHE[slot["id"]]


def match_broll(f, meta):
    """Pull a B-roll clip towards the studio footage before the shared grade:
    exposure/contrast via a luma curve fitted on the clip, slight desaturation."""
    L = 0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]
    gain = meta.get("gain", 1.0)
    gamma = meta.get("gamma", 1.0)
    Ln = np.clip(L * gain, 0, 1) ** gamma
    ratio = (Ln + 1e-4) / (L + 1e-4)
    f = np.clip(f * ratio[..., None], 0, 1)
    L = Ln
    sat = meta.get("sat", 0.85)
    return np.clip(L[..., None] + (f - L[..., None]) * sat, 0, 1)


def broll_frame(n, t, slot):
    frames = broll_frames(slot)
    a, b = slot["out"]
    k = n - round(a * FPS)
    if frames is None:
        return None
    img = np.asarray(frames[min(k, len(frames) - 1)])
    z = BROLL_PUSH[0] + (BROLL_PUSH[1] - BROLL_PUSH[0]) * ((t - a) / (b - a))
    cx, cy = W / 2, H / 2
    M = np.float32([[z, 0, cx - z * cx], [0, z, cy - z * cy]])
    img = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    f = img.astype(np.float32) / 255
    return match_broll(f, BROLL_META.get(str(slot["id"]), {}))


def placeholder(n, t, slot):
    r = run_at(slot["out"][0] - 0.01) if slot["out"][0] > 0 else PLAN[0]
    f = face_frame(n, t, dict(r, out=slot["out"], zoom=(1.0, 1.0)))
    f = cv2.GaussianBlur(f, (0, 0), 18) * 0.35
    img = (f * 255).astype(np.uint8)
    cv2.putText(img, f"B-ROLL {slot['id']}", (300, 860), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (230, 230, 230), 5, cv2.LINE_AA)
    cv2.putText(img, slot["queries"][0], (300, 940), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (200, 200, 200), 2, cv2.LINE_AA)
    return img.astype(np.float32) / 255


# ------------------------------------------------------------------ look
PIVOT = 0.20
CONTRAST = 1.05


def grade(f):
    # gentle S-curve around a low pivot (+5% slope), endpoints fixed so nothing clips
    lo = f < PIVOT
    g = np.empty_like(f)
    g[lo] = PIVOT * (f[lo] / PIVOT) ** CONTRAST
    g[~lo] = 1 - (1 - PIVOT) * ((1 - f[~lo]) / (1 - PIVOT)) ** CONTRAST
    g = 0.012 + g * (1 - 0.012)  # tiny black lift so the grain lives in the shadows
    L = 0.2126 * g[..., 0] + 0.7152 * g[..., 1] + 0.0722 * g[..., 2]
    ws = (1 - L) ** 3
    wh = smoothstep((L - 0.45) / 0.55)
    g = g + ws[..., None] * np.float32([-0.010, 0.004, 0.012]) + wh[..., None] * np.float32([0.018, 0.006, -0.014])
    L = 0.2126 * g[..., 0] + 0.7152 * g[..., 1] + 0.0722 * g[..., 2]
    g = L[..., None] + (g - L[..., None]) * 0.95
    return np.clip(g, 0, 1)


_yy, _xx = np.mgrid[0:H, 0:W].astype(np.float32)
_r = np.sqrt(((_xx - W / 2) / (W / 2)) ** 2 * 0.9 + ((_yy - H * 0.46) / (H / 2)) ** 2 * 0.75)
VIG = (1 - VIGNETTE * smoothstep((_r - 0.35) / 0.75)).astype(np.float32)[..., None]
del _yy, _xx, _r


def finish(f, n):
    f = f * VIG
    rng = np.random.default_rng(1000 + n)
    g = cv2.GaussianBlur(rng.standard_normal((H, W), dtype=np.float32), (0, 0), GRAIN_SIZE)
    g *= GRAIN / g.std()
    L = 0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]
    amp = 0.55 + 1.8 * L * (1 - L)  # strongest in the mids, still visible in blacks
    return np.clip(f + (g * amp)[..., None], 0, 1)


def render(n):
    t = n / FPS
    slot = broll_at(t)
    f = None
    if slot is not None:
        f = broll_frame(n, t, slot)
        if f is None:
            f = placeholder(n, t, slot)
    if f is None:
        f = face_frame(n, t, run_at(t))
    f = finish(grade(f), n)
    return (f * 255 + 0.5).astype(np.uint8).tobytes()


def main():
    global SRC
    missing = [b["id"] for b in BROLL if not os.path.exists(f"work/broll_{b['id']}.npy")]
    if missing and not PREVIEW:
        sys.exit(f"missing B-roll for slots {missing}; run fetch/prep first or use --preview")
    SRC = load_source()
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-",
           "-vf", "ass=work/captions.ass:fontsdir=fonts,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
           "-movflags", "+faststart", OUT]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(os.cpu_count()) as pool:
        for k, buf in enumerate(pool.imap(render, range(N_FRAMES), chunksize=2)):
            p.stdin.write(buf)
            if k % 100 == 0:
                print(f"frame {k}/{N_FRAMES}", flush=True)
    p.stdin.close()
    p.wait()
    print("wrote", OUT, f"{N_FRAMES} frames, {DURATION}s")


if __name__ == "__main__":
    main()
