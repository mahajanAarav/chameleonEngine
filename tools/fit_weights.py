"""Fit scorer weights to the judges' pairwise picks.

    python -m tools.fit_weights /tmp/judge_c1 [more dirs ...]

For every judged pair we know each layout's term values (overlap, readability, ...)
and which one the judge preferred. We search weights (non-negative, summing to 1)
that maximise how often the higher weighted score matches the judge, with leave-one-out
checking so we don't just memorise a few dozen pairs.
"""

import itertools
import json
import random
import sys
from pathlib import Path

from engine.score import WEIGHTS

TERMS = list(WEIGHTS)


def recompute_ref(key, refs, **_):
    """Reference-vs-engine pairs: terms of the designer layout and of the engine as the judges saw it
    (before the logo gate existed)."""
    import engine.resize as R
    from engine.score import metrics
    R.LOGO_OK = 0.0
    for name, k in key.items():
        n = name.split("_")[1]
        t = json.load(open(f"{refs}/task_{n}.json"))
        ref = json.load(open(f"{refs}/layout_{n}.json"))
        out = R.resize(t["source"], t["target"])
        k["terms"] = {"ref": {c: v for c, v in metrics(t["source"], ref).items() if isinstance(v, float)},
                      "engine": {c: v for c, v in metrics(t["source"], out).items() if isinstance(v, float)}}
    return key


def recompute(key, split="train", n=20, nsizes="2", skip=0):
    """Re-derive every candidate's current term values (layouts are deterministic), so old
    judgments stay usable after we add or change score terms."""
    from engine.resize import candidates
    from engine.score import metrics
    from tools.report import cases
    cache = {cid: (src, tgt) for cid, src, tgt in cases(split, n, nsizes, skip)}
    for k in key.values():
        src, (tw, th) = cache[k["case"]]
        cands = dict(candidates(src, {"width": tw, "height": th}))
        k["terms"] = {nm: {t: v for t, v in metrics(src, cands[nm]).items() if isinstance(v, float)}
                      for nm in (k["A"], k["B"])}
    return key


def load(dirs):
    rows = []
    for d in dirs:
        d = Path(d)
        meta = json.load(open(d / "meta.json")) if (d / "meta.json").exists() else {}
        raw = json.load(open(d / "key.json"))
        key = recompute_ref(raw, **meta) if meta.get("kind") == "ref" else recompute(raw, **meta)
        picks = {}
        for f in sorted(d.glob("picks*.json")):
            picks.update(json.load(open(f)))
        for name, k in key.items():
            if name in picks:
                win = k[picks[name]["pick"]]
                lose = k["A"] if win == k["B"] else k["B"]
                rows.append(([k["terms"][win].get(t, 0.0) - k["terms"][lose].get(t, 0.0) for t in TERMS],
                             name, d.name))
    return rows


def agree(rows, w):
    """Fraction of pairs where the judge's winner has the higher weighted score (ties count half)."""
    good = 0.0
    for diff, _, _ in rows:
        s = sum(wi * di for wi, di in zip(w, diff))
        good += 1.0 if s > 1e-9 else 0.5 if abs(s) <= 1e-9 else 0.0
    return good / len(rows)


def search(rows, iters=4000, seed=0, start=None):
    rng = random.Random(seed)
    best = list(start or [1 / len(TERMS)] * len(TERMS))
    best_a = agree(rows, best)
    for _ in range(iters):
        cand = [max(0.0, b + rng.gauss(0, 0.06)) for b in best]
        tot = sum(cand) or 1
        cand = [c / tot for c in cand]
        a = agree(rows, cand)
        # prefer higher agreement; on ties prefer the weights closer to uniform (less overfit)
        if a > best_a or (a == best_a and sum(abs(c - 1 / len(TERMS)) for c in cand)
                          < sum(abs(c - 1 / len(TERMS)) for c in best)):
            best, best_a = cand, a
    return best, best_a


if __name__ == "__main__":
    rows = load(sys.argv[1:])
    if not rows:
        sys.exit("no judged pairs found")
    cur = [WEIGHTS[t] for t in TERMS]
    print(f"{len(rows)} judged pairs")
    print(f"current weights agree with judges on {agree(rows, cur):.0%}")
    # per-term signal: how often the judge's winner has the larger value of just that term
    for i, t in enumerate(TERMS):
        w = [0.0] * len(TERMS)
        w[i] = 1.0
        nz = [r for r in rows if abs(r[0][i]) > 1e-9]
        print(f"  {t:12s} alone: {agree(rows, w):.0%} (differs in {len(nz)} pairs)")
    # leave-one-out: fit on all but one pair, test on it
    hits = 0.0
    for j in range(len(rows)):
        train = rows[:j] + rows[j + 1:]
        w, _ = search(train, iters=800, seed=j, start=cur)
        hits += agree([rows[j]], w)
    print(f"leave-one-out agreement of fitted weights: {hits / len(rows):.0%}")
    w, a = search(rows, start=cur)
    print(f"fitted on all pairs: {a:.0%}")
    print("weights:", {t: round(x, 3) for t, x in zip(TERMS, w)})
