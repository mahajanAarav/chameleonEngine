"""Strict rule checker for engine output (stricter than engine/main.py's self_check).
Used by the engine to reject bad candidates and by tools/.

check(source, output) -> list of (severity, message); severity is "error"
(breaks a hard rule) or "warn" (probably hurts the judge's score).
"""

import math

from engine.safety import _footprint
from engine.textmeasure import measure_text

TOL = 0.5
ASPECT_TOL = 0.05
MIN_FONT_WARN = 10  # below this, text is hard to read

REQUIRED_COMMON = ["id", "type", "x", "y", "width", "height"]
REQUIRED_BY_TYPE = {
    "text": ["content", "font_family", "font_size", "color"],
    "image": ["asset_id"],
    "shape": ["shape_type", "fill_color"],
}
UNCHANGED = ["type", "opacity", "z_index", "group_id", "rotation", "style_runs"]
UNCHANGED_TEXT = ["content", "font_family", "font_weight", "font_style", "color", "text_align"]


def _off(a0: float, a1: float, tol: float) -> bool:
    """Do two aspect ratios differ by more than tol? Degenerate (zero or infinite) shapes are never flagged."""
    import math
    if not (math.isfinite(a0) and math.isfinite(a1)) or a0 <= 0 or a1 <= 0:
        return False
    return abs(a1 / a0 - 1) > tol


def _rotated_ink(el: dict, x0: float, y0: float, x1: float, y1: float):
    """Bounding box of the ink rectangle (x0,y0)-(x1,y1) turned about the centre of the element's box."""
    a = math.radians(el.get("rotation") or 0)
    c, s = math.cos(a), math.sin(a)
    cx, cy = el["x"] + el["width"] / 2, el["y"] + el["height"] / 2
    pts = [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x in (x0, x1) for y in (y0, y1)]
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def _aspect(el: dict) -> float:
    return el["width"] / el["height"] if el["height"] else float("inf")


def _finite(el: dict) -> bool:
    return all(isinstance(el.get(k), (int, float)) and math.isfinite(el[k]) for k in ("x", "y", "width", "height"))


def check(source: dict, output: dict) -> list[tuple[str, str]]:
    probs: list[tuple[str, str]] = []

    def err(m): probs.append(("error", m))
    def warn(m): probs.append(("warn", m))

    if "canvas" not in output or "elements" not in output:
        return [("error", "missing canvas or elements")]
    cw, ch = output["canvas"]["width"], output["canvas"]["height"]

    src = {e["id"]: e for e in source["elements"]}
    out_ids = [e.get("id") for e in output["elements"]]
    if len(out_ids) != len(set(out_ids)):
        err("duplicate element ids")
    if set(out_ids) != set(src):
        err(f"id mismatch: missing {sorted(set(src) - set(out_ids))}, extra {sorted(set(out_ids) - set(src))}")

    for el in output["elements"]:
        eid = el.get("id")
        s = src.get(eid)
        miss = [f for f in REQUIRED_COMMON + REQUIRED_BY_TYPE.get(el.get("type"), []) if f not in el]
        if miss:
            err(f"{eid}: missing fields {miss}")
            continue
        if not _finite(el) or el["width"] < 0 or el["height"] < 0:
            err(f"{eid}: non-finite or negative geometry")
            continue
        if s is None:
            continue

        # fields the engine must not change
        for f in UNCHANGED + (UNCHANGED_TEXT if el["type"] == "text" else []):
            if s.get(f) != el.get(f):
                (err if f in ("content", "font_family") else warn)(f"{eid}: '{f}' changed")

        # on canvas, rotation included. Text is checked at its real wrapped height below.
        x0, y0, x1, y1 = _footprint(el)
        if el["type"] != "text" and (x0 < -TOL or y0 < -TOL or x1 > cw + TOL or y1 > ch + TOL):
            err(f"{eid}: off-canvas ({x0:.1f},{y0:.1f})-({x1:.1f},{y1:.1f}) in {cw}x{ch}")

        if el["type"] == "image":
            fit = el.get("fit", "contain")
            if fit == "fill":
                err(f"{eid}: fit=fill distorts the image")
            if fit != "cover" and s.get("fit", "contain") != "cover" and s["height"] and el["height"]:
                a0, a1 = _aspect(s), _aspect(el)
                if _off(a0, a1, ASPECT_TOL):
                    err(f"{eid}: image aspect {a1:.3f} vs source {a0:.3f}")

        if el["type"] == "shape" and s["height"] and el["height"]:
            a0, a1 = _aspect(s), _aspect(el)
            if (s.get("shape_type") == "ellipse" or s.get("corner_radius")) and _off(a0, a1, 0.25):
                warn(f"{eid}: shape distorted (aspect {a1:.2f} vs {a0:.2f})")

        if el["type"] == "text":
            if el["font_size"] < 1:
                err(f"{eid}: font_size < 1")
                continue
            if el["font_size"] < MIN_FONT_WARN:
                warn(f"{eid}: font_size {el['font_size']:.1f} is hard to read")
            m = measure_text(el)
            tx0, ty0 = el["x"], el["y"]
            ty1 = ty0 + m["height"]
            if m["max_line_width"] > el["width"] + TOL:
                warn(f"{eid}: a word is wider than the box ({m['max_line_width']:.0f} > {el['width']:.0f})")
            # horizontal extent of the actual ink, honouring alignment
            align = el.get("text_align", "left")
            if align == "center":
                ix0 = tx0 + (el["width"] - m["max_line_width"]) / 2
            elif align == "right":
                ix0 = tx0 + el["width"] - m["max_line_width"]
            else:
                ix0 = tx0
            ix1 = ix0 + m["max_line_width"]
            if el.get("rotation"):  # the text turns about the middle of its box: test where it really lands
                ix0, ty0, ix1, ty1 = _rotated_ink(el, ix0, ty0, ix1, ty1)
            if ix0 < -TOL or ix1 > cw + TOL or ty0 < -TOL or ty1 > ch + TOL:
                err(f"{eid}: wrapped text runs off-canvas (text bottom {ty1:.1f} of {ch})")

    return probs


def summarize(probs: list[tuple[str, str]]) -> tuple[int, int]:
    return (sum(1 for s, _ in probs if s == "error"), sum(1 for s, _ in probs if s == "warn"))
