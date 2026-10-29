"""Throw odd designs at the engine.   python -m tools.fuzz [-n 300] [--seed 0]

Random but schema-valid designs: no logo / headline / product, many texts, empty or huge text, unicode, rotated and
zero-size elements, missing optional fields, unknown assets, negative z, elements already off-canvas, extreme
canvas sizes. Reports crashes, rule errors, slow cases and a summary by cause so each can be fixed.
"""

import argparse
import collections
import random
import time
import traceback

from engine.resize import resize
from engine.rules import check

ASSETS = ["solstice_bg_gradient.png", "solstice_logo_lockup.png", "solstice_bottle.png", "unknown_asset_xyz.png"]
WORDS = "summer sale new fresh taste the light golden hour limited edition shop now free delivery 50% off".split()
TEXTS = ["", " ", "A", "Hello", "Chase the Light", "Supercalifragilisticexpialidocious", "日本語のテキスト", "😀 party 🎉",
         "©2005 Brand", "www.example.com/terms-and-conditions", "8€", "Line one\nLine two"]


def rnd_text(r):
    if r.random() < 0.35:
        return r.choice(TEXTS)
    return " ".join(r.choice(WORDS) for _ in range(r.choice([1, 2, 3, 6, 12, 40, 120])))


def design(seed):
    r = random.Random(seed)
    W, H = r.choice([(1080, 1080), (1080, 1350), (1920, 1080), (400, 300), (3000, 500), (200, 900), (2500, 2500), (640, 480)])
    els, z = [], 0
    n_img, n_txt, n_shape = r.choice([0, 1, 2, 3, 5]), r.choice([0, 1, 2, 4, 8]), r.choice([0, 1, 3, 6])
    if r.random() < 0.7:
        els.append({"id": "bg", "type": "image", "asset_id": r.choice(ASSETS[:3]), "x": 0, "y": 0, "width": W, "height": H,
                    "fit": "cover", "z_index": 0})
    for i in range(n_img):
        w, h = r.randint(20, W), r.randint(20, H)
        e = {"id": f"img{i}", "type": "image", "asset_id": r.choice(ASSETS), "x": r.randint(-50, W), "y": r.randint(-50, H),
             "width": w, "height": h}
        if r.random() < 0.7:
            e["fit"] = r.choice(["contain", "cover"])
        if r.random() < 0.3:
            e["rotation"] = r.choice([-90, -12, 5, 45, 180])
        els.append(e)
    for i in range(n_txt):
        size = r.choice([1, 6, 12, 24, 48, 120, 300])
        e = {"id": f"t{i}", "type": "text", "x": r.randint(-20, W), "y": r.randint(-20, H), "width": r.randint(0, W) or 1,
             "height": r.randint(0, 200), "content": rnd_text(r), "font_family": r.choice(["Solstice Serif", "Solstice Sans", "Comic Neue"]),
             "font_size": size, "color": "rgba(255,255,255,1)"}
        for k, v in (("font_weight", r.choice(["regular", "bold"])), ("font_style", r.choice(["normal", "italic"])),
                     ("text_align", r.choice(["left", "center", "right"])), ("line_height", r.choice([0.8, 1.0, 1.5, 2.0])),
                     ("letter_spacing", r.choice([0, 2, -1, 10])), ("max_lines", r.choice([None, 1, 3])),
                     ("opacity", r.choice([0, 0.1, 0.6, 1])), ("rotation", r.choice([0, 0, 0, -12, 90, 270]))):
            if r.random() < 0.4:
                e[k] = v
        if r.random() < 0.2:
            e["style_runs"] = [{"start": r.randint(0, 5), "end": r.randint(5, 500), "color": "rgba(240,178,66,1)"}]
        els.append(e)
    for i in range(n_shape):
        e = {"id": f"s{i}", "type": "shape", "shape_type": r.choice(["rectangle", "ellipse", "line"]),
             "x": r.randint(-300, W), "y": r.randint(-300, H), "width": r.choice([0, 1, 50, 400, W * 2]),
             "height": r.choice([0, 1, 50, 400, H]), "fill_color": "rgba(232,106,58,1)"}
        if r.random() < 0.5:
            e["corner_radius"] = r.choice([0, 10, 1000])
        if r.random() < 0.4:
            e["opacity"] = r.choice([0.1, 0.5])
        if r.random() < 0.3:
            e["rotation"] = r.choice([-12, 30, 90])
        els.append(e)
    # groups: pair up some shapes and texts, sometimes with odd members
    for e in els:
        if r.random() < 0.15:
            e["group_id"] = r.choice(["g1", "g2"])
        if r.random() < 0.8:
            z += r.choice([0, 1, 1, 2, -1])
            e["z_index"] = z
    if not els:
        els.append({"id": "only", "type": "shape", "shape_type": "rectangle", "x": 0, "y": 0, "width": 10, "height": 10,
                    "fill_color": "rgba(0,0,0,1)"})
    return {"canvas": {"width": W, "height": H}, "elements": els}


TARGETS = [(1080, 1080), (1080, 1920), (728, 90), (300, 250), (160, 600), (1600, 400), (320, 50), (4000, 4000), (50, 50)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    crashes, errs, slow = [], collections.Counter(), []
    examples = {}
    for i in range(a.n):
        seed = a.seed * 100000 + i
        src = design(seed)
        tw, th = random.Random(seed).choice(TARGETS)
        t0 = time.time()
        try:
            out = resize(src, {"width": tw, "height": th})
            probs = [m for s, m in check(src, out) if s == "error"]
        except Exception:
            crashes.append((seed, traceback.format_exc().strip().splitlines()[-1]))
            continue
        dt = time.time() - t0
        if dt > 20:
            slow.append((seed, round(dt, 1)))
        for m in probs:
            key = m.split(":", 1)[1].strip().split("(")[0][:50] if ":" in m else m[:50]
            errs[key] += 1
            examples.setdefault(key, (seed, tw, th, m))
    print(f"{a.n} designs: crashes {len(crashes)}, designs-with-slow-resize {len(slow)}, rule-error kinds {len(errs)}")
    for s, why in crashes[:8]:
        print("  CRASH seed", s, "->", why)
    for k, c in errs.most_common(10):
        print(f"  RULE ERROR x{c}: {k}   e.g. seed {examples[k][0]} -> {examples[k][1]}x{examples[k][2]}: {examples[k][3][:100]}")
    for s, d in slow[:5]:
        print("  SLOW seed", s, d, "s")


if __name__ == "__main__":
    main()
