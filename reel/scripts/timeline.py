"""Single source of truth for the edit: cuts, source->output remap, captions,
B-roll slots, face framing keyframes and SFX cues.

All "src" times are seconds in raw.mp4; all "out" times are seconds in the
final reel. Source and output are both 25 fps, and every cut point is on a
frame boundary, so a src frame maps 1:1 to an out frame.
"""
FPS = 25
W, H = 1080, 1920
SRC_W, SRC_H = 512, 768
HOLD = 0.8  # freeze the last frame at the end

# Kept source ranges. Every edge sits in silence (checked against the RMS
# envelope; see edit_report.md). 23.28 -> 23.32 trims the tail of an inhale.
SEGMENTS = [(0.00, 1.80), (2.04, 5.92), (6.76, 9.48), (9.80, 16.68), (17.00, 22.80), (23.32, 27.44)]


def _seg_out_starts():
    t, starts = 0.0, []
    for a, b in SEGMENTS:
        starts.append(t)
        t += b - a
    return starts, t


SEG_OUT, CUT_LEN = _seg_out_starts()
DURATION = round(CUT_LEN + HOLD, 3)
N_FRAMES = round(DURATION * FPS)


def src_to_out(t):
    """Map a source time to output time (snaps into the nearest kept segment)."""
    for (a, b), o in zip(SEGMENTS, SEG_OUT):
        if a - 1e-6 <= t <= b + 1e-6:
            return round(o + (t - a), 4)
    # in a removed gap: snap to the start of the next kept segment
    for (a, b), o in zip(SEGMENTS, SEG_OUT):
        if t < a:
            return round(o, 4)
    return round(CUT_LEN, 4)


def out_frame_to_src_frame(n):
    """Output frame index -> source frame index (last frame held at the end)."""
    t = n / FPS
    for (a, b), o in zip(SEGMENTS, SEG_OUT):
        if o - 1e-6 <= t < o + (b - a) - 1e-6:
            return round((a + (t - o)) * FPS)
    return round(SEGMENTS[-1][1] * FPS) - 1


# ---------------------------------------------------------------- captions
# (src onset, text, highlight words, emphasis). Onsets are the reference
# timings corrected (<= 0.2 s) to the measured word onsets in the audio.
CAPTIONS = [
    (0.07, "तपाईंले कहिल्यै", [], False),
    (0.99, "सोच्नुभएको छ?", [], False),
    (2.21, "एउटा कम्प्युटरले", [], False),
    (3.12, "तपाईंको काम", [], False),
    (3.95, "केही सेकेन्डमै", ["सेकेन्डमै"], True),
    (4.63, "गरिदियो भने", [], False),
    (5.38, "कस्तो लाग्ला??", [], False),
    (6.91, "अहिले AI ले", ["AI"], False),
    (7.90, "ठ्याक्कै यही", [], False),
    (8.70, "गरिरहेको छ।", [], False),
    (9.95, "टेक्स्ट लेख्ने,", [], False),
    (10.89, "फोटो बनाउने,", [], False),
    (12.01, "भिडियो तयार गर्ने", [], False),
    (13.42, "यी सबै काम", [], False),
    (14.22, "AI ले अहिले निकै", [], False),
    (15.35, "सजिलो बनाइदिएको छ।", ["सजिलो"], False),
    (17.13, "त्यसैले", [], False),
    (17.96, "आजको समयमा", [], False),
    (19.24, "AI सिक्नु भनेको", [], False),
    (20.55, "आफूलाई", [], False),
    (21.16, "एक कदम अगाडि", ["एक", "कदम", "अगाडि"], True),
    (22.09, "लैजानु हो।", [], False),
    (23.41, "यदि तपाईं पनि", [], False),
    (24.19, "AI सिक्न", [], False),
    (24.86, "चाहनुहुन्छ भने", [], False),
    (25.93, "मलाई मेसेज", ["मेसेज"], True),
    (26.56, "गर्न सक्नुहुन्छ।", [], False),
]
CAPTION_LEAD = 0.04  # show each chunk one frame before its first word

SCRIPT = """तपाईंले कहिल्यै सोच्नुभएको छ?
एउटा कम्प्युटरले तपाईंको काम केही सेकेन्डमै गरिदियो भने कस्तो लाग्ला??
अहिले AI ले ठ्याक्कै यही गरिरहेको छ।
टेक्स्ट लेख्ने, फोटो बनाउने, भिडियो तयार गर्ने यी सबै काम AI ले अहिले निकै सजिलो बनाइदिएको छ।
त्यसैले आजको समयमा AI सिक्नु भनेको आफूलाई एक कदम अगाडि लैजानु हो।
यदि तपाईं पनि AI सिक्न चाहनुहुन्छ भने मलाई मेसेज गर्न सक्नुहुन्छ।"""


def visual_cuts():
    cuts = set(round(s, 3) for s in SEG_OUT[1:])
    for b in BROLL:
        cuts.update(round(x, 3) for x in b["out"])
    return sorted(cuts)


def caption_start(src_t):
    """Chunk appears one frame before its first word, or on a visual cut that
    falls just before the word (lead <= 0.15 s) so text changes with the picture."""
    onset = src_to_out(src_t)
    near = [c for c in visual_cuts() if onset - 0.15 - 1e-6 <= c <= onset + 0.02]
    if near:
        return min(near, key=lambda c: abs(c - (onset - CAPTION_LEAD)))
    return max(0.0, onset - CAPTION_LEAD)


def caption_events():
    """[(out_start, out_end, text, highlights, emphasis)] — chunks butt together."""
    starts = [caption_start(t) for t, *_ in CAPTIONS]
    ev = []
    for k, (t, text, hl, emph) in enumerate(CAPTIONS):
        end = starts[k + 1] if k + 1 < len(CAPTIONS) else DURATION
        ev.append((round(starts[k], 3), round(end, 3), text, hl, emph))
    return ev


# ---------------------------------------------------------------- B-roll
# Slot boundaries are frame-aligned src times on word boundaries. Slots 1 and 3
# start exactly on the jump cut so no 4-5 frame face flash is left before them.
BROLL = [
    dict(id=1, src=(2.04, 4.60), line="एउटा कम्प्युटरले … केही सेकेन्डमै",
         queries=["typing on laptop", "hands typing keyboard night", "fast typing"]),
    dict(id=2, src=(7.24, 8.68), line="अहिले AI ले ठ्याक्कै यही",
         queries=["artificial intelligence", "robot hand", "digital brain", "futuristic technology"]),
    dict(id=3, src=(9.80, 10.88), line="टेक्स्ट लेख्ने",
         queries=["writing on laptop", "typing message laptop", "chatbot"]),
    dict(id=4, src=(10.88, 11.96), line="फोटो बनाउने",
         queries=["photo editing", "graphic designer tablet", "editing photos computer"]),
    dict(id=5, src=(11.96, 13.36), line="भिडियो तयार गर्ने",
         queries=["video editing", "video editor timeline", "editing video computer"]),
    dict(id=6, src=(17.88, 19.52), line="आजको समयमा AI",
         queries=["student studying laptop", "young man learning online", "studying at night laptop"]),
    dict(id=7, src=(20.48, 22.08), line="आफूलाई एक कदम अगाडि",
         queries=["walking up stairs", "climbing stairs", "stepping up stairs"]),
]
for _b in BROLL:
    _b["out"] = (src_to_out(_b["src"][0]), src_to_out(_b["src"][1]))

# ---------------------------------------------------------------- framing
# Face runs = output spans where the avatar is on screen, with a zoom ramp
# (smoothstep). Adjacent runs across a jump cut always change framing.
CLOSE, WIDE, CTA = (1.10, 1.14), (1.00, 1.04), (1.02, 1.08)


def face_runs():
    spans, t = [], 0.0
    cuts = sorted([b["out"] for b in BROLL])
    for a, b in cuts:
        if a - t > 1e-6:
            spans.append([t, a])
        t = b
    spans.append([t, DURATION])
    # split spans at jump cuts (segment starts) that fall inside them
    out = []
    for a, b in spans:
        pts = [a] + [s for s in SEG_OUT if a + 1e-6 < s < b - 1e-6] + [b]
        out += [[pts[i], pts[i + 1]] for i in range(len(pts) - 1)]
    return out


def framing_plan():
    runs = face_runs()
    plan = []
    n = len(runs)
    for k, (a, b) in enumerate(runs):
        if k == 0:
            z = CLOSE  # hook
        elif k == n - 1:
            z = CTA
        else:
            # alternate backwards from the CTA so the run before it is close
            z = CLOSE if (n - 1 - k) % 2 == 1 else WIDE
        plan.append(dict(out=(round(a, 3), round(b, 3)), zoom=z))
    return plan


# ---------------------------------------------------------------- sound cues
WHOOSH_AT = [BROLL[0]["out"][0], BROLL[1]["out"][0], BROLL[2]["out"][0], BROLL[5]["out"][0]]
RISER_END = src_to_out(21.16)  # onset of "एक कदम अगाडि"
POP_AT = src_to_out(26.13)  # onset of "मेसेज"
# music automation (out seconds)
BREAKDOWN = (src_to_out(17.00), src_to_out(21.16))  # "त्यसैले आजको समयमा …" → lift at "एक कदम"

if __name__ == "__main__":
    print(f"cut length {CUT_LEN:.2f}s, final {DURATION:.2f}s, {N_FRAMES} frames")
    for (a, b), o in zip(SEGMENTS, SEG_OUT):
        print(f"  seg src {a:5.2f}-{b:5.2f} -> out {o:5.2f}-{o + b - a:5.2f}")
    print("B-roll:")
    for b in BROLL:
        print(f"  #{b['id']} src {b['src'][0]:5.2f}-{b['src'][1]:5.2f} -> out {b['out'][0]:5.2f}-{b['out'][1]:5.2f} "
              f"({b['out'][1] - b['out'][0]:.2f}s) {b['line']}")
    print("Face runs:")
    for r in framing_plan():
        print(f"  out {r['out'][0]:5.2f}-{r['out'][1]:5.2f} ({r['out'][1] - r['out'][0]:.2f}s) zoom {r['zoom']}")
    print("Captions:")
    for s, e, t, hl, em in caption_events():
        print(f"  {s:5.2f}-{e:5.2f} {t} {'[' + ','.join(hl) + ']' if hl else ''}{' EMPH' if em else ''}")
    print("whoosh", WHOOSH_AT, "riser->", RISER_END, "pop", POP_AT, "breakdown", BREAKDOWN)
