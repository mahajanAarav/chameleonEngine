"""Distance to a reference ("perfect") layout. Proxy for Adobe's coordinate-based grading.

ref_score(source, output, reference) -> 0..100, higher = closer. Per element we compare
the ink box (normalised by canvas size) with IoU, the centre offset, and for text the
font-size ratio. Elements are weighted by role importance so logo/headline/button count most.
"""

import math

from engine.score import _area, _inter, _rect
from engine.understand import understand


def _norm(rect, cw, ch):
    return rect[0] / cw, rect[1] / ch, rect[2] / cw, rect[3] / ch


def _iou(a, b):
    inter = _inter(a, b)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def element_scores(source: dict, output: dict, reference: dict) -> dict:
    cw, ch = output["canvas"]["width"], output["canvas"]["height"]
    out = {e["id"]: e for e in output["elements"]}
    ref = {e["id"]: e for e in reference["elements"]}
    weights = {}
    for u in understand(source).units:
        for m in u.members:
            weights[m["id"]] = max(u.importance, 0.05)
    res = {}
    for eid, r in ref.items():
        o = out.get(eid)
        if o is None:
            res[eid] = (0.0, weights.get(eid, 0.5))
            continue
        ro, rr = _norm(_rect(o), cw, ch), _norm(_rect(r), cw, ch)
        iou = _iou(ro, rr)
        d = math.hypot((ro[0] + ro[2]) / 2 - (rr[0] + rr[2]) / 2, (ro[1] + ro[3]) / 2 - (rr[1] + rr[3]) / 2)
        centre = max(0.0, 1 - d / 0.25)  # 25% of the canvas away counts as fully off
        s = 0.5 * iou + 0.3 * centre
        if o["type"] == "text":
            fs = max(0.0, 1 - abs(math.log(max(o["font_size"], 1) / max(r["font_size"], 1))) / math.log(2))
            s += 0.2 * fs
        else:
            s += 0.2 * iou
        res[eid] = (s, weights.get(eid, 0.5))
    return res


def ref_score(source: dict, output: dict, reference: dict) -> float:
    res = element_scores(source, output, reference)
    tot = sum(w for _, w in res.values())
    return 100 * sum(s * w for s, w in res.values()) / tot if tot else 0.0
