"""One command that scores an engine.

    python -m tools.report                       # train + heldout + official samples
    python -m tools.report --engine baseline     # compare against the stretch baseline
    python -m tools.report --sizes all -n 20     # every catalogue size per design
    python -m tools.report --sheet 12 --out /tmp/sheet.png   # contact sheet of worst cases

--engine takes baseline, safety, or module:function (default engine.resize:resize).
Never tune on the heldout split.
"""

import argparse
import glob
import importlib
import json
import random
import statistics
from pathlib import Path

from tools.gen_designs import generate_set
from tools.metrics import metrics
from tools.sizes import SIZES

TERMS = ["overlap", "readability", "hierarchy", "margin", "coverage"]


def load_engine(name: str):
    if name == "baseline":
        from engine.resize import _baseline_stretch
        return _baseline_stretch
    if name == "safety":
        from engine.safety import safety_resize
        return safety_resize
    mod, _, fn = name.partition(":")
    return getattr(importlib.import_module(mod), fn or "resize")


def bucket(src_c: dict, dst: tuple[int, int]) -> str:
    r = (dst[0] / dst[1]) / (src_c["width"] / src_c["height"])
    if r >= 4: return "ultra-wide"
    if r >= 1.5: return "wider"
    if r > 0.67: return "similar"
    if r > 0.25: return "taller"
    return "ultra-tall"


def cases(split: str, n: int, nsizes, skip: int = 0):
    """Yield (case_id, source, (tw, th))."""
    if split == "samples":
        for f in sorted(glob.glob("input/*.json")):
            t = json.load(open(f))
            yield Path(f).stem, t["source"], (t["target_canvas"]["width"], t["target_canvas"]["height"])
        return
    for seed, src in generate_set(split, n + skip)[skip:]:
        sc = (src["canvas"]["width"], src["canvas"]["height"])
        names = [k for k, v in SIZES.items() if v != sc]
        if nsizes != "all":
            names = random.Random(seed).sample(names, int(nsizes))
        for name in names:
            yield f"s{seed}->{name}", src, SIZES[name]


def run(engine, split, n, nsizes):
    rows = []
    for cid, src, (tw, th) in cases(split, n, nsizes):
        try:
            out = engine(src, {"width": tw, "height": th})
            m = metrics(src, out)
        except Exception as e:  # an engine crash is the worst result
            out, m = None, {"score": 0.0, "errors": [f"CRASH {type(e).__name__}: {e}"], "warns": [],
                            **{t: 0.0 for t in TERMS}}
        rows.append({"id": cid, "split": split, "bucket": bucket(src["canvas"], (tw, th)), "src": src,
                     "target": (tw, th), "out": out, **m})
    return rows


def summarize(rows, label):
    if not rows:
        return
    bad = [r for r in rows if r["errors"]]
    print(f"\n== {label}: {len(rows)} cases | rule-breaking cases: {len(bad)} | "
          f"mean score {statistics.mean(r['score'] for r in rows):.1f}")
    print("   terms: " + "  ".join(f"{t} {statistics.mean(r[t] for r in rows):.2f}" for t in TERMS))
    by = {}
    for r in rows:
        by.setdefault(r["bucket"], []).append(r["score"])
    print("   by shape: " + "  ".join(f"{b} {statistics.mean(v):.1f} (n={len(v)})" for b, v in sorted(by.items())))
    scores = sorted(r["score"] for r in rows)
    p10 = scores[max(0, int(0.1 * len(scores)) - 1)]
    print(f"   consistency: worst case {scores[0]:.1f} | 10th percentile {p10:.1f} | spread (std) "
          f"{statistics.pstdev(scores):.1f}")
    sizes = {}
    for r in rows:
        sizes.setdefault(r["target"], []).append(r["score"])
    if len(sizes) > 1:
        per = sorted((statistics.mean(v), k, len(v)) for k, v in sizes.items())
        print("   weakest sizes: " + "  ".join(f"{k[0]}x{k[1]} {m:.1f} (n={n})" for m, k, n in per[:4]))
    for r in bad[:3]:
        print(f"   ERROR {r['id']}: {r['errors'][0]}")


def sheet(rows, k, path):
    from PIL import Image, ImageDraw
    from renderer.converter.convert import render_design_to_png
    tmp = Path(path).with_suffix("")
    tmp.mkdir(parents=True, exist_ok=True)
    worst = sorted(rows, key=lambda r: r["score"])[:k]
    ims = []
    for i, r in enumerate(worst):
        if r["out"] is None:
            continue
        p = tmp / f"w{i}.png"
        render_design_to_png(r["out"], Path("brand_kit/assets"), p)
        im = Image.open(p).convert("RGB")
        im.thumbnail((480, 300))
        cell = Image.new("RGB", (500, 340), "white")
        cell.paste(im, (10, 30))
        ImageDraw.Draw(cell).text((10, 8), f"{r['id']}  score {r['score']:.0f}", fill="black")
        ims.append(cell)
    cols = 3
    out = Image.new("RGB", (cols * 500, ((len(ims) + cols - 1) // cols) * 340), "white")
    for i, c in enumerate(ims):
        out.paste(c, ((i % cols) * 500, (i // cols) * 340))
    out.save(path)
    print(f"contact sheet of {len(ims)} worst cases -> {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="engine.resize:resize")
    ap.add_argument("-n", type=int, default=15, help="designs per split")
    ap.add_argument("--sizes", default="4", help="target sizes per design, or 'all'")
    ap.add_argument("--splits", default="samples,train,heldout")
    ap.add_argument("--save", default="", help="write per-case scores to this JSON file")
    ap.add_argument("--sheet", type=int, default=0, help="render the N worst cases")
    ap.add_argument("--out", default="/tmp/report_sheet.png")
    a = ap.parse_args()

    eng = load_engine(a.engine)
    allrows = []
    for sp in a.splits.split(","):
        rows = run(eng, sp, a.n, a.sizes)
        allrows += rows
        summarize(rows, sp)
    print("\nworst 5:")
    for r in sorted(allrows, key=lambda r: r["score"])[:5]:
        print(f"   {r['score']:5.1f} {r['id']} ({r['bucket']})  {(r['errors'] or r['warns'] or [''])[0][:70]}")
    if a.save:
        json.dump([{k: v for k, v in r.items() if k not in ("src", "out")} for r in allrows], open(a.save, "w"))
    if a.sheet:
        sheet(allrows, a.sheet, a.out)
