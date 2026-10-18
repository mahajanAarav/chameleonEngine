"""Code-based quality score (0-100) for one resized design. Dev-only proxy for the AI judge.

Terms (each 0..1, higher is better): overlap, readability, hierarchy, margin, coverage.
Any hard-rule error from tools/check.py forces the score to 0.
"""

import math

from engine.safety import _footprint, is_background
from engine.textmeasure import measure_text
from tools.check import check

WEIGHTS = {"overlap": 0.30, "readability": 0.30, "hierarchy": 0.15, "margin": 0.10, "coverage": 0.15}


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _rect(el: dict) -> tuple[float, float, float, float]:
    """Where the element's ink actually lands (text uses its real wrapped extent)."""
    if el["type"] != "text":
        return _footprint(el)
    m = measure_text(el)
    w = m["max_line_width"]
    align = el.get("text_align", "left")
    x0 = el["x"] + {"center": (el["width"] - w) / 2, "right": el["width"] - w}.get(align, 0)
    return x0, el["y"], x0 + w, el["y"] + m["height"]


def _area(r) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _inter(a, b) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def _is_decoration(el: dict) -> bool:
    return el["type"] == "shape" and not el.get("group_id") and (el.get("opacity", 1) <= 0.35)


def metrics(source: dict, output: dict) -> dict:
    src = {e["id"]: e for e in source["elements"]}
    cw, ch = output["canvas"]["width"], output["canvas"]["height"]
    probs = check(source, output)
    errors = [m for s, m in probs if s == "error"]

    content = []  # (element, rect)
    for el in output["elements"]:
        s = src.get(el["id"], el)
        if is_background(s, source["canvas"]) or _is_decoration(el):
            continue
        content.append((el, _rect(el)))

    # overlap: pairs from different groups, relative to the smaller item
    total = 0.0
    for i in range(len(content)):
        for j in range(i + 1, len(content)):
            (a, ra), (b, rb) = content[i], content[j]
            if a.get("group_id") and a.get("group_id") == b.get("group_id"):
                continue
            small = min(_area(ra), _area(rb))
            if small > 0:
                total += min(1.0, _inter(ra, rb) / small)
    overlap = math.exp(-2 * total)

    # readability: size floor, headline-sized text counts triple
    texts = [(e, src.get(e["id"], e)) for e, _ in content if e["type"] == "text"]
    if texts:
        top = max(s["font_size"] for _, s in texts)
        num = den = 0.0
        for e, s in texts:
            fine = s["font_size"] <= 0.25 * top and s.get("opacity", 1) < 1 or s["font_size"] <= 14 and s.get("opacity", 1) < 1
            lo, hi = (5, 9) if fine else (7, 12)
            wgt = 3.0 if s["font_size"] >= 0.8 * top else 1.0
            num += wgt * _clamp((e["font_size"] - lo) / (hi - lo))
            den += wgt
        readability = num / den
    else:
        readability = 1.0

    # hierarchy: pairs of texts whose size order in the source must survive
    pairs = ok = 0
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            (a, sa), (b, sb) = texts[i], texts[j]
            if sa["font_size"] > 1.1 * sb["font_size"]:
                pairs += 1
                ok += a["font_size"] >= b["font_size"]
            elif sb["font_size"] > 1.1 * sa["font_size"]:
                pairs += 1
                ok += b["font_size"] >= a["font_size"]
    hierarchy = ok / pairs if pairs else 1.0

    # margin and coverage use the main content (not fine print)
    main = [r for e, r in content if src.get(e["id"], e).get("opacity", 1) >= 0.7]
    if main:
        d = min(min(r[0], r[1], cw - r[2], ch - r[3]) for r in main)
        margin = _clamp(d / (0.03 * min(cw, ch)))
        bx = (min(r[0] for r in main), min(r[1] for r in main), max(r[2] for r in main), max(r[3] for r in main))
        coverage = _clamp(_area(bx) / (0.5 * cw * ch))
    else:
        margin = coverage = 0.0

    terms = {"overlap": overlap, "readability": readability, "hierarchy": hierarchy, "margin": margin,
             "coverage": coverage}
    score = 0.0 if errors else 100 * sum(WEIGHTS[k] * v for k, v in terms.items())
    return {"score": score, "errors": errors, "warns": [m for s, m in probs if s == "warn"], **terms}
