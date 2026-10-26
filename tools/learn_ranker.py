"""Learn a "designer-likeness" ranker from designer reference layouts.

    python -m tools.learn_ranker [--save] [--splits train] [--folds 5]

For every task with a reference (data/refs/task_*.json + layout_*.json) we compute the features of the designer's
layout and of every candidate the engine generates. A linear model is trained so the designer's layout outranks the
candidates (pairwise hinge loss, L2 regularised, standardised features). Reported honestly:
  * k-fold cross-validation over the training tasks
  * the held-out tasks (never trained on)
  * the real question: how close (distance to the reference) is the layout the ranker would PICK, compared with the
    engine's current pick and with the best candidate available (oracle).
--save writes engine/ranker.json, which engine/score.py then uses.
"""

import argparse
import glob
import json
import random
import statistics
from pathlib import Path

import numpy as np

from engine.resize import LOGO_OK, OVERLAP_OK, candidates
from engine.rules import check
from engine.score import metrics
from tools.refdist import ref_score


def load_tasks(splits):
    tasks = []
    for tf in sorted(glob.glob("data/refs/task_*.json")):
        lf = tf.replace("task_", "layout_")
        if not Path(lf).exists():
            continue
        t, ref = json.load(open(tf)), json.load(open(lf))
        if t["split"] not in splits or any(s == "error" for s, _ in check(t["source"], ref)):
            continue
        tasks.append((tf, t, ref))
    return tasks


def featurise(task, ref, names=None):
    src, tgt = task["source"], task["target"]
    mr = metrics(src, ref)
    names = names or sorted(k for k, v in mr.items() if isinstance(v, float) and k != "score")
    cands = []
    for name, out in candidates(src, tgt):
        m = metrics(src, out)
        if m["errors"]:
            continue
        cands.append({"name": name, "x": np.array([m[k] for k in names]), "gate": (m["overlap"] >= OVERLAP_OK, m["logo"] >= LOGO_OK),
                      "dist": ref_score(src, out, ref)})
    return {"ref": np.array([mr[k] for k in names]), "cands": cands, "split": task["split"]}, names


def train(rows, mu, sd, lam=0.02, steps=600, lr=0.05, margin=0.3):
    F = len(mu)
    w = np.zeros(F)
    data = [((r["ref"] - mu) / sd, np.array([(c["x"] - mu) / sd for c in r["cands"]])) for r in rows]
    for _ in range(steps):
        g = 2 * lam * w
        for xr, C in data:
            viol = margin - (C - 0) @ (-w) - 0  # placeholder to keep shapes clear
            d = xr - C                           # (n_cands, F): want w.d > margin
            bad = (d @ w) < margin
            if bad.any():
                g -= d[bad].mean(axis=0) / len(data)
        w -= lr * g
    return w


def pick(row, w, mu, sd):
    def key(c):
        return (c["gate"][0], c["gate"][1], float(((c["x"] - mu) / sd) @ w))
    return max(row["cands"], key=key)["dist"]


def evaluate(rows, w, mu, sd, current):
    if not rows:
        return None
    return {"ranker pick": statistics.mean(pick(r, w, mu, sd) for r in rows),
            "current pick": statistics.mean(pick(r, current, mu, sd) for r in rows),
            "oracle": statistics.mean(max(c["dist"] for c in r["cands"]) for r in rows),
            "pair acc": statistics.mean(float(((r["ref"] - c["x"]) / sd) @ w > 0) for r in rows for c in r["cands"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--lam", type=float, default=0.02)
    a = ap.parse_args()

    tr_tasks, ho_tasks = load_tasks({"train"}), load_tasks({"heldout"})
    rows, names = [], None
    for _, t, ref in tr_tasks:
        r, names = featurise(t, ref, names)
        rows.append(r)
    held = [featurise(t, ref, names)[0] for _, t, ref in ho_tasks]
    print(f"{len(rows)} train tasks, {len(held)} held-out tasks, {len(names)} features, "
          f"{sum(len(r['cands']) for r in rows)} candidate layouts")

    allx = np.array([c["x"] for r in rows for c in r["cands"]] + [r["ref"] for r in rows])
    mu, sd = allx.mean(axis=0), allx.std(axis=0) + 1e-6

    # current engine scoring, expressed as weights on the standardised features, for comparison
    from engine.score import WEIGHTS
    cur = np.array([WEIGHTS.get(k, 0.0) for k in names]) * sd  # standardised weight = w * sd

    rng = random.Random(0)
    idx = list(range(len(rows)))
    rng.shuffle(idx)
    folds = [idx[i::a.folds] for i in range(a.folds)]
    cv = {"ranker pick": [], "current pick": [], "oracle": [], "pair acc": []}
    for f in folds:
        test = [rows[i] for i in f]
        trn = [rows[i] for i in idx if i not in f]
        w = train(trn, mu, sd, a.lam)
        ev = evaluate(test, w, mu, sd, cur)
        for k in cv:
            cv[k].append(ev[k])
    print("\ncross-validated on training tasks:  " + "  ".join(f"{k} {statistics.mean(v):.1f}" if k != "pair acc"
                                                               else f"{k} {statistics.mean(v):.0%}" for k, v in cv.items()))
    w = train(rows, mu, sd, a.lam)
    if held:
        ev = evaluate(held, w, mu, sd, cur)
        print("held-out tasks (never trained on):   " + "  ".join(f"{k} {v:.1f}" if k != "pair acc" else f"{k} {v:.0%}"
                                                                  for k, v in ev.items()))
    print("\nlearned weights (on standardised features):")
    for k, v in sorted(zip(names, w), key=lambda kv: -abs(kv[1])):
        print(f"  {k:12s} {v:+.3f}")
    if a.save:
        json.dump({"names": names, "mu": mu.tolist(), "sd": sd.tolist(), "w": w.tolist()}, open("engine/ranker.json", "w"), indent=1)
        print("saved engine/ranker.json")


if __name__ == "__main__":
    main()
