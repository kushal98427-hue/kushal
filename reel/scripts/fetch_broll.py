"""Find, rank and download the B-roll from the Pixabay Videos API.

  python3 scripts/fetch_broll.py search     # query Pixabay, keep candidates that fill 9:16 at >= 1080 px wide
  python3 scripts/fetch_broll.py analyze    # download small renditions, score them, build broll_candidates.jpg
  python3 scripts/fetch_broll.py download   # fetch the chosen HD files into work/broll_full/, write credits.txt
  python3 scripts/fetch_broll.py archive    # trim each chosen clip at its in-point into broll/ (committed)
  python3 scripts/fetch_broll.py sheet      # rebuild broll_candidates.jpg after editing choice/rejects

The key is read from $PIXABAY_API_KEY or from PIXABAY_API_KEY in .env; it is never
printed or stored (request errors are reported without the URL).
Pixabay has no orientation filter for videos, so orientation is checked here:
portrait renditions >= 1080 px wide are preferred, and landscape ones qualify only
when their centre 9:16 crop is still >= 1080 px wide (i.e. 4K), so nothing is upscaled.
broll_choice.json ({"<slot>": <pixabay video id>}) records the reviewed pick per slot
(the automatic score is only a starting point); slots missing from it are auto-picked.
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

API = "https://pixabay.com/api/videos/"
SEARCH_JSON = "work/pixabay_search.json"
CAND_DIR = "work/candidates"  # downloaded third-party media: data only, never executed
os.makedirs(CAND_DIR, exist_ok=True)
os.makedirs("broll", exist_ok=True)
os.makedirs("work/broll_full", exist_ok=True)


def api_key():
    k = os.environ.get("PIXABAY_API_KEY")
    if not k and os.path.exists(".env"):
        for line in open(".env"):
            if line.strip().startswith("PIXABAY_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        sys.exit("PIXABAY_API_KEY is not set (env var or .env)")
    return k


def get(url, **kw):
    """GET with retries. Errors are re-raised without the URL, which can carry the key."""
    for i in range(4):
        try:
            r = requests.get(url, timeout=120, **kw)
            if r.status_code == 429:  # Pixabay allows 100 requests / 60 s
                time.sleep(2 ** (i + 2))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if i == 3:
                code = getattr(getattr(e, "response", None), "status_code", None)
                raise SystemExit(f"request to {url.split('?')[0]} failed: {type(e).__name__} (HTTP {code})") from None
            time.sleep(2 ** (i + 1))


def crop_w(r):
    """Width of the 9:16 window this rendition yields after scale-to-cover."""
    w, h = r.get("width") or 0, r.get("height") or 0
    return w if w / max(h, 1) <= 9 / 16 else h * 9 / 16


def renditions(v):
    return [dict(link=r["url"], width=r["width"], height=r["height"], size=r.get("size"))
            for r in v["videos"].values() if r.get("url") and r.get("width")]


def hd_file(v):
    """Best rendition >= 1080 px wide (the brief's rule). Prefer one whose 9:16 window is
    already >= 1080 px (portrait, or 4K landscape) so nothing is upscaled; otherwise the
    largest available. Smallest qualifying file wins to keep downloads sane."""
    ok = [r for r in renditions(v) if r["width"] >= 1080]
    if not ok:
        return None
    full = [r for r in ok if crop_w(r) >= 1080]
    if full:
        full.sort(key=lambda r: (r["height"] <= r["width"], r["width"] * r["height"]))
        return full[0]
    return max(ok, key=lambda r: crop_w(r))


def small_file(v):
    """Rendition used for scoring and thumbnails: smallest with a >= 300 px wide 9:16 window."""
    rs = sorted(renditions(v), key=lambda r: r["width"] * r["height"])
    ok = [r for r in rs if crop_w(r) >= 300]
    return ok[0] if ok else rs[-1]


STOP = {"on", "at", "up", "the", "of", "a", "in", "to"}
MAX_POOL = 30   # candidates kept per slot
N_ANALYSE = 16  # scored automatically per slot (plus any reviewed pick beyond that)
CHOICE = "broll_choice.json"
REJECTS = "broll_rejects.json"  # {"<id>": "reason"} — clips the manual review ruled out


def rejects():
    return {int(k): v for k, v in json.load(open(REJECTS)).items()} if os.path.exists(REJECTS) else {}


def _same_word(a, b):
    return a == b or (len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4] and abs(len(a) - len(b)) <= 3)


def relevance(query, tags):
    """Fraction of the query's content words found in the clip's tags. Pixabay matches
    any single word, so this is what keeps 'photo editing' from returning skylines."""
    words = [w for w in query.lower().split() if w not in STOP]
    tag_words = {t for tag in tags.lower().split(",") for t in tag.strip().split()}
    hit = sum(any(_same_word(w, t) for t in tag_words) for w in words)
    return hit / len(words), len(words) - hit


def search():
    key = api_key()
    out = {}
    for slot in BROLL:
        need = slot["out"][1] - slot["out"][0] + 0.6
        cands, half, seen = {}, {}, 0
        for qi, q in enumerate(slot["queries"]):  # every query, in the brief's order
            # no orientation filter on Pixabay videos -> fetch more and filter here
            r = get(API, params=dict(key=key, q=q, video_type="film", safesearch="true", per_page=100))
            hits = r.json().get("hits", [])
            seen += len(hits)
            for rank, v in enumerate(hits):
                f = hd_file(v)
                if not f or v.get("isAiGenerated") or v.get("isLowQuality") or v["duration"] < need:
                    continue
                rel, missing = relevance(q, v.get("tags", ""))
                strict = missing <= (1 if len(q.split()) >= 3 else 0)
                if rel < 0.5 or v["id"] in cands or (v["id"] in half and not strict):
                    continue
                half.pop(v["id"], None)  # a later query matched it fully: promote
                (cands if strict else half)[v["id"]] = dict(id=v["id"], query=q, query_rank=qi, api_rank=rank, rel=rel, url=v["pageURL"],
                                      duration=v["duration"], user=v["user"],
                                      user_url=v.get("userURL") or f"https://pixabay.com/users/{v['user_id']}/",
                                      tags=v.get("tags", ""), portrait=f["height"] > f["width"],
                                      upscale=round(1080 / crop_w(f), 2), hd=f, small=small_file(v))
        ranked = sorted(cands.values(), key=lambda c: (c["query_rank"], -c["rel"], c["api_rank"]))
        if len(ranked) < 8:
            # thin slot: add clips matching half the words of a query (still the brief's queries)
            ranked += sorted(half.values(), key=lambda c: (c["query_rank"], c["api_rank"]))
        out[str(slot["id"])] = ranked[:MAX_POOL]
        npor = sum(c["portrait"] for c in ranked)
        nup = sum(c["upscale"] > 1.0 for c in ranked)
        print(f"slot {slot['id']}: {seen} hits -> {len(cands)} on-topic, {len(half)} half-matches "
              f"({npor} portrait, {nup} need upscaling); keeping {len(out[str(slot['id'])])}")
    json.dump(out, open(SEARCH_JSON, "w"), indent=1)


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


def to_916(f):
    """Centre 9:16 window — what scale-to-cover will show of a landscape clip."""
    h, w = f.shape[:2]
    cw = int(round(h * 9 / 16))
    if cw >= w:
        return f
    x0 = (w - cw) // 2
    return f[:, x0:x0 + cw]


def analyse_clip(path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frames = []
    while len(frames) < int(fps * 3):
        ok, f = cap.read()
        if not ok:
            break
        frames.append(to_916(f))
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
    s += 1.0 * c.get("rel", 0)                               # tags really match the query
    s += 0.3 if c.get("portrait") else -0.25 * max(0.0, c.get("upscale", 1.0) - 1.0)  # native 9:16 > upscaled crop
    s += min(m["motion"], 2.0) * 0.6 if m["motion"] > 0.15 else -1.0  # clear motion in the first 2 s
    s -= abs(np.log((m["luma50"] + 0.02) / 0.14)) * 0.35      # dark/moody preferred
    s += 0.3 if m["warm"] > 0.0 else 0.0                     # warm-lit preferred
    s -= 1.5 * m["big_face_ratio"]                           # nobody talking to camera
    return float(s)


def analyze():
    data = json.load(open(SEARCH_JSON))
    choice = json.load(open(CHOICE)) if os.path.exists(CHOICE) else {}
    report = {}
    for slot in BROLL:
        sid = str(slot["id"])
        rows = []
        pool = data[sid][:N_ANALYSE] + [c for c in data[sid][N_ANALYSE:] if c["id"] == choice.get(sid)]
        for c in pool:
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
    # reviewed picks win; the rest: best score, no clip/creator reused across slots
    used_ids = {v for v in choice.values()}
    used_users = {r["user"] for sid, rows in report.items() for r in rows if r["id"] == choice.get(sid)}
    for slot in BROLL:
        sid = str(slot["id"])
        if sid in choice:
            pick = next((r for r in report[sid] if r["id"] == choice[sid]), None)
            if pick is None:
                sys.exit(f"slot {sid}: reviewed pick {choice[sid]} is not in the search results")
        else:
            bad = rejects()
            pick = next((r for r in report[sid] if r["id"] not in used_ids and r["user"] not in used_users
                         and r["id"] not in bad), report[sid][0])
        choice[sid] = pick["id"]
        used_ids.add(pick["id"])
        used_users.add(pick["user"])
    json.dump(choice, open(CHOICE, "w"), indent=1)
    json.dump(report, open("work/broll_candidates.json", "w"), indent=1, default=str)
    contact_sheet(report, choice)


def framed_thumbs(path, start, dur, xoff):
    """First/middle/last frame of the cutaway as the edit will show it (in-point + crop offset)."""
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    ims = []
    for t in (start, start + dur / 2, start + dur):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, f = cap.read()
        h, w = f.shape[:2]
        cw = min(w, int(round(h * 9 / 16)))
        x0 = int((w - cw) / 2 * (1 + xoff))
        ims.append(cv2.resize(f[:, x0:x0 + cw], (216, 384)))
    return ims


def contact_sheet(report, choice):
    """Per slot: the reviewed pick (gold, framed as edited) + the two best-scoring alternatives
    that are not used elsewhere and not ruled out in broll_rejects.json."""
    inpoints = json.load(open("broll_inpoints.json")) if os.path.exists("broll_inpoints.json") else {}
    rows = []
    for slot in BROLL:
        sid = str(slot["id"])
        tiles = []
        pick = next(r for r in report[sid] if r["id"] == choice[sid])
        taken, bad = set(choice.values()), rejects()
        top = [pick] + [r for r in report[sid] if r["id"] not in taken and r["id"] not in bad][:2]
        for r in top:
            if r is pick:
                ip = inpoints.get(sid, {})
                ims = framed_thumbs(f"{CAND_DIR}/{r['id']}_small.mp4", ip.get("start", 0.2),
                                    slot["out"][1] - slot["out"][0], ip.get("xoff", 0.0))
            else:
                ims = [cv2.imread(f"{CAND_DIR}/{r['id']}_t{k}.jpg") for k in range(3)]
            tile = np.hstack(ims)
            chosen = r["id"] == choice[sid]
            col = (77, 194, 255) if chosen else (60, 60, 60)
            tile = cv2.copyMakeBorder(tile, 34, 6, 6, 6, cv2.BORDER_CONSTANT, value=col)
            fmt = "P" if r.get("portrait") else ("L4K" if r.get("upscale", 1) <= 1.0 else f"Lx{r['upscale']:.1f}")
            label = (f"#{sid} {r['id']} {fmt} {r['query'][:18]} s={r['score']:.1f}"
                     + ("  CHOSEN" if chosen else ""))
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
    choice = json.load(open(CHOICE))
    lines = ["B-roll footage — Pixabay (Pixabay Content License: free to use, attribution not required;"
             " credited anyway)", ""]
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
    """Keep only the part of each chosen clip the edit uses (+0.5 s), scaled to cover
    and cropped to 1080x1920 at its xoff, muted, so the reel re-renders without the API.
    (prep_broll's crop is then a no-op on these files.)"""
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
        xoff = inpoints.get(sid, {}).get("xoff", 0.0)
        for old in glob.glob(f"broll/slot{sid}_*.mp4"):
            os.remove(old)
        dst = f"broll/{os.path.basename(src)}"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", src, "-t", f"{need:.3f}", "-an",
                        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
                               f"crop=1080:1920:(iw-1080)/2*(1+{xoff}):(ih-1920)/2",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", dst], check=True)
        print(f"slot {sid}: {dst} ({start:.2f}s +{need:.2f}s @ {fps:g} fps, xoff {xoff:+.2f})")


def sheet():
    """Rebuild broll_candidates.jpg from the last analysis (after editing choice/rejects)."""
    contact_sheet(json.load(open("work/broll_candidates.json")), json.load(open(CHOICE)))


if __name__ == "__main__":
    {"search": search, "analyze": analyze, "download": download, "archive": archive,
     "sheet": sheet}[sys.argv[1]]()
