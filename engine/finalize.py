"""Last-chance repair: make every text and shape fit the canvas, however odd the input.

Runs on the layout the engine is about to return (and on the safety net). It only touches elements that actually
break a rule, so good layouts pass through unchanged:
  * a word wider than its box (URLs, long names), or wrapped text taller than the canvas -> widen the box up to the
    canvas, then search for the biggest whole-number font size that fits
  * rotated text -> measured box, then shrink and shift until its rotated footprint is inside
  * anything else still outside -> shift, then shrink about its centre
"""

from engine.safety import _footprint
from engine.textfit import fit_size
from engine.textmeasure import measure_text

TOL = 0.5


def _inside(el, tw, th):
    x0, y0, x1, y1 = _footprint(el)
    return x0 >= -TOL and y0 >= -TOL and x1 <= tw + TOL and y1 <= th + TOL


def _ink_inside(e, tw, th):
    """Rotated text: is the wrapped text itself (not just its box) inside the canvas?"""
    from engine.rules import _rotated_ink
    m = measure_text(e)
    align = e.get("text_align", "left")
    ix0 = e["x"] + {"center": (e["width"] - m["max_line_width"]) / 2, "right": e["width"] - m["max_line_width"]}.get(align, 0)
    x0, y0, x1, y1 = _rotated_ink(e, ix0, e["y"], ix0 + m["max_line_width"], e["y"] + m["height"])
    return x0 >= -TOL and y0 >= -TOL and x1 <= tw + TOL and y1 <= th + TOL, (x0, y0, x1, y1)


def _fix_text(e, tw, th):
    m = measure_text(e)
    ink = m["max_line_width"]
    if e.get("rotation"):
        for _ in range(80):
            m = measure_text(e)
            e["height"] = m["height"]  # rotate about the middle of the real text, not of an arbitrary box
            e["width"] = max(e["width"], m["max_line_width"])
            ok, (x0, y0, x1, y1) = _ink_inside(e, tw, th)
            if ok:
                return
            if x1 - x0 <= tw and y1 - y0 <= th:  # it fits, just in the wrong place
                e["x"] += -min(0.0, x0) - max(0.0, x1 - tw)
                e["y"] += -min(0.0, y0) - max(0.0, y1 - th)
                if _ink_inside(e, tw, th)[0]:
                    return
            if e["font_size"] <= 1:
                return
            e["font_size"] = max(1, int(round(e["font_size"] * 0.9)) if e["font_size"] > 2 else 1)
            e["width"] *= 0.9
    fits = (ink <= e["width"] + TOL and e["x"] >= -TOL and e["x"] + e["width"] <= tw + TOL and e["y"] >= -TOL
            and e["y"] + m["height"] <= th + TOL)
    if fits:
        return
    width = min(max(e["width"], 1.0), tw)
    size, m, ok = fit_size(e, width, th, e["font_size"], min_size=1)
    if not ok:  # a long word needs more room than the box gave it
        size, m, ok = fit_size(e, tw, th, e["font_size"], min_size=1)
        width = tw if ok else width
    e["font_size"] = size
    e["width"] = width
    e["height"] = m["height"]
    e["x"] = min(max(e["x"], 0.0), max(0.0, tw - width))
    e["y"] = min(max(e["y"], 0.0), max(0.0, th - m["height"]))


def _shift_inside(e, tw, th):
    x0, y0, x1, y1 = _footprint(e)
    dx = -min(0.0, x0) - max(0.0, x1 - tw)
    dy = -min(0.0, y0) - max(0.0, y1 - th)
    e["x"] += dx
    e["y"] += dy


def _fix_other(e, tw, th):
    if _inside(e, tw, th):
        return
    _shift_inside(e, tw, th)
    if _inside(e, tw, th):
        return
    x0, y0, x1, y1 = _footprint(e)
    bw, bh = x1 - x0, y1 - y0
    k = min(1.0, tw / bw if bw > 1e-6 else 1.0, th / bh if bh > 1e-6 else 1.0)
    cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
    e["width"] *= k
    e["height"] *= k
    e["x"], e["y"] = cx - e["width"] / 2, cy - e["height"] / 2
    if "corner_radius" in e:
        e["corner_radius"] *= k
    _shift_inside(e, tw, th)


def finalize(layout: dict) -> dict:
    tw, th = layout["canvas"]["width"], layout["canvas"]["height"]
    for e in layout["elements"]:
        try:
            if e["type"] == "text":
                _fix_text(e, tw, th)
            else:
                _fix_other(e, tw, th)
        except Exception:
            continue  # never let a repair step crash the engine
        for k in ("x", "y", "width", "height", "corner_radius"):
            if k in e:
                e[k] = round(e[k], 2)
    return layout
