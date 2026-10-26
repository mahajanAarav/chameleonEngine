"""Write tasks for human/LLM designers to produce reference ("perfect") layouts.

    python -m tools.make_ref_tasks --out /tmp/refs --train 8 --heldout 4 --sizes 2

Each task_NN.json has the source design and target size; task_NN_source.png is the source render.
"""

import argparse
import json
from pathlib import Path

from tools.report import cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--train", type=int, default=8)
    ap.add_argument("--heldout", type=int, default=4)
    ap.add_argument("--sizes", default="2")
    ap.add_argument("--skip-train", type=int, default=0, help="designs already used in this split")
    ap.add_argument("--skip-heldout", type=int, default=0)
    ap.add_argument("--start", type=int, default=0, help="first task number")
    ap.add_argument("--png-dir", default="", help="where to write the source renders (default: --out)")
    a = ap.parse_args()
    from renderer.converter.convert import render_design_to_png
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    png = Path(a.png_dir) if a.png_dir else out
    png.mkdir(parents=True, exist_ok=True)
    i = a.start
    for split, n, skip in (("train", a.train, a.skip_train), ("heldout", a.heldout, a.skip_heldout)):
        for cid, src, (tw, th) in cases(split, n, a.sizes, skip):
            task = {"case": cid, "split": split, "source": src, "target": {"width": tw, "height": th}}
            json.dump(task, open(out / f"task_{i:03d}.json", "w"), indent=1)
            render_design_to_png(src, Path("brand_kit/assets"), png / f"task_{i:03d}_source.png")
            print(f"task_{i:03d}: {cid} ({split}) -> {tw}x{th}")
            i += 1


if __name__ == "__main__":
    main()
