"""Last-chance repair: make every text and shape fit the canvas, however odd the input.

Runs on the layout the engine is about to return (and on the safety net). It only touches elements that actually
break a rule, so good layouts pass through unchanged:
  * text whose ink would leave the canvas (a very long word, wrapped text taller than the canvas) -> widen the box up
    to the canvas, then search for the biggest whole-number font size that fits
  * rotated text -> give it the canvas side it runs along, take the biggest font that fits, then shift it inside
  * anything else still outside -> shift, then shrink about its centre
Text that merely overflows its own box but stays on the canvas is left alone (the rules only ask for the canvas).
"""

from engine.safety import _footprint
from engine.textfit import fit_size
from engine.textmeasure import measure_text

TOL = 0.5


def _inside(el, tw, th):
    x0, y0, x1, y1 = _footprint(el)
    return x0 >= -TOL and y0 >= -TOL and x1 <= tw + TOL and y1 <= th + TOL


def _ink_inside(e, tw, th):
    """Is the wrapped text itself (turned about its box centre if rotated) inside the canvas? Also returns its box."""
    from engine.rules import _rotated_ink

    m = measure_text(e)
    align = e.get("text_align", "left")
    ink = m["max_line_width"]
    ix0 = e["x"] + {"center": (e["width"] - ink) / 2, "right": e["width"] - ink}.get(align, 0)
    box = (ix0, e["y"], ix0 + ink, e["y"] + m["height"])
    if e.get("rotation"):
        box = _rotated_ink(e, *box)
    x0, y0, x1, y1 = box
    return x0 >= -TOL and y0 >= -TOL and x1 <= tw + TOL and y1 <= th + TOL, box


def _shift_inside(e, tw, th):
    x0, y0, x1, y1 = _footprint(e)
    e["x"] += -min(0.0, x0) - max(0.0, x1 - tw)
    e["y"] += -min(0.0, y0) - max(0.0, y1 - th)


def _fix_rotated_text(e, tw, th):
    r = abs(e["rotation"]) % 180
    if abs(r - 90) < 1.0:
        run, across = th, tw
    elif r < 1.0 or abs(r - 180) < 1.0:
        run, across = tw, th
    else:
        run = across = 0.7 * min(tw, th)
    size, m, _ = fit_size(e, run, across, e["font_size"], min_size=1)
    e["font_size"] = size
    e["width"] = run  # exactly the width the size search measured with, so the wrap cannot change
    e["height"] = measure_text(e)["height"]
    for _ in range(3):
        ok, (x0, y0, x1, y1) = _ink_inside(e, tw, th)
        if ok:
            return
        e["x"] += -min(0.0, x0) - max(0.0, x1 - tw)
        e["y"] += -min(0.0, y0) - max(0.0, y1 - th)


def _fix_text(e, tw, th):
    if _ink_inside(e, tw, th)[0]:
        return  # the text is on the canvas: all the rules ask, so leave the layout alone
    if e.get("rotation"):
        _fix_rotated_text(e, tw, th)
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
