"""Generate the Devanagari caption track (ASS, rendered by libass).

  python3 scripts/captions.py            -> work/captions.ass (the reel)
  python3 scripts/captions.py --sheet    -> work/caption_sheet.ass (all chunks stacked, for a shaping check)
"""
import sys

sys.path.insert(0, "scripts")
from timeline import DURATION, H, W, caption_events  # noqa: E402

FONT = "Noto Sans Devanagari"
FONT_FILE = "fonts/NotoSansDevanagari-Bold.ttf"


def _em_to_fs():
    """libass sizes text by usWinAscent+usWinDescent, which is 1.9 em for this
    font; convert so the brief's 86/96 px are true em sizes."""
    from fontTools.ttLib import TTFont
    f = TTFont(FONT_FILE)
    return (f["OS/2"].usWinAscent + f["OS/2"].usWinDescent) / f["head"].unitsPerEm


EM = _em_to_fs()
SIZE, SIZE_EMPH = round(86 * EM), round(96 * EM)
Y = 1250  # caption centre (below the chin, above the Reels UI zone)
GOLD = "&H4DC2FF&"  # #FFC24D in ASS BGR
WHITE = "&HFFFFFF&"
POP_MS = 150
RISE = 12
MAX_W = 960  # 60 px side margins; wider chunks get squeezed horizontally


def ts(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def body(text, highlights):
    out = []
    for w in text.split(" "):
        core = w.rstrip(",?।")
        tail = w[len(core):]
        if core in highlights:
            out.append(f"{{\\1c{GOLD}}}{core}{{\\1c{WHITE}}}{tail}")
        else:
            out.append(w)
    return " ".join(out)


HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT},{SIZE},&H00FFFFFF,&H00FFFFFF,&H30101010,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,5,60,60,0,1
Style: Shadow,{FONT},{SIZE},&H90000000,&H90000000,&H90000000,&H00000000,-1,0,0,0,100,100,0,0,1,7,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def event_lines(start, end, text, hl, emph, y=Y, squeeze=100, animate=True):
    size = SIZE_EMPH if emph else SIZE
    x = W // 2
    sx = round(squeeze)
    if animate:
        anim = (f"\\fscx{round(sx * .92)}\\fscy92\\t(0,{POP_MS},0.6,\\fscx{sx}\\fscy100)"
                f"\\fad({POP_MS},0)")
        pos_main = f"\\move({x},{y + RISE},{x},{y},0,{POP_MS})"
        pos_sh = f"\\move({x},{y + RISE + 6},{x},{y + 6},0,{POP_MS})"
    else:
        anim = f"\\fscx{sx}"
        pos_main = f"\\pos({x},{y})"
        pos_sh = f"\\pos({x},{y + 6})"
    plain = text
    return [
        f"Dialogue: 0,{ts(start)},{ts(end)},Shadow,,0,0,0,,{{\\fs{size}{pos_sh}{anim}\\blur9}}{plain}",
        f"Dialogue: 1,{ts(start)},{ts(end)},Cap,,0,0,0,,{{\\fs{size}{pos_main}{anim}\\blur0.6}}{body(text, hl)}",
    ]


def load_widths():
    try:
        import json
        return json.load(open("work/caption_widths.json"))
    except FileNotFoundError:
        return {}


def build(path="work/captions.ass"):
    widths = load_widths()
    lines = []
    for s, e, text, hl, emph in caption_events():
        w = widths.get(text)
        squeeze = min(100, 100 * MAX_W / w) if w else 100
        lines += event_lines(s, e, text, hl, emph, squeeze=squeeze)
    open(path, "w").write(HEADER + "\n".join(lines) + "\n")
    return path


def build_sheet(path="work/caption_sheet.ass"):
    """Each chunk on its own frame (1 s each) at the real position, no animation,
    so widths and shaping can be measured frame by frame."""
    lines = []
    for k, (s, e, text, hl, emph) in enumerate(caption_events()):
        lines += event_lines(k, k + 1, text, hl, emph, animate=False)
    open(path, "w").write(HEADER + "\n".join(lines) + "\n")
    return path


if __name__ == "__main__":
    if "--sheet" in sys.argv:
        print(build_sheet())
    else:
        print(build(), DURATION)
