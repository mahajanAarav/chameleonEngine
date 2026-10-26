"""Check and render a hand-made layout against its task.

    python -m tools.refcheck TASK.json LAYOUT.json [--png out.png]

TASK.json = {"case", "source", "target"}; LAYOUT.json = {"canvas", "elements"} in the same schema as
the source. Prints rule errors/warnings from the strict checker and renders a PNG to look at.
"""

import argparse
import json
from pathlib import Path

from engine.rules import check


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("layout")
    ap.add_argument("--png", default="")
    a = ap.parse_args()
    task = json.load(open(a.task))
    layout = json.load(open(a.layout))
    t = task["target"]
    if layout.get("canvas") != {"width": t["width"], "height": t["height"]}:
        print(f"ERROR canvas must be exactly {t['width']}x{t['height']}")
    probs = check(task["source"], layout)
    for sev, msg in probs:
        print(sev.upper(), msg)
    print("RESULT:", "no errors" if not any(s == "error" for s, _ in probs) else "FIX THE ERRORS ABOVE")
    if a.png:
        from renderer.converter.convert import render_design_to_png
        render_design_to_png(layout, Path("brand_kit/assets"), Path(a.png))
        print("rendered", a.png)


if __name__ == "__main__":
    main()
