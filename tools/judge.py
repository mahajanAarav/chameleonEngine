"""Dev-only pairwise judge helper (never shipped).

    python -m tools.judge make --a safety --b baseline -n 12 --out /tmp/judge1
    # then have Claude subagents view /tmp/judge1/pair_*.png and write picks.json (see PROMPT.md)
    python -m tools.judge tally --out /tmp/judge1

`make` renders both engines on the same cases and writes side-by-side images with
the A/B order randomised; the answer key and code scores stay in key.json.
`tally` reports win rate and how often the code score agrees with the judge,
which is the signal for calibrating tools/metrics.py weights.
"""

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

from tools.report import cases, load_engine
from tools.metrics import metrics

PROMPT = """You are judging resized ad designs. Each image pair_NN.png shows two versions of the SAME ad
resized to a new shape: the left half is labelled A, the right half is labelled B.
Pick the better design. Judge like a senior designer, using these criteria:
1. No unwanted collisions (text over text, text over the product or busy areas).
2. Everything readable: sensible size and contrast, nothing cut off or running off the canvas.
3. On brand: colours, fonts and logo intact and in proportion; nothing stretched or distorted.
4. Looks intentional: alignment, even spacing, clear hierarchy, images in good proportion,
   good use of the canvas (not a tiny cluster in an empty space).
Write ONE JSON file {out}/picks.json mapping each pair name to {{"pick": "A" or "B", "why": "<10 words"}},
e.g. {{"pair_00": {{"pick": "B", "why": "text readable, no overlap"}}}}. No ties: always choose.
Do not read key.json or any other file in this folder; it would spoil the blind comparison.
"""


def _render(design, path):
    from renderer.converter.convert import render_design_to_png
    render_design_to_png(design, Path("brand_kit/assets"), path)
    return Image.open(path).convert("RGB")


def make(a_name, b_name, n, split, nsizes, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ea, eb = load_engine(a_name), load_engine(b_name)
    rng = random.Random(7)
    key = {}
    for i, (cid, src, (tw, th)) in enumerate(cases(split, n, nsizes)):
        tgt = {"width": tw, "height": th}
        oa, ob = ea(src, tgt), eb(src, tgt)
        flip = rng.random() < 0.5
        left, right = (ob, oa) if flip else (oa, ob)
        ims = []
        for tag, d in (("A", left), ("B", right)):
            im = _render(d, out / "_tmp.png")
            im.thumbnail((700, 700))
            ims.append(im)
        w = ims[0].width + ims[1].width + 60
        h = max(ims[0].height, ims[1].height) + 50
        sheet = Image.new("RGB", (w, h), "white")
        dr = ImageDraw.Draw(sheet)
        sheet.paste(ims[0], (20, 40))
        sheet.paste(ims[1], (40 + ims[0].width, 40))
        dr.text((20, 10), "A", fill="black")
        dr.text((40 + ims[0].width, 10), "B", fill="black")
        name = f"pair_{i:02d}"
        sheet.save(out / f"{name}.png")
        key[name] = {"case": cid, "A": b_name if flip else a_name, "B": a_name if flip else b_name,
                     "score": {a_name: metrics(src, oa)["score"], b_name: metrics(src, ob)["score"]}}
    (out / "_tmp.png").unlink(missing_ok=True)
    json.dump(key, open(out / "key.json", "w"), indent=1)
    (out / "PROMPT.md").write_text(PROMPT.format(out=out))
    print(f"{len(key)} pairs in {out}; give subagents {out}/PROMPT.md")


def tally(out):
    out = Path(out)
    key = json.load(open(out / "key.json"))
    picks = json.load(open(out / "picks.json"))
    wins, agree, n = {}, 0, 0
    for name, k in key.items():
        if name not in picks:
            continue
        winner = k[picks[name]["pick"]]
        loser = k["A"] if winner == k["B"] else k["B"]
        wins[winner] = wins.get(winner, 0) + 1
        n += 1
        agree += k["score"][winner] >= k["score"][loser]
    print(f"{n} judged pairs; wins: {wins}")
    if n:
        print(f"code score agrees with the judge on {agree}/{n} ({100 * agree / n:.0f}%)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["make", "tally"])
    ap.add_argument("--a", default="engine.resize:resize")
    ap.add_argument("--b", default="baseline")
    ap.add_argument("-n", type=int, default=12)
    ap.add_argument("--split", default="train")
    ap.add_argument("--sizes", default="1")
    ap.add_argument("--out", default="/tmp/judge")
    a = ap.parse_args()
    if a.cmd == "make":
        make(a.a, a.b, a.n, a.split, a.sizes, a.out)
    else:
        tally(a.out)
