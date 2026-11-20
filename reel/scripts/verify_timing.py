"""Check every cut and B-roll edge against the voice energy envelope.

Prints the RMS level (20 ms window) at each kept-range edge (must be silence)
and at each B-roll edge (should sit at a word boundary / low point).
"""
import subprocess
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, "scripts")
from timeline import BROLL, SEGMENTS  # noqa: E402

subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "raw.mp4", "-vn", "-ac", "1", "-ar", "48000", "work/voice_raw48.wav"],
               check=True)
x, sr = sf.read("work/voice_raw48.wav")


def level(t, win=0.02):
    i = int(t * sr)
    seg = x[max(0, i - int(win * sr / 2)): i + int(win * sr / 2)]
    return 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9) if len(seg) else -120.0


def quietest_near(t, span=0.06):
    ts = np.arange(t - span, t + span, 0.005)
    return max(level(u) for u in ts)


bad = 0
print("cut edges (level at the edge, loudest within ±60 ms):")
for a, b in SEGMENTS:
    for t in (a, b):
        if t <= 0 or t >= len(x) / sr:
            continue
        lv, mx = level(t), quietest_near(t)
        ok = mx < -40
        bad += not ok
        print(f"  {t:6.2f}s  {lv:6.1f} dBFS  (max nearby {mx:6.1f})  {'ok' if ok else 'NOT SILENT'}")
print("B-roll edges:")
for s in BROLL:
    for t in s["src"]:
        print(f"  #{s['id']} {t:6.2f}s  {level(t):6.1f} dBFS")
sys.exit(1 if bad else 0)
