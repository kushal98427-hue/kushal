"""Conform the chosen B-roll for the renderer.

For each slot: pick the (already trimmed, see fetch_broll.py archive) clip in
broll/slot<N>_*.mp4, conform to 25 fps
(24/25/30 fps footage is reinterpreted frame-for-frame = smooth slight slow-mo;
50/60 fps drops every other frame first), scale-to-cover 1080x1920 with a
centre crop (x offset "xoff" in broll_inpoints.json), trim to the slot
length and store as work/broll_<N>.npy. Also fits the match-grade
(work/broll_meta.json) that pulls each clip towards the studio footage.
"""
import glob
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, "scripts")
from timeline import BROLL, FPS, H, W  # noqa: E402

OVR = json.load(open("broll_inpoints.json")) if os.path.exists("broll_inpoints.json") else {}
# studio footage reference, measured on the 9:16 crop of raw.mp4 (luma p50 0.056,
# p95 0.516, chroma/mean-luma 0.17); B-roll is allowed to sit a touch brighter
REF = dict(luma50=0.07, luma95=0.52, relchroma=0.17)


def probe_fps(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    a, b = r.split("/")
    return float(a) / float(b)


def conform(path, start, nframes, xoff):
    fps = probe_fps(path)
    pre = "select='not(mod(n\\,2))'," if fps > 45 else ""
    eff = fps / 2 if fps > 45 else fps
    # reinterpret at 25 fps: frame N of the (decimated) clip is shown at N/25 s
    vf = (f"{pre}setpts=N/({FPS}*TB),"
          f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={W}:{H}:(iw-{W})/2*(1+{xoff}):(ih-{H})/2,format=rgb24")
    # start is in clip seconds; convert to the decimated frame index
    first = int(round(start * eff))
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-an", "-vf", vf + f",select='gte(n\\,{first})'",
           "-frames:v", str(nframes), "-vsync", "0", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    arr = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    if len(arr) < nframes:  # pad by holding the last frame (should not happen: search requires length)
        arr = np.concatenate([arr, np.repeat(arr[-1:], nframes - len(arr), 0)])
    return arr, fps


def fit_match(arr):
    f = arr[:: max(1, len(arr) // 8), ::4, ::4].astype(np.float32) / 255
    L = f @ np.float32([0.2126, 0.7152, 0.0722])
    c50, c95 = np.percentile(L, 50) + 1e-3, np.percentile(L, 95) + 1e-3
    relchroma = np.abs(f - L[..., None]).mean() / (L.mean() + 1e-3)
    # move half the way (in log space) towards the studio look — keeps each clip's character;
    # gamma above ~1.35 crushed close-ups (fingers on a keyboard vanished), so it is capped there
    t50 = np.exp(0.5 * np.log(c50) + 0.5 * np.log(REF["luma50"]))
    t95 = np.exp(0.5 * np.log(c95) + 0.5 * np.log(REF["luma95"]))
    gamma = float(np.clip((np.log(t95) - np.log(t50)) / (np.log(c95) - np.log(c50)), 0.8, 1.35))
    gain = float(np.clip(np.exp(np.log(t50) / gamma - np.log(c50)), 0.5, 1.3))
    sat = float(np.clip((REF["relchroma"] / max(relchroma, 1e-3)) ** 0.5, 0.72, 0.95))
    return dict(gain=gain, gamma=gamma, sat=sat, luma50=float(c50), luma95=float(c95), relchroma=float(relchroma))


def main():
    meta = {}
    for slot in BROLL:
        sid = str(slot["id"])
        files = sorted(glob.glob(f"broll/slot{sid}_*.mp4"))
        if not files:
            print(f"slot {sid}: no clip yet")
            continue
        n = round((slot["out"][1] - slot["out"][0]) * FPS)
        o = OVR.get(sid, {})
        arr, fps = conform(files[0], o.get("trim_start", 0.0), n, o.get("xoff", 0.0))
        np.save(f"work/broll_{sid}.npy", arr)
        # "start" is the in-point in the full downloaded clip (archive already trimmed there)
        meta[sid] = dict(fit_match(arr), file=files[0], src_fps=fps, start=o.get("start", 0.2), frames=n)
        print(f"slot {sid}: {files[0]} @{fps:.2f}fps -> {n} frames, match {meta[sid]['gain']:.2f}/"
              f"{meta[sid]['gamma']:.2f}/{meta[sid]['sat']:.2f}")
    json.dump(meta, open("work/broll_meta.json", "w"), indent=1)


if __name__ == "__main__":
    main()
