"""How accurately does engine/understand.py guess roles? Ground truth comes from
the id names our generator and the official samples use (the engine itself never reads ids).

    python -m tools.test_understand [-n 100]
"""

import argparse
import glob
import json
from collections import Counter

from engine.understand import understand
from tools.gen_designs import generate_set


def truth(uid: str) -> str:
    u = uid.lower()
    for key, role in [("bg", "bg"), ("deco", "decoration"), ("logo", "logo"), ("product", "product"),
                      ("headline", "headline"), ("subhead", "supporting"), ("badge", "badge"),
                      ("ribbon", "ribbon"), ("watermark", "watermark"), ("legal", "fine_print")]:
        if u == key or u.startswith(key) or (key == "watermark" and key in u):
            return role
    return "cta" if u.startswith("cta") else "?"


def main(n: int):
    designs = [(f"gen{s}", d) for s, d in generate_set("all", n)]
    for f in sorted(glob.glob("input/*.json")):
        designs.append((f, json.load(open(f))["source"]))
    total = right = 0
    confusions = Counter()
    for name, src in designs:
        for u in understand(src).units:
            want = truth(u.uid)
            if want == "cta" and u.role == "cta_text":  # plain-text button counts as a button
                got = "cta"
            else:
                got = u.role
            total += 1
            if got == want:
                right += 1
            else:
                confusions[(want, got)] += 1
                if confusions[(want, got)] <= 2:
                    print(f"  {name}: {u.uid} should be {want}, got {u.role}")
    print(f"\nrole accuracy: {right}/{total} = {100 * right / total:.1f}%")
    for (w, g), c in confusions.most_common(8):
        print(f"  {w} -> {g}: {c}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    main(ap.parse_args().n)
