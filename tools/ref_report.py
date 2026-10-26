"""Score the engine against reference layouts, and build a review sheet.

    python -m tools.ref_report --refs /tmp/refs [--engine safety] [--sheet /tmp/review.png]

Reads task_NN.json + layout_NN.json from --refs. Prints the distance score per case and the mean for
train and heldout cases. The sheet shows reference (left) vs the engine (right) for each case, so a
human can judge which is better, not just which is closer.
"""

import argparse
import glob
import json
import statistics
from pathlib import Path

from engine.rules import check
from tools.refdist import ref_score
from tools.report import load_engine


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", required=True)
    ap.add_argument("--engine", default="engine.resize:resize")
    ap.add_argument("--sheet", default="")
    ap.add_argument("--pairs", default="", help="write blind reference-vs-engine A/B pairs here")
    a = ap.parse_args()
    eng = load_engine(a.engine)
    rows = []
    for tf in sorted(glob.glob(f"{a.refs}/task_[0-9][0-9].json")):
        n = Path(tf).stem.split("_")[1]
        lf = Path(a.refs) / f"layout_{n}.json"
        if not lf.exists():
            continue
        task, ref = json.load(open(tf)), json.load(open(lf))
        errs = [m for s, m in check(task["source"], ref) if s == "error"]
        out = eng(task["source"], task["target"])
        rows.append({"n": n, "case": task["case"], "split": task["split"], "ref_errors": errs, "task": task,
                     "ref": ref, "out": out, "dist": ref_score(task["source"], out, ref)})
    for r in rows:
        flag = f"  (reference has {len(r['ref_errors'])} rule errors!)" if r["ref_errors"] else ""
        print(f"  {r['n']} {r['case']:32s} {r['split']:8s} distance score {r['dist']:5.1f}{flag}")
    for sp in ("train", "heldout"):
        v = [r["dist"] for r in rows if r["split"] == sp and not r["ref_errors"]]
        if v:
            print(f"mean distance score, {sp}: {statistics.mean(v):.1f} over {len(v)} cases")
    if a.pairs:
        import random
        from PIL import Image, ImageDraw
        from renderer.converter.convert import render_design_to_png
        pd = Path(a.pairs)
        pd.mkdir(parents=True, exist_ok=True)
        rng, key = random.Random(3), {}
        for r in rows:
            flip = rng.random() < 0.5
            sides = [("engine", r["out"]), ("ref", r["ref"])] if flip else [("ref", r["ref"]), ("engine", r["out"])]
            ims = []
            for tag, d in sides:
                render_design_to_png(d, Path("brand_kit/assets"), pd / "_t.png")
                im = Image.open(pd / "_t.png").convert("RGB")
                im.thumbnail((700, 700))
                ims.append(im)
            sh = Image.new("RGB", (ims[0].width + ims[1].width + 60, max(i.height for i in ims) + 50), "white")
            sh.paste(ims[0], (20, 40))
            sh.paste(ims[1], (40 + ims[0].width, 40))
            dr = ImageDraw.Draw(sh)
            dr.text((20, 10), "A", fill="black")
            dr.text((40 + ims[0].width, 10), "B", fill="black")
            sh.save(pd / f"pair_{r['n']}.png")
            key[f"pair_{r['n']}"] = {"case": r["case"], "A": sides[0][0], "B": sides[1][0],
                                     "score": {"ref": 0.0, "engine": 0.0}}
        (pd / "_t.png").unlink(missing_ok=True)
        json.dump(key, open(pd / "key.json", "w"), indent=1)
        print(f"{len(key)} blind pairs in {pd}")
    if a.sheet:
        from PIL import Image, ImageDraw
        from renderer.converter.convert import render_design_to_png
        tmp = Path(a.sheet).with_suffix("")
        tmp.mkdir(parents=True, exist_ok=True)
        cells = []
        for r in rows:
            ims = []
            for tag, d in (("reference", r["ref"]), ("engine", r["out"])):
                p = tmp / f"{r['n']}_{tag}.png"
                render_design_to_png(d, Path("brand_kit/assets"), p)
                im = Image.open(p).convert("RGB")
                im.thumbnail((520, 420))
                ims.append(im)
            cell = Image.new("RGB", (1080, 470), "white")
            cell.paste(ims[0], (10, 35))
            cell.paste(ims[1], (550, 35))
            dr = ImageDraw.Draw(cell)
            dr.text((10, 8), f"{r['n']} {r['case']} -> {r['task']['target']['width']}x{r['task']['target']['height']}"
                    f"   LEFT = reference, RIGHT = engine   distance {r['dist']:.0f}", fill="black")
            cells.append(cell)
        per = 8
        for k in range(0, len(cells), per):
            chunk = cells[k:k + per]
            sheet = Image.new("RGB", (1080 * 2, 470 * ((len(chunk) + 1) // 2)), "white")
            for i, c in enumerate(chunk):
                sheet.paste(c, ((i % 2) * 1080, (i // 2) * 470))
            out_path = Path(a.sheet).with_name(f"{Path(a.sheet).stem}_{k // per + 1}.png")
            sheet.save(out_path)
            print("sheet:", out_path)


if __name__ == "__main__":
    main()
