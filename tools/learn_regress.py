"""Learn to predict how close each candidate layout is to the designer's, then pick the closest.

    python -m tools.learn_regress [--save] [--lam 30]

Target: distance-to-reference (tools/refdist.py, 0-100) of every candidate. Within each task the values are centred
(we only choose among a task's own candidates), features are standardised, and a ridge regression is fitted. Besides
the score terms it sees which template made the candidate (stack, split, row, spread, grow variants, safety) and the
target shape bucket, plus their interaction, so it can learn "for ultra-wide targets prefer row layouts".
Reported by 5-fold cross-validation over training tasks and on the held-out tasks (never trained on):
the mean distance of the layout it would PICK vs the engine's current pick vs the best candidate (oracle).
"""

import argparse
import json
import random
import statistics

import numpy as np

from tools.learn_ranker import featurise, load_tasks

TEMPLATES = ["safety", "layout_spread", "layout_row", "layout_stack", "layout_split", "layout_stack_grow", "layout_split_grow",
             "layout_anchor"]
BUCKETS = ["ultra-wide", "wide", "square", "tall", "ultra-tall"]


def bucket(w, h):
    r = w / h
    return 0 if r >= 2.5 else 1 if r >= 1.2 else 2 if r > 0.85 else 3 if r > 0.4 else 4


def template_of(name):
    base = name.split("#")[0]
    return TEMPLATES.index(base) if base in TEMPLATES else 0


def size_dev(head_raw, prod_raw, targets, b):
    """How far a candidate's headline and product sizes are from what designers use for this target shape."""
    import math
    return np.array([abs(math.log(max(head_raw, 1e-3) / targets["head"][b])),
                     abs(math.log(max(prod_raw, 1e-3) / targets["prod"][b]))])


def expand(x_std, name, b, dev):
    """Score terms + size deviations + template one-hot + bucket x template interaction."""
    t = np.zeros(len(TEMPLATES))
    t[template_of(name)] = 1.0
    inter = np.zeros(len(BUCKETS) * len(TEMPLATES))
    inter[b * len(TEMPLATES) + template_of(name)] = 1.0
    return np.concatenate([x_std, dev, t, inter])


def learn_targets(tasks, names):
    """Median designer headline / product size per target shape (uncapped, relative to min canvas side)."""
    import collections
    from engine.score import metrics
    ih, ip = names.index("head_raw"), names.index("prod_raw")
    acc = collections.defaultdict(lambda: ([], []))
    for _, t, ref in tasks:
        m = metrics(t["source"], ref)
        b = bucket(t["target"]["width"], t["target"]["height"])
        acc[b][0].append(m["head_raw"])
        acc[b][1].append(m["prod_raw"])
    return {"head": [statistics.median(acc[b][0]) if acc[b][0] else 1.0 for b in range(len(BUCKETS))],
            "prod": [statistics.median(acc[b][1]) if acc[b][1] else 1.0 for b in range(len(BUCKETS))]}


def build(tasks, names, mu, sd, targets):
    rows = []
    ih, ip = names.index("head_raw"), names.index("prod_raw")
    for _, t, ref in tasks:
        r, _ = featurise(t, ref, names)
        b = bucket(t["target"]["width"], t["target"]["height"])
        X = np.array([expand((c["x"] - mu) / sd, c["name"], b, size_dev(c["x"][ih], c["x"][ip], targets, b))
                      for c in r["cands"]])
        y = np.array([c["dist"] for c in r["cands"]])
        rows.append({"X": X, "y": y, "gate": [c["gate"] for c in r["cands"]], "names": [c["name"] for c in r["cands"]],
                     "split": t["split"]})
    return rows


def fit(rows, lam):
    Xs = np.vstack([r["X"] - r["X"].mean(axis=0) for r in rows])
    ys = np.concatenate([r["y"] - r["y"].mean() for r in rows])
    A = Xs.T @ Xs + lam * np.eye(Xs.shape[1])
    return np.linalg.solve(A, Xs.T @ ys)


def pick_idx(row, w):
    pred = row["X"] @ w
    return max(range(len(pred)), key=lambda i: (row["gate"][i][0], row["gate"][i][1], pred[i]))


def evaluate(rows, w, current_w):
    return {"regression pick": statistics.mean(r["y"][pick_idx(r, w)] for r in rows),
            "current pick": statistics.mean(r["y"][pick_idx(r, current_w)] for r in rows),
            "oracle": statistics.mean(r["y"].max() for r in rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--lam", type=float, default=30.0)
    ap.add_argument("--folds", type=int, default=5)
    a = ap.parse_args()

    tr, ho = load_tasks({"train"}), load_tasks({"heldout"})
    _, names = featurise(tr[0][1], tr[0][2])
    first = [featurise(t, ref, names)[0] for _, t, ref in tr]
    allx = np.array([c["x"] for r in first for c in r["cands"]])
    mu, sd = allx.mean(axis=0), allx.std(axis=0) + 1e-6
    targets = learn_targets(tr, names)
    print('designer-typical sizes per shape', {k: [round(x, 2) for x in v] for k, v in targets.items()})
    rows, held = build(tr, names, mu, sd, targets), build(ho, names, mu, sd, targets)
    print(f"{len(rows)} train tasks, {len(held)} held-out tasks, {sum(len(r['y']) for r in rows)} candidate layouts, "
          f"{rows[0]['X'].shape[1]} inputs")

    from engine.score import WEIGHTS
    cur = np.zeros(rows[0]["X"].shape[1])
    cur[:len(names)] = np.array([WEIGHTS.get(k, 0.0) for k in names]) * sd

    idx = list(range(len(rows)))
    random.Random(0).shuffle(idx)
    cv = {"regression pick": [], "current pick": [], "oracle": []}
    for k in range(a.folds):
        test_i = set(idx[k::a.folds])
        w = fit([rows[i] for i in idx if i not in test_i], a.lam)
        ev = evaluate([rows[i] for i in test_i], w, cur)
        for key in cv:
            cv[key].append(ev[key])
    print("\ncross-validated on training tasks:  " + "  ".join(f"{k} {statistics.mean(v):.1f}" for k, v in cv.items()))
    w = fit(rows, a.lam)
    ev = evaluate(held, w, cur)
    print("held-out tasks (never trained on):   " + "  ".join(f"{k} {v:.1f}" for k, v in ev.items()))
    if a.save:
        json.dump({"names": names, "mu": mu.tolist(), "sd": sd.tolist(), "w": w.tolist(), "templates": TEMPLATES,
                   "targets": targets},
                  open("engine/regressor.json", "w"))
        print("saved engine/regressor.json")


if __name__ == "__main__":
    main()
