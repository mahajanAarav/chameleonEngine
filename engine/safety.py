"""Safety net: always-valid resize with no stretching.

One uniform scale, centred; the background covers the canvas; every unit
(a group, or a lone element) is shrunk/shifted until its rotated footprint is
fully inside the canvas. The engine only outputs numbers.
"""

import copy
import math
from typing import Any

EPS = 1e-6


def _footprint(el: dict) -> tuple[float, float, float, float]:
    """Axis-aligned box (x0, y0, x1, y1) of the element after rotation about its centre."""
    w, h = el["width"], el["height"]
    cx, cy = el["x"] + w / 2, el["y"] + h / 2
    a = math.radians(el.get("rotation") or 0)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    hw, hh = (w * c + h * s) / 2, (w * s + h * c) / 2
    return cx - hw, cy - hh, cx + hw, cy + hh


def is_background(el: dict, canvas: dict) -> bool:
    """Image covering (almost) the whole canvas."""
    if el.get("type") != "image":
        return False
    area = el["width"] * el["height"]
    return (
        area >= 0.9 * canvas["width"] * canvas["height"]
        and el["x"] <= 0.02 * canvas["width"]
        and el["y"] <= 0.02 * canvas["height"]
    )


def _units(elements: list[dict]) -> list[list[dict]]:
    """Grouped elements travel together; everything else is its own unit."""
    groups: dict[str, list[dict]] = {}
    units: list[list[dict]] = []
    for el in elements:
        gid = el.get("group_id")
        if gid:
            if gid not in groups:
                groups[gid] = []
                units.append(groups[gid])
            groups[gid].append(el)
        else:
            units.append([el])
    return units


def _fit_unit(unit: list[dict], tw: float, th: float) -> None:
    """Shrink (about the unit centre) then shift so the unit's footprint is inside the canvas."""
    boxes = [_footprint(e) for e in unit]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    bw, bh = x1 - x0, y1 - y0
    if bw <= EPS or bh <= EPS:
        k = 1.0
    else:
        k = min(1.0, tw / bw, th / bh)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ncx = min(max(cx, bw * k / 2), tw - bw * k / 2)
    ncy = min(max(cy, bh * k / 2), th - bh * k / 2)
    for e in unit:
        ecx, ecy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
        ecx = ncx + (ecx - cx) * k
        ecy = ncy + (ecy - cy) * k
        e["width"] *= k
        e["height"] *= k
        e["x"] = ecx - e["width"] / 2
        e["y"] = ecy - e["height"] / 2
        if e["type"] == "text":
            e["font_size"] = max(1, int(round(e["font_size"] * k)))
        if e["type"] == "shape" and "corner_radius" in e:
            e["corner_radius"] *= k


def safety_resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    sw, sh = source["canvas"]["width"], source["canvas"]["height"]
    tw, th = target_canvas["width"], target_canvas["height"]
    s = min(tw / sw, th / sh)
    ox, oy = (tw - sw * s) / 2, (th - sh * s) / 2

    elements = copy.deepcopy(source["elements"])
    movable = []
    for el in elements:
        if is_background(el, source["canvas"]):
            el["x"], el["y"], el["width"], el["height"] = 0, 0, tw, th
            if el.get("fit") != "cover":
                el["fit"] = "cover"
            continue
        el["x"] = ox + el["x"] * s
        el["y"] = oy + el["y"] * s
        el["width"] *= s
        el["height"] *= s
        if el["type"] == "text":
            el["font_size"] = max(1, int(round(el["font_size"] * s)))
        if el["type"] == "shape" and "corner_radius" in el:
            el["corner_radius"] *= s
        movable.append(el)

    for unit in _units(movable):
        _fit_unit(unit, tw, th)

    for el in elements:
        for k in ("x", "y", "width", "height"):
            el[k] = round(el[k], 2)
        if "corner_radius" in el:
            el["corner_radius"] = round(el["corner_radius"], 2)

    return {"canvas": {"width": tw, "height": th}, "elements": elements}
