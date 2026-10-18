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


def make_cands(n, split, nsizes, out, skip=0, maxgap=1e9):
    """Pairs of two different valid candidate layouts from the engine for the same case:
    A = the best by our score, B = another candidate. Tests whether our score ranks layouts like the judge."""
    from engine.resize import candidates
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(11)
    key, i = {}, 0
    for cid, src, (tw, th) in cases(split, n, nsizes, skip):
        cands = candidates(src, {"width": tw, "height": th})
        scored = [(name, o, metrics(src, o)) for name, o in cands]
        valid = [(nm, o, m) for nm, o, m in scored if not m["errors"]]
        if len(valid) < 2:
            continue
        valid.sort(key=lambda t: -t[2]["score"])
        best = valid[0]
        others = [t for t in valid[1:] if best[2]["score"] - maxgap <= t[2]["score"] <= best[2]["score"] - 1.0 and t[1] != best[1]]
        if not others:
            continue
        other = rng.choice(others)
        flip = rng.random() < 0.5
        left, right = (other, best) if flip else (best, other)
        ims = []
        for _, o, _ in (left, right):
            im = _render(o, out / "_tmp.png")
            im.thumbnail((700, 700))
            ims.append(im)
        sheet = Image.new("RGB", (ims[0].width + ims[1].width + 60, max(ims[0].height, ims[1].height) + 50), "white")
        dr = ImageDraw.Draw(sheet)
        sheet.paste(ims[0], (20, 40))
        sheet.paste(ims[1], (40 + ims[0].width, 40))
        dr.text((20, 10), "A", fill="black")
        dr.text((40 + ims[0].width, 10), "B", fill="black")
        name = f"pair_{i:02d}"
        sheet.save(out / f"{name}.png")
        key[name] = {"case": cid, "A": left[0], "B": right[0],
                     "terms": {left[0]: {k: v for k, v in left[2].items() if isinstance(v, float)},
                               right[0]: {k: v for k, v in right[2].items() if isinstance(v, float)}},
                     "score": {left[0]: left[2]["score"], right[0]: right[2]["score"]}}
        i += 1
    (out / "_tmp.png").unlink(missing_ok=True)
    json.dump(key, open(out / "key.json", "w"), indent=1)
    json.dump({"split": split, "n": n, "nsizes": nsizes, "skip": skip}, open(out / "meta.json", "w"))
    (out / "PROMPT.md").write_text(PROMPT.format(out=out))
    print(f"{len(key)} candidate pairs in {out}")


OLD_WEIGHTS = {"overlap": 0.30, "readability": 0.30, "hierarchy": 0.15, "margin": 0.10, "coverage": 0.15,
               "logo": 0.0, "cta": 0.0, "headline": 0.0, "product": 0.0}


def make_weights(n, split, nsizes, out, skip=0):
    """Pairs where A/B are the layouts picked by the old vs the new scorer weights (only where they differ).
    The 'engine' labels in key.json are 'old' and 'new'; tally then shows which weights the judges prefer."""
    from engine.resize import candidates
    from engine.score import WEIGHTS
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(5)
    key, i = {}, 0
    for cid, src, (tw, th) in cases(split, n, nsizes, skip):
        valid = []
        for name, o in candidates(src, {"width": tw, "height": th}):
            m = metrics(src, o)
            if not m["errors"]:
                valid.append((name, o, m))
        if len(valid) < 2:
            continue
        pick = lambda w: max(valid, key=lambda t: sum(w.get(k, 0) * t[2][k] for k in OLD_WEIGHTS))
        old, new = pick(OLD_WEIGHTS), pick(WEIGHTS)
        if old[1] == new[1]:
            continue
        flip = rng.random() < 0.5
        left, right = ((new, "new"), (old, "old")) if flip else ((old, "old"), (new, "new"))
        ims = []
        for (t, _) in (left, right):
            im = _render(t[1], out / "_tmp.png")
            im.thumbnail((700, 700))
            ims.append(im)
        sheet = Image.new("RGB", (ims[0].width + ims[1].width + 60, max(ims[0].height, ims[1].height) + 50), "white")
        dr = ImageDraw.Draw(sheet)
        sheet.paste(ims[0], (20, 40))
        sheet.paste(ims[1], (40 + ims[0].width, 40))
        dr.text((20, 10), "A", fill="black")
        dr.text((40 + ims[0].width, 10), "B", fill="black")
        name = f"pair_{i:02d}"
        sheet.save(out / f"{name}.png")
        key[name] = {"case": cid, "A": left[1], "B": right[1], "score": {"old": 0.0, "new": 0.0}}
        i += 1
    (out / "_tmp.png").unlink(missing_ok=True)
    json.dump(key, open(out / "key.json", "w"), indent=1)
    print(f"{len(key)} old-vs-new pairs in {out}")


def tally(out):
    out = Path(out)
    key = json.load(open(out / "key.json"))
    picks = {}
    for f in sorted(out.glob("picks*.json")):
        picks.update(json.load(open(f)))
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
    ap.add_argument("cmd", choices=["make", "make-cands", "make-weights", "tally"])
    ap.add_argument("--a", default="engine.resize:resize")
    ap.add_argument("--b", default="baseline")
    ap.add_argument("-n", type=int, default=12)
    ap.add_argument("--split", default="train")
    ap.add_argument("--sizes", default="1")
    ap.add_argument("--out", default="/tmp/judge")
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--maxgap", type=float, default=1e9)
    a = ap.parse_args()
    if a.cmd == "make":
        make(a.a, a.b, a.n, a.split, a.sizes, a.out)
    elif a.cmd == "make-weights":
        make_weights(a.n, a.split, a.sizes, a.out, a.skip)
    elif a.cmd == "make-cands":
        make_cands(a.n, a.split, a.sizes, a.out, a.skip, a.maxgap)
    else:
        tally(a.out)
