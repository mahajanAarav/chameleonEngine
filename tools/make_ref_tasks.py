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
    a = ap.parse_args()
    from renderer.converter.convert import render_design_to_png
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    i = 0
    for split, n in (("train", a.train), ("heldout", a.heldout)):
        for cid, src, (tw, th) in cases(split, n, a.sizes):
            task = {"case": cid, "split": split, "source": src, "target": {"width": tw, "height": th}}
            json.dump(task, open(out / f"task_{i:02d}.json", "w"), indent=1)
            render_design_to_png(src, Path("brand_kit/assets"), out / f"task_{i:02d}_source.png")
            print(f"task_{i:02d}: {cid} ({split}) -> {tw}x{th}")
            i += 1


if __name__ == "__main__":
    main()
