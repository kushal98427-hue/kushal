"""Sound: voice chain, cuts with micro-fades, generated SFX, music bed with
sidechain ducking + automation, master to -14 LUFS / -1.5 dBTP, 48 kHz stereo.

  python3 scripts/audio.py              -> work/mix_nomusic.wav (+ work/mix_final.wav if music/ has a track)
"""
import glob
import json
import subprocess
import sys

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.ndimage import minimum_filter1d
from scipy.signal import lfilter, resample_poly, stft, istft

sys.path.insert(0, "scripts")
from timeline import (BREAKDOWN, DURATION, POP_AT, RISER_END, SEGMENTS,  # noqa: E402
                      WHOOSH_AT)

SR = 48000
N = round(DURATION * SR)
FADE = 0.012  # 12 ms at every cut
TARGET_LUFS = -14.0
TP_CEIL = -1.5
rng = np.random.default_rng(7)


def db(x):
    return 10 ** (x / 20)


# ------------------------------------------------------------------ voice
def process_voice():
    """Voice chain on the whole source first, so no filter state straddles a cut."""
    chain = ",".join([
        "highpass=f=75:poles=2",
        "afftdn=nr=6:nf=-55:tn=1",                      # light denoise
        "equalizer=f=280:t=q:w=1.0:g=-1.5",
        "equalizer=f=3400:t=q:w=0.9:g=2",
        "highshelf=f=9500:g=1.5",
        "deesser=i=0.25:m=0.5:f=0.5:s=o",                # gentle de-ess
        "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:knee=4",
    ])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "raw.mp4", "-vn", "-ac", "1", "-ar", str(SR),
                    "-af", chain, "-c:a", "pcm_f32le", "work/voice_proc.wav"], check=True)
    x, sr = sf.read("work/voice_proc.wav", dtype="float32")
    assert sr == SR
    return x


def cut_voice(x):
    out = []
    nf = round(FADE * SR)
    ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, nf))).astype(np.float32)
    src_end = len(x)
    for a, b in SEGMENTS:
        i0, i1 = round(a * SR), round(b * SR)
        seg = np.zeros(i1 - i0, np.float32)
        avail = x[i0:min(i1, src_end)]
        seg[:len(avail)] = avail
        if len(avail) < len(seg):  # source audio ends 64 ms before the picture: fade the truncated tail
            k = round(0.04 * SR)
            avail_end = len(avail)
            seg[avail_end - k:avail_end] *= np.linspace(1, 0, k, dtype=np.float32)
        seg[:nf] *= ramp
        seg[-nf:] *= ramp[::-1]
        out.append(seg)
    v = np.concatenate(out)
    return np.pad(v, (0, N - len(v)))


# ------------------------------------------------------------------ SFX
def band_noise(dur, f_of_t, bw_oct=0.9, seed=0):
    """White noise shaped by a moving Gaussian band (centre f_of_t(t), Hz)."""
    r = np.random.default_rng(seed)
    n = round(dur * SR)
    x = r.standard_normal(n + 2048).astype(np.float32)
    f, t, Z = stft(x, SR, nperseg=1024, noverlap=768)
    fc = f_of_t(np.clip(t, 0, dur))[None, :]
    lf = np.log2(np.maximum(f, 1))[:, None]
    mask = np.exp(-0.5 * ((lf - np.log2(fc)) / (bw_oct / 2)) ** 2)
    _, y = istft(Z * mask, SR, nperseg=1024, noverlap=768)
    y = y[:n]
    return y / (np.abs(y).max() + 1e-9)


def whoosh(dur=0.55, peak=0.36, seed=0):
    t = np.arange(round(dur * SR)) / SR

    def fc(tt):
        up = 250 * (2600 / 250) ** np.clip(tt / peak, 0, 1)
        down = 2600 * (700 / 2600) ** np.clip((tt - peak) / (dur - peak), 0, 1)
        return np.where(tt < peak, up, down)

    y = band_noise(dur, fc, 1.1, seed)
    env = np.where(t < peak, (t / peak) ** 2.2, np.exp(-(t - peak) / 0.07))
    y = y * env
    pan = np.clip(t / dur, 0, 1)  # sweep left -> right
    return np.stack([y * np.cos(pan * np.pi / 2) * 1.2, y * np.sin(pan * np.pi / 2) * 1.2], 1), peak


def riser(dur=0.9, seed=11):
    t = np.arange(round(dur * SR)) / SR
    y = band_noise(dur, lambda tt: 400 * (5500 / 400) ** (tt / dur), 1.3, seed)
    tone = np.sin(2 * np.pi * np.cumsum(220 * (4 ** (t / dur))) / SR) * 0.25
    env = (t / dur) ** 2.5
    env[-round(0.012 * SR):] *= np.linspace(1, 0, round(0.012 * SR))
    y = (y + tone) * env
    return np.stack([y * 0.95, y], 1)


def pop():
    dur = 0.09
    t = np.arange(round(dur * SR)) / SR
    f = 620 + 520 * np.exp(-t / 0.012)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.022)
    click = rng.standard_normal(len(t)) * np.exp(-t / 0.0015) * 0.25
    y = body + click
    y = lfilter([0.35], [1, -0.65], y)  # soften the top end
    y /= np.abs(y).max()
    attack = round(0.002 * SR)
    y[:attack] *= np.linspace(0, 1, attack)
    return np.stack([y, y], 1)


def place(bus, clip, at, gain_db):
    i = round(at * SR)
    j = min(len(bus), i + len(clip))
    if i < 0:
        clip, i = clip[-i:], 0
    bus[i:j] += clip[: j - i] * db(gain_db)


def build_sfx(voice_peak_db):
    """SFX bus; levels are set relative to the voice so nothing out-shouts it."""
    bus = np.zeros((N, 2), np.float32)
    rel = voice_peak_db
    for k, at in enumerate(WHOOSH_AT):
        w, pk = whoosh(seed=k + 1)
        place(bus, w, at - pk, rel - 15)
    r = riser()
    place(bus, r, RISER_END - len(r) / SR, rel - 17)
    place(bus, pop(), POP_AT - 0.005, rel - 13)
    return bus


# ------------------------------------------------------------------ music
def voice_env(v, att=0.015, rel=0.25):
    """Smoothed voice activity (0..1) for sidechain ducking."""
    hop = 240
    frames = v[: len(v) // hop * hop].reshape(-1, hop)
    rms = np.sqrt((frames ** 2).mean(1) + 1e-12)
    act = np.clip((20 * np.log10(rms) + 50) / 20, 0, 1)  # -50 dBFS -> 0, -30 dBFS -> 1
    a_att, a_rel = np.exp(-hop / (att * SR)), np.exp(-hop / (rel * SR))
    env = np.zeros_like(act)
    e = 0.0
    for i, x in enumerate(act):
        a = a_att if x > e else a_rel
        e = a * e + (1 - a) * x
        env[i] = e
    env = np.repeat(env, hop)
    return np.pad(env, (0, len(v) - len(env)), mode="edge").astype(np.float32)


def automation(n):
    """Music gain curve in dB: breakdown dip, lift at 'एक कदम अगाडि', fade-out."""
    t = np.arange(n) / SR
    g = np.zeros(n, np.float32)
    b0, b1 = BREAKDOWN
    down = np.clip((t - b0) / 0.35, 0, 1)
    up = np.clip((t - (b1 - 0.15)) / 0.3, 0, 1)
    g += -4.0 * down * (1 - up)  # breakdown under "त्यसैले आजको समयमा …"
    g += 1.0 * up                 # lift from "एक कदम अगाडि" to the end
    fo = np.clip((t - (DURATION - 0.6)) / 0.6, 0, 1)
    g += 20 * np.log10(np.maximum(np.cos(fo * np.pi / 2), 1e-4))
    return g


def music_bed(path, v, voice_lufs, offset=None):
    m, sr = sf.read(path, dtype="float32", always_2d=True)
    if sr != SR:
        m = resample_poly(m, SR, sr, axis=0).astype(np.float32)
    if m.shape[1] == 1:
        m = np.repeat(m, 2, 1)
    m = m[:, :2]
    meta = {}
    if offset is None:
        # back-time so the track's own ending lands on the reel's last frame when
        # it is long enough; otherwise start from the top
        offset = max(0.0, len(m) / SR - DURATION)
    meta["offset"] = offset
    i0 = round(offset * SR)
    m = m[i0:i0 + N]
    if len(m) < N:
        m = np.pad(m, ((0, N - len(m)), (0, 0)))
    meter = pyln.Meter(SR)
    m_lufs = meter.integrated_loudness(m)
    # base level 12 LU under the voice, ducked ~4-5 dB more under words -> ~15-17 LU below speech
    m = m * db(voice_lufs - 12 - m_lufs)
    env = voice_env(v)
    duck = db(-4.5 * env)
    m = m * (duck * db(automation(N)))[:, None]
    fi = round(0.05 * SR)
    m[:fi] *= np.linspace(0, 1, fi)[:, None]
    meta["music_lufs_raw"] = float(m_lufs)
    return m, meta


# ------------------------------------------------------------------ master
def true_peak_db(x):
    up = resample_poly(x, 4, 1, axis=0)
    return 20 * np.log10(np.abs(up).max() + 1e-12)


def limiter(x, ceil_db, look=0.005, release=0.06):
    """Look-ahead peak limiter run 4x oversampled (true-peak aware)."""
    up = resample_poly(x, 4, 1, axis=0)
    sr = SR * 4
    peak = np.abs(up).max(1)
    thr = db(ceil_db)
    need = np.minimum(1.0, thr / np.maximum(peak, 1e-9))
    w = round(look * sr)
    g = minimum_filter1d(need, size=2 * w + 1, mode="nearest")
    a = np.exp(-1 / (release * sr))
    g = lfilter([1 - a], [1, -a], g - 1) + 1  # smooth recovery
    g = np.minimum(g, minimum_filter1d(need, size=2 * w + 1, mode="nearest"))
    y = up * g[:, None]
    return resample_poly(y, 1, 4, axis=0).astype(np.float32)


def master(x):
    meter = pyln.Meter(SR)
    for _ in range(4):
        L = meter.integrated_loudness(x)
        x = x * db(TARGET_LUFS - L)
        if true_peak_db(x) > TP_CEIL:
            x = limiter(x, TP_CEIL - 0.3)
    L = meter.integrated_loudness(x)
    return x, L, true_peak_db(x)


def ffmpeg_measure(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    summ = r[r.rfind("Summary:"):]
    I = float(summ.split("I:")[1].split("LUFS")[0])
    tp = float(summ.split("Peak:")[1].split("dBFS")[0])
    return I, tp


def main():
    v = cut_voice(process_voice())
    meter = pyln.Meter(SR)
    v_st = np.stack([v, v], 1)
    voice_lufs = meter.integrated_loudness(v_st)
    voice_peak = 20 * np.log10(np.abs(v).max())
    sfx = build_sfx(voice_peak)
    report = {"voice_lufs_pre": float(voice_lufs), "voice_peak_pre": float(voice_peak)}

    mixes = {"nomusic": v_st + sfx}
    tracks = sorted(glob.glob("music/*.wav") + glob.glob("music/*.mp3") + glob.glob("music/*.flac")
                    + glob.glob("music/*.m4a") + glob.glob("music/*.ogg"))
    if tracks:
        if not tracks[0].endswith((".wav", ".flac", ".ogg")):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tracks[0], "-ar", str(SR), "-ac", "2",
                            "work/music_src.wav"], check=True)
            mpath = "work/music_src.wav"
        else:
            mpath = tracks[0]
        offset = json.load(open("work/music_offset.json"))["offset"] if glob.glob("work/music_offset.json") else None
        m, meta = music_bed(mpath, v, voice_lufs, offset)
        report.update(music=tracks[0], **meta)
        mixes["final"] = v_st + sfx + m
        sf.write("work/music_bed.wav", m, SR, subtype="FLOAT")

    sf.write("work/voice_cut.wav", v, SR, subtype="FLOAT")
    sf.write("work/sfx.wav", sfx, SR, subtype="FLOAT")
    for name, x in mixes.items():
        y, L, tp = master(x)
        path = f"work/mix_{name}.wav"
        sf.write(path, y, SR, subtype="PCM_24")
        fI, ftp = ffmpeg_measure(path)
        report[name] = dict(lufs=round(float(L), 2), true_peak=round(float(tp), 2), ffmpeg_I=fI, ffmpeg_TP=ftp)
        print(f"{name}: {L:.2f} LUFS, TP {tp:.2f} dBTP (ffmpeg: I {fI} LUFS, TP {ftp} dBTP)")
    json.dump(report, open("work/audio_report.json", "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
