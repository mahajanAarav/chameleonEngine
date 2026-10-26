"""Is the right layout among our candidates? Compare what the scorer picks with the best possible pick.

    python -m tools.oracle --refs /tmp/refs [--fit]

For each reference case: distance of the engine's chosen layout vs the 'oracle' (the candidate closest to the
reference). With --fit, search scorer weights on train cases that maximise the distance of the chosen layout
and report them on the held-out cases.
"""

import argparse
import glob
import json
import random
import statistics
from pathlib import Path

from engine.resize import OVERLAP_OK, candidates
from engine.score import WEIGHTS, metrics
from tools.refdist import ref_score

TERMS = list(WEIGHTS)


def load(refs):
    rows = []
    for tf in sorted(glob.glob(f"{refs}/task_[0-9][0-9].json")):
        n = Path(tf).stem.split("_")[1]
        task, ref = json.load(open(tf)), json.load(open(f"{refs}/layout_{n}.json"))
        cands = []
        for name, o in candidates(task["source"], task["target"]):
            m = metrics(task["source"], o)
            if m["errors"]:
                continue
            cands.append({"name": name, "terms": [m[t] for t in TERMS], "overlap_ok": m["overlap"] >= OVERLAP_OK,
                          "dist": ref_score(task["source"], o, ref)})
        rows.append({"n": n, "split": task["split"], "cands": cands})
    return rows


def pick(row, w):
    best = max(row["cands"], key=lambda c: (c["overlap_ok"], sum(wi * t for wi, t in zip(w, c["terms"]))))
    return best["dist"]


def evaluate(rows, w):
    return statistics.mean(pick(r, w) for r in rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", required=True)
    ap.add_argument("--fit", action="store_true")
    a = ap.parse_args()
    rows = load(a.refs)
    cur = [WEIGHTS[t] for t in TERMS]
    print(f"{'case':5s} {'chosen':>7s} {'oracle':>7s} {'safety':>7s} {'#cands':>6s}")
    for r in rows:
        oracle = max(c["dist"] for c in r["cands"])
        safety = next(c["dist"] for c in r["cands"] if c["name"] == "safety")
        print(f"{r['n']:5s} {pick(r, cur):7.1f} {oracle:7.1f} {safety:7.1f} {len(r['cands']):6d}")
    for sp in ("train", "heldout"):
        sub = [r for r in rows if r["split"] == sp]
        print(f"{sp:8s} chosen {evaluate(sub, cur):.1f}  oracle {statistics.mean(max(c['dist'] for c in r['cands']) for r in sub):.1f}")
    if a.fit:
        train = [r for r in rows if r["split"] == "train"]
        held = [r for r in rows if r["split"] == "heldout"]
        rng = random.Random(0)
        best, best_s = list(cur), evaluate(train, cur)
        for _ in range(3000):
            cand = [max(0.0, b + rng.gauss(0, 0.05)) for b in best]
            tot = sum(cand) or 1
            cand = [c / tot for c in cand]
            s = evaluate(train, cand)
            if s > best_s:
                best, best_s = cand, s
        print(f"\nfitted on train: {best_s:.1f} (was {evaluate(train, cur):.1f}); heldout: {evaluate(held, best):.1f} (was {evaluate(held, cur):.1f})")
        print({t: round(x, 3) for t, x in zip(TERMS, best)})


if __name__ == "__main__":
    main()
