"""Write designer tasks for the real-ad look-alikes (tools/real_ads.py): one task per ad and target size.

    python -m tools.make_real_tasks --out data/refs --png-dir /tmp/refs3 --start 124

Splits by DESIGN (never within one): heldout = pizza, ford, mmm_wordart; everything else is train.
"""

import argparse
import json
from pathlib import Path

from tools.real_ads import ADS, TARGETS

HELDOUT = {"pizza", "ford", "mmm_wordart"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--png-dir", required=True)
    ap.add_argument("--start", type=int, default=124)
    a = ap.parse_args()
    from renderer.converter.convert import render_design_to_png
    out, png = Path(a.out), Path(a.png_dir)
    png.mkdir(parents=True, exist_ok=True)
    i = a.start
    for name, ad in ADS.items():
        for tw, th in TARGETS:
            task = {"case": f"real:{name}->{tw}x{th}", "split": "heldout" if name in HELDOUT else "train",
                    "source": ad["source"], "target": {"width": tw, "height": th}}
            json.dump(task, open(out / f"task_{i:03d}.json", "w"), indent=1)
            render_design_to_png(ad["source"], Path("brand_kit/assets"), png / f"task_{i:03d}_source.png")
            print(f"task_{i:03d} {task['case']} ({task['split']})")
            i += 1


if __name__ == "__main__":
    main()
