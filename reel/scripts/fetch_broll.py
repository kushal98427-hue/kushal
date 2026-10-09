"""Find, rank and download the B-roll from the Pexels Videos API.

  python3 scripts/fetch_broll.py search     # query Pexels, keep viable portrait HD candidates
  python3 scripts/fetch_broll.py analyze    # download small renditions, score them, build broll_candidates.jpg
  python3 scripts/fetch_broll.py download   # fetch the chosen HD files into work/broll_full/, write credits.txt
  python3 scripts/fetch_broll.py archive    # trim each chosen clip at its in-point into broll/ (committed)

The key is read from $PEXELS_API_KEY or from PEXELS_API_KEY in .env.
work/broll_choice.json ({"<slot>": <pexels video id>}) overrides the automatic pick.
broll_inpoints.json ({"<slot>": {"start": s, "xoff": -1..1}}) sets where each cutaway
starts in the full clip and the horizontal crop offset; `archive` trims at "start".
"""
import glob
import json
import os
import subprocess
import sys
import time
from fractions import Fraction

import cv2
import numpy as np
import requests

sys.path.insert(0, "scripts")
from timeline import BROLL  # noqa: E402

API = "https://api.pexels.com/videos/search"
CAND_DIR = "work/candidates"  # downloaded third-party media: data only, never executed
os.makedirs(CAND_DIR, exist_ok=True)
os.makedirs("broll", exist_ok=True)
os.makedirs("work/broll_full", exist_ok=True)


def api_key():
    k = os.environ.get("PEXELS_API_KEY")
    if not k and os.path.exists(".env"):
        for line in open(".env"):
            if line.strip().startswith("PEXELS_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        sys.exit("PEXELS_API_KEY is not set (env var or .env)")
    return k


def get(url, **kw):
    for i in range(4):
        try:
            r = requests.get(url, timeout=60, **kw)
            if r.status_code == 429:
                time.sleep(2 ** (i + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == 3:
                raise
            time.sleep(2 ** (i + 1))


def hd_file(v):
    """Best portrait rendition >= 1080 px wide; prefer exactly 1080x1920, then the smallest above it."""
    files = [f for f in v["video_files"] if f.get("width") and f.get("height")
             and f["height"] > f["width"] and f["width"] >= 1080 and f.get("file_type") == "video/mp4"]
    if not files:
        return None
    files.sort(key=lambda f: (f["width"] != 1080, f["width"] * f["height"]))
    return files[0]


def small_file(v):
    files = [f for f in v["video_files"] if f.get("width") and f.get("file_type") == "video/mp4"]
    files.sort(key=lambda f: f["width"] * f["height"])
    ok = [f for f in files if f["width"] >= 360]
    return (ok or files)[0]


def search():
    key = api_key()
    used = set()
    out = {}
    for slot in BROLL:
        need = slot["out"][1] - slot["out"][0] + 0.6
        cands = []
        for qi, q in enumerate(slot["queries"]):
            r = get(API, headers={"Authorization": key},
                    params=dict(query=q, orientation="portrait", size="medium", per_page=15))
            for v in r.json().get("videos", []):
                f = hd_file(v)
                if not f or v["duration"] < need or v["id"] in used or any(c["id"] == v["id"] for c in cands):
                    continue
                cands.append(dict(id=v["id"], query=q, query_rank=qi, url=v["url"], duration=v["duration"],
                                  user=v["user"]["name"], user_url=v["user"]["url"], hd=f, small=small_file(v),
                                  image=v.get("image")))
            if len(cands) >= 12:
                break
        out[str(slot["id"])] = cands
        used.update(c["id"] for c in cands[:3])  # keep the obvious picks distinct across slots
        print(f"slot {slot['id']}: {len(cands)} viable candidates")
    json.dump(out, open("work/pexels_search.json", "w"), indent=1)


# ------------------------------------------------------------------ analysis
_FACE = None


def big_face(bgr):
    """True when a face fills >12 % of the frame width — likely someone on camera."""
    global _FACE
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    if _FACE is None:
        _FACE = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path="work/models/face_landmarker.task"), num_faces=3))
    res = _FACE.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    for f in res.face_landmarks:
        xs = [q.x for q in f]
        if max(xs) - min(xs) > 0.12:
            return True
    return False


STUDIO = dict(luma50=0.06, warm=0.03)  # measured on raw.mp4


def analyse_clip(path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frames = []
    while len(frames) < int(fps * 3):
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    if len(frames) < fps:
        return None
    g = [cv2.cvtColor(cv2.resize(f, (180, 320)), cv2.COLOR_BGR2GRAY) for f in frames]
    flow = []
    for a, b in zip(g[:int(fps * 2)], g[1:int(fps * 2)]):
        fl = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        flow.append(np.linalg.norm(fl, axis=2).mean())
    rgb = np.stack([cv2.cvtColor(cv2.resize(f, (180, 320)), cv2.COLOR_BGR2RGB) for f in frames[::5]]).astype(np.float32) / 255
    L = rgb @ np.float32([0.2126, 0.7152, 0.0722])
    picks = frames[:: max(1, len(frames) // 6)][:6]
    faces = sum(big_face(cv2.resize(f, (360, 640))) for f in picks)
    return dict(fps=fps, motion=float(np.median(flow)), luma50=float(np.median(L)),
                luma95=float(np.percentile(L, 95)), warm=float((rgb[..., 0] - rgb[..., 2]).mean()),
                big_face_ratio=faces / 6.0, thumbs=[frames[i] for i in (0, len(frames) // 2, len(frames) - 1)])


def score(c, m):
    s = 0.0
    s += 1.0 - 0.25 * c["query_rank"]                       # earlier queries match the line best
    s += min(m["motion"], 2.0) * 0.6 if m["motion"] > 0.15 else -1.0  # clear motion in the first 2 s
    s -= abs(np.log((m["luma50"] + 0.02) / 0.14)) * 0.35      # dark/moody preferred
    s += 0.3 if m["warm"] > 0.0 else 0.0                     # warm-lit preferred
    s -= 1.5 * m["big_face_ratio"]                           # nobody talking to camera
    return float(s)


def analyze():
    data = json.load(open("work/pexels_search.json"))
    report = {}
    for slot in BROLL:
        sid = str(slot["id"])
        rows = []
        for c in data[sid][:10]:
            p = f"{CAND_DIR}/{c['id']}_small.mp4"
            if not os.path.exists(p):
                open(p, "wb").write(get(c["small"]["link"]).content)
            m = analyse_clip(p)
            if not m:
                continue
            thumbs = m.pop("thumbs")
            for k, im in enumerate(thumbs):
                cv2.imwrite(f"{CAND_DIR}/{c['id']}_t{k}.jpg", cv2.resize(im, (216, 384)))
            rows.append(dict(c, metrics=m, score=score(c, m)))
        rows.sort(key=lambda r: -r["score"])
        report[sid] = rows
        print(f"slot {sid}: " + ", ".join(f"{r['id']}({r['score']:.2f})" for r in rows[:3]))
    # automatic pick: best score, no clip/creator reused across slots
    choice = json.load(open("work/broll_choice.json")) if os.path.exists("work/broll_choice.json") else {}
    used_ids, used_users = set(), set()
    for slot in BROLL:
        sid = str(slot["id"])
        if sid in choice:
            pick = next(r for r in report[sid] if r["id"] == choice[sid])
        else:
            pick = next((r for r in report[sid] if r["id"] not in used_ids and r["user"] not in used_users),
                        report[sid][0])
        choice[sid] = pick["id"]
        used_ids.add(pick["id"])
        used_users.add(pick["user"])
    json.dump(choice, open("work/broll_choice.json", "w"), indent=1)
    json.dump(report, open("work/broll_candidates.json", "w"), indent=1, default=str)
    contact_sheet(report, choice)


def contact_sheet(report, choice):
    """Top 3 per slot (3 frames each), chosen one framed in gold."""
    rows = []
    for slot in BROLL:
        sid = str(slot["id"])
        tiles = []
        top = report[sid][:3]
        if choice[sid] not in [r["id"] for r in top]:
            top = [next(r for r in report[sid] if r["id"] == choice[sid])] + top[:2]
        for r in top:
            ims = [cv2.imread(f"{CAND_DIR}/{r['id']}_t{k}.jpg") for k in range(3)]
            tile = np.hstack(ims)
            chosen = r["id"] == choice[sid]
            col = (77, 194, 255) if chosen else (60, 60, 60)
            tile = cv2.copyMakeBorder(tile, 34, 6, 6, 6, cv2.BORDER_CONSTANT, value=col)
            label = f"#{sid} {r['id']} {r['query'][:22]} s={r['score']:.1f}" + ("  CHOSEN" if chosen else "")
            cv2.putText(tile, label, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0) if chosen else (230, 230, 230), 2,
                        cv2.LINE_AA)
            tiles.append(tile)
        while len(tiles) < 3:
            tiles.append(np.zeros_like(tiles[0]))
        rows.append(np.hstack(tiles))
    cv2.imwrite("broll_candidates.jpg", np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print("wrote broll_candidates.jpg")


def download():
    report = json.load(open("work/broll_candidates.json"))
    choice = json.load(open("work/broll_choice.json"))
    lines = ["B-roll footage — Pexels (free to use, attribution not required; credited anyway)", ""]
    for slot in BROLL:
        sid = str(slot["id"])
        r = next(x for x in report[sid] if x["id"] == choice[sid])
        dst = f"work/broll_full/slot{sid}_{r['id']}.mp4"
        if not os.path.exists(dst):
            tmp = f"{CAND_DIR}/{r['id']}_hd.mp4"
            open(tmp, "wb").write(get(r["hd"]["link"]).content)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-an", "-c:v", "copy", dst], check=True)  # mute
        a, b = slot["out"]
        lines.append(f"Slot {sid} ({a:.2f}-{b:.2f}s, \"{slot['line']}\"): {r['url']} — video by {r['user']} "
                     f"({r['user_url']}) — {r['hd']['width']}x{r['hd']['height']}")
        print("downloaded", dst)
    lines += ["", "Fonts: Noto Sans Devanagari, Poppins — SIL Open Font License (google/fonts)."]
    open("credits.txt", "w").write("\n".join(lines) + "\n")


def archive():
    """Keep only the part of each chosen clip the edit uses (+0.5 s), scaled to
    cover 1080x1920 and muted, so the reel can be re-rendered without Pexels."""
    from timeline import FPS
    inpoints = json.load(open("broll_inpoints.json")) if os.path.exists("broll_inpoints.json") else {}
    for slot in BROLL:
        sid = str(slot["id"])
        full = sorted(glob.glob(f"work/broll_full/slot{sid}_*.mp4"))
        if not full:
            print(f"slot {sid}: nothing downloaded")
            continue
        src = full[0]
        fps = float(Fraction(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                             "stream=r_frame_rate", "-of", "csv=p=0", src],
                                            capture_output=True, text=True).stdout.strip()))
        n = round((slot["out"][1] - slot["out"][0]) * FPS)
        need = n * (2 if fps > 45 else 1) / fps + 0.5
        start = inpoints.get(sid, {}).get("start", 0.2)
        for old in glob.glob(f"broll/slot{sid}_*.mp4"):
            os.remove(old)
        dst = f"broll/{os.path.basename(src)}"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", src, "-t", f"{need:.3f}", "-an",
                        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", dst], check=True)
        print(f"slot {sid}: {dst} ({start:.2f}s +{need:.2f}s @ {fps:g} fps)")


if __name__ == "__main__":
    {"search": search, "analyze": analyze, "download": download, "archive": archive}[sys.argv[1]]()
