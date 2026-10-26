"""Learned picker: predicts how close a candidate layout is to what a designer would make.

Weights live in engine/regressor.json (written by tools/learn_regress.py from the designer reference layouts in
data/refs). Inputs: the standardised score terms, which template produced the candidate, the target shape bucket
and their interaction. If the file is missing the engine silently falls back to the hand-set score.
"""

import json
import math
from pathlib import Path

import numpy as np

_PATH = Path(__file__).with_name("regressor.json")
BUCKETS = 5


def bucket(w: float, h: float) -> int:
    r = w / h
    return 0 if r >= 2.5 else 1 if r >= 1.2 else 2 if r > 0.85 else 3 if r > 0.4 else 4


class Picker:
    def __init__(self, cfg: dict):
        self.names = cfg["names"]
        self.mu = np.array(cfg["mu"])
        self.sd = np.array(cfg["sd"])
        self.w = np.array(cfg["w"])
        self.templates = cfg["templates"]
        self.targets = cfg.get("targets")

    @classmethod
    def load(cls):
        try:
            return cls(json.loads(_PATH.read_text()))
        except Exception:
            return None

    def predict(self, m: dict, name: str, w: float, h: float) -> float:
        x = (np.array([m[k] for k in self.names]) - self.mu) / self.sd
        T = len(self.templates)
        b = bucket(w, h)
        dev = np.zeros(2)
        if self.targets:
            dev = np.array([abs(math.log(max(m["head_raw"], 1e-3) / self.targets["head"][b])),
                            abs(math.log(max(m["prod_raw"], 1e-3) / self.targets["prod"][b]))])
        base = name.split("#")[0]
        t = np.zeros(T)
        inter = np.zeros(BUCKETS * T)
        if base in self.templates:  # a plug-in proposal has no template one-hot
            i = self.templates.index(base)
            t[i] = 1.0
            inter[bucket(w, h) * T + i] = 1.0
        return float(np.concatenate([x, dev, t, inter]) @ self.w)
