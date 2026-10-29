"""
THIS IS THE FILE YOU IMPLEMENT.

Everything else in this repo (input loading, output writing, rendering,
the Dockerfile) is plumbing so you can focus on exactly one function:
`resize()`. See RULES.md and the design schema for the full contract.
"""

from typing import Any

from engine.safety import safety_resize


def _baseline_stretch(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """Original starter baseline (non-uniform stretch). Last-resort fallback only."""
    scale_x = target_canvas["width"] / source["canvas"]["width"]
    scale_y = target_canvas["height"] / source["canvas"]["height"]

    out_elements = []
    for el in source["elements"]:
        el = dict(el)
        el["x"] = el["x"] * scale_x
        el["y"] = el["y"] * scale_y
        el["width"] = el["width"] * scale_x
        el["height"] = el["height"] * scale_y
        if el["type"] == "text":
            el["font_size"] = max(1.0, el["font_size"] * min(scale_x, scale_y))
        out_elements.append(el)

    return {
        "canvas": {"width": target_canvas["width"], "height": target_canvas["height"]},
        "elements": out_elements,
    }


def _round(el: dict) -> dict:
    for k in ("x", "y", "width", "height", "corner_radius"):
        if k in el:
            el[k] = round(el[k], 2)
    return el


OVERLAP_OK = 0.85  # overlap term at or above this counts as collision-free
COLLAGE_MIN = 4  # this many separate pictures (not touching) make a collage
HERO_FRAC = 0.5  # the spotlight must keep at least this fraction of the best share any clean layout gives it
HERO_FRAC_DOMINANT = 0.8  # ... and this much when it dominates the source design (the point of the ad)
HERO_DOMINANT_SHARE = 0.33  # a spotlight covering at least this share of the source canvas counts as dominant
LOGO_OK = 0.45  # logo term at or above this counts as a clearly visible logo (about 27% of its original relative area)


def candidates(source: dict[str, Any], target_canvas: dict[str, Any]) -> list:
    """All candidate layouts as (name, output). Index 0 is always the safety net."""
    from engine.layout import (GROW_SPLIT_PARAMS, GROW_STACK_PARAMS, ROW_PARAMS, ROW_TIGHT_PARAMS, SPLIT_PARAMS,
                               SPLIT_WIDE_PARAMS, SPREAD_PARAMS, STACK_PARAMS, STACK_TIGHT_PARAMS, layout_row, layout_split, layout_split_grow, layout_spread,
                               layout_stack, layout_stack_grow)
    from engine.understand import understand

    tw, th = target_canvas["width"], target_canvas["height"]
    canvas = {"width": tw, "height": th}
    from engine.finalize import finalize

    cands = [("safety", finalize(safety_resize(source, target_canvas)))]

    design = understand(source)
    templates = [(layout_spread, SPREAD_PARAMS)]
    # a collage (several separate pictures) only works as its original composition, scaled
    collage = len([u for u in design.units if u.role in ("product", "image")]) >= COLLAGE_MIN
    if not collage:
        if tw / th >= 2.5:
            templates.append((layout_row, ROW_PARAMS + ROW_TIGHT_PARAMS))
        if tw / th <= 1.6:
            templates.append((layout_stack, STACK_PARAMS + STACK_TIGHT_PARAMS))
            templates.append((layout_stack_grow, GROW_STACK_PARAMS))
        if 1.0 <= tw / th <= 3.0:
            templates.append((layout_split, SPLIT_PARAMS + SPLIT_WIDE_PARAMS))
            templates.append((layout_split_grow, GROW_SPLIT_PARAMS))
    ids = {e["id"] for e in source["elements"]}
    for fn, params in templates:
        for pi, P in enumerate(params):
            try:
                placed = fn(design, tw, th, P)
            except Exception:
                placed = None
            if placed and set(placed) == ids:
                cands.append((f"{fn.__name__}#{pi}",
                              {"canvas": canvas, "elements": [_round(placed[e["id"]]) for e in source["elements"]]}))
    try:  # layouts suggested by any plugged-in model (none ship with the engine)
        from engine.proposer import propose
        cands += propose(source, target_canvas)
    except Exception:
        pass
    return cands


def _smart(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """Keep the best-scoring candidate. The safety net is always a candidate, so the result is
    never worse than it by our own score."""
    from engine.score import metrics

    try:  # learned from designer references; any problem (missing numpy or file) -> hand-set score
        from engine.picker import Picker
        picker = Picker.load()
    except Exception:
        picker = None
    tw, th = target_canvas["width"], target_canvas["height"]

    # collisions are the judge's first criterion, then a clearly visible logo (brand), then our score;
    # a layout that fails a gate only wins if no candidate passes it
    scored = []
    for name, c in candidates(source, target_canvas):
        m = metrics(source, c)
        if m["errors"]:  # a layout that breaks a hard rule is never eligible, whatever else it scores
            continue
        scored.append((name, c, m))
    # the spotlight image must keep close to the biggest share any clean layout can give it
    best_hero = max((m["hero_ratio"] for _, _, m in scored if m["overlap"] >= OVERLAP_OK), default=0.0)
    from engine.understand import understand
    sw, sh = source["canvas"]["width"], source["canvas"]["height"]
    hero_area = sum(max(0.0, u.bbox[2] - u.bbox[0]) * max(0.0, u.bbox[3] - u.bbox[1]) for u in understand(source).heroes())
    frac = HERO_FRAC_DOMINANT if hero_area / (sw * sh) >= HERO_DOMINANT_SHARE else HERO_FRAC
    best, best_key = None, (-1, -1, -1, -1.0)
    for name, c, m in scored:
        value = picker.predict(m, name, tw, th) if picker else m["score"]
        key = (m["overlap"] >= OVERLAP_OK, m["logo"] >= LOGO_OK, m["hero_ratio"] >= frac * best_hero, value)
        if key > best_key:
            best, best_key = c, key
    return best if best is not None else safety_resize(source, target_canvas)


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """
    Args:
        source: {"canvas": {"width": int, "height": int}, "elements": [...]}
        target_canvas: {"width": int, "height": int}

    Returns:
        {"canvas": target_canvas, "elements": [...]} with the same element ids.

    Hard rules: same ids, nothing off-canvas (rotation included), images keep
    their aspect ratio, text content/font family untouched, no pixel changes.
    Never raises: falls back to simpler strategies on any error.
    """
    from engine.finalize import finalize

    try:
        return finalize(_smart(source, target_canvas))
    except Exception:
        pass
    try:
        return finalize(safety_resize(source, target_canvas))
    except Exception:
        return _baseline_stretch(source, target_canvas)
