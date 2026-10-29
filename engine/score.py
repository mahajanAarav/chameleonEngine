"""Code-based quality score (0-100) for one resized design. Dev-only proxy for the AI judge.

Terms (each 0..1, higher is better): overlap, readability, hierarchy, margin, coverage.
Any hard-rule error from tools/check.py forces the score to 0.
"""

import math

from engine.safety import _footprint, is_background
from engine.textmeasure import measure_text
from engine.rules import check
from engine.understand import understand

# Fitted to blind judge picks (tools/fit_weights.py, data/judgments/): 24 designer-reference-vs-engine pairs,
# leave-one-out agreement 83% (the old weights agreed 46% on the same pairs). "fill" alone predicted 88%.
WEIGHTS = {"overlap": 0.03, "readability": 0.07, "hierarchy": 0.07, "margin": 0.04, "coverage": 0.095,
           "logo": 0.04, "cta": 0.095, "headline": 0.055, "product": 0.08,
           "prod_size": 0.105, "cta_size": 0.19, "head_size": 0.045, "fill": 0.06, "deco_clash": 0.03, "wrap": 0.03}


def _tent(r: float, peak: float) -> float:
    """Rises to `peak` (a designer-like size), then falls: bigger is better only up to a point."""
    return r if r <= peak else max(0.0, peak - 2.0 * (r - peak))


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


_RGBA = __import__("re").compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+))?\s*\)")


def _text_readable(output: dict) -> float:
    """Contrast and busyness of the real picture pixels behind each text (1.0 = comfortably readable)."""
    try:
        import numpy as np

        from engine import pixels
    except Exception:
        return 1.0
    imgs = [e for e in output["elements"] if e["type"] == "image"]
    num = den = 0.0
    for e in output["elements"]:
        if e["type"] != "text":
            continue
        rect = _rect(e)
        z = e.get("z_index") or 0
        under = [im for im in imgs if (im.get("z_index") or 0) <= z and _inter(_footprint(im), rect) > 0]
        if not under:
            continue
        top = max(under, key=lambda im: im.get("z_index") or 0)
        res = pixels.luma_under(top.get("asset_id", ""), (top["x"], top["y"], top["width"], top["height"]),
                                top.get("fit", "contain"), rect)
        mt = _RGBA.match(str(e.get("color", "")))
        if res is None or not mt:
            continue
        bg, busy = res
        r, g, b = (float(mt.group(i)) / 255 for i in (1, 2, 3))
        alpha = float(mt.group(4) or 1) * float(e.get("opacity", 1))
        lt = float(pixels.rel_luminance(np.array([r, g, b])))
        eff = alpha * lt + (1 - alpha) * bg
        contrast = (max(eff, bg) + 0.05) / (min(eff, bg) + 0.05)
        score = min(1.0, contrast / 4.5) * (1 - 0.5 * min(1.0, busy / 0.08))
        num += e["font_size"] * score
        den += e["font_size"]
    return num / den if den else 1.0


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

    # brand/size terms: logo, button and headline keep their size relative to the canvas
    out_by_id = {e["id"]: e for e in output["elements"]}
    design = understand(source)
    sw, sh = source["canvas"]["width"], source["canvas"]["height"]

    def rel_area(role):
        us = design.by_role(role)
        if not us:
            return 1.0
        u = us[0]
        boxes = [_rect(out_by_id[m["id"]]) for m in u.members if m["id"] in out_by_id]
        if not boxes:
            return 0.0
        a_out = _area((min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                       max(b[3] for b in boxes)))
        return (a_out / (cw * ch)) / max(u.w * u.h / (sw * sh), 1e-9)

    heads = design.by_role("headline")
    if heads and heads[0].members[0]["id"] in out_by_id:
        hm = heads[0].members[0]
        head_rel = (out_by_id[hm["id"]]["font_size"] / min(cw, ch)) / (hm["font_size"] / min(sw, sh))
    else:
        head_rel = 1.0
    cta_role = "cta" if design.by_role("cta") else "cta_text"

    # absolute prominence (not relative to the source, not capped early): what blind judges rewarded
    def frac(role):
        us = design.by_role(role)
        boxes = [_rect(out_by_id[m["id"]]) for u in us[:1] for m in u.members if m["id"] in out_by_id]
        if not boxes:
            return None
        return _area((min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                      max(b[3] for b in boxes))) / (cw * ch)

    pf, cf = frac("product"), frac(cta_role)
    prod_size = 1.0 if pf is None else _tent(math.sqrt(pf) / 0.5, 1.2)
    cta_size = 1.0 if cf is None else _tent(math.sqrt(cf) / 0.25, 1.4)
    prod_raw = 1.0 if pf is None else math.sqrt(pf) / 0.5  # uncapped sizes for the learned picker
    head_raw = 1.0
    if heads and heads[0].members[0]["id"] in out_by_id:
        head_raw = out_by_id[heads[0].members[0]["id"]]["font_size"] / min(cw, ch) / 0.08
    head_size = 1.0
    if heads and heads[0].members[0]["id"] in out_by_id:
        head_size = _tent(out_by_id[heads[0].members[0]["id"]]["font_size"] / min(cw, ch) / 0.08, 1.5)
    body = [r for e, r in content if src.get(e["id"], e).get("opacity", 1) >= 0.7]
    fill = _tent(math.sqrt(sum(_area(r) for r in body) / (cw * ch)) / 0.6, 1.45)
    deco_ids = {m["id"] for u in design.by_role("decoration") for m in u.members}
    clash = 0.0
    for did in deco_ids:
        if did not in out_by_id:
            continue
        dr = _rect(out_by_id[did])
        for e, r in content:
            if _area(r) > 0 and e["type"] in ("text", "image"):
                clash += _inter(dr, r) / _area(r)
    deco_clash = math.exp(-3 * clash)
    # the spotlight keeps its share of the canvas (1.0 = as big a share as in the source)
    heroes = design.heroes()
    hero_ratio = 1.0
    if heroes:
        src_share = sum(_area(u.bbox) for u in heroes) / (sw * sh)
        rects = [_rect(out_by_id[m_["id"]]) for u in heroes for m_ in u.members if m_["id"] in out_by_id]
        if rects and src_share > 0:
            out_share = _area((min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects),
                               max(r[3] for r in rects))) / (cw * ch)
            hero_ratio = min(1.5, out_share / src_share)

    # design conventions: where things sit, balance, breathing room, headline lines, reading order
    def centre(role):
        us = design.by_role(role)
        rs = [_rect(out_by_id[m["id"]]) for u in us[:1] for m in u.members if m["id"] in out_by_id]
        if not rs:
            return None
        return ((min(r[0] for r in rs) + max(r[2] for r in rs)) / 2 / cw, (min(r[1] for r in rs) + max(r[3] for r in rs)) / 2 / ch)

    lc, pc = centre("logo"), centre("product")
    logo_cy = 0.5 if lc is None else lc[1]
    logo_cx_off = 0.0 if lc is None else abs(lc[0] - 0.5)
    prod_cx_off = 0.0 if pc is None else abs(pc[0] - 0.5)
    prod_cy_off = 0.0 if pc is None else abs(pc[1] - 0.5)
    if body:
        tot = sum(_area(r) for r in body) or 1.0
        cent_dx = abs(sum((r[0] + r[2]) / 2 * _area(r) for r in body) / tot / cw - 0.5)
        cent_dy = abs(sum((r[1] + r[3]) / 2 * _area(r) for r in body) / tot / ch - 0.5)
    else:
        cent_dx = cent_dy = 0.0
    gaps = []
    for i in range(len(body)):
        for j in range(i + 1, len(body)):
            a, b = body[i], body[j]
            dx, dy = max(a[0] - b[2], b[0] - a[2]), max(a[1] - b[3], b[1] - a[3])
            if max(dx, dy) > 0:
                gaps.append(max(dx, dy))
    min_gap = min(0.15, (min(gaps) if gaps else 0.15 * min(cw, ch)) / min(cw, ch))
    head_lines = 1.0
    if heads and heads[0].members[0]["id"] in out_by_id:
        head_lines = float(min(4, measure_text(out_by_id[heads[0].members[0]["id"]])["n_lines"]))
    flow = [(u, centre(u.role)) for u in design.units
            if u.role in ("logo", "product", "headline", "supporting", "cta", "cta_text") and centre(u.role)]
    axis = 0 if cw / ch > 1.8 else 1
    agree_pairs = total_pairs = 0
    for i in range(len(flow)):
        for j in range(i + 1, len(flow)):
            (ua, ca), (ub, cb) = flow[i], flow[j]
            if ua.order != ub.order and ca[axis] != cb[axis]:
                total_pairs += 1
                agree_pairs += (ua.order < ub.order) == (ca[axis] < cb[axis])
    order = agree_pairs / total_pairs if total_pairs else 1.0

    # widows: a wrapped text whose last line is a short orphan looks accidental
    widows = 0
    for e, _ in content:
        if e["type"] == "text" and len(str(e.get("content", "")).split()) >= 3:
            m = measure_text(e)
            if m["n_lines"] >= 2:
                last = m["lines"][-1]
                lw = measure_text(dict(e, content=last), None, 1e9)["max_line_width"]
                widows += lw < 0.3 * m["max_line_width"]
    wrap = math.exp(-1.2 * widows)
    terms = {"overlap": overlap, "readability": readability, "hierarchy": hierarchy, "margin": margin,
             "coverage": coverage, "logo": _clamp(rel_area("logo") / 0.6),
             "cta": _clamp(rel_area(cta_role) / 0.5), "headline": _clamp(head_rel / 0.7),
             "product": _clamp(rel_area("product") / 0.6), "prod_size": prod_size, "cta_size": cta_size,
             "head_size": head_size, "fill": fill, "deco_clash": deco_clash, "wrap": wrap,
             "logo_cy": logo_cy, "logo_cx_off": logo_cx_off, "prod_cx_off": prod_cx_off, "prod_cy_off": prod_cy_off,
             "cent_dx": cent_dx, "cent_dy": cent_dy, "min_gap": min_gap, "head_lines": head_lines, "order": order,
             "prod_raw": prod_raw, "head_raw": head_raw, "hero_ratio": hero_ratio,
             "text_readable": _text_readable(output)}
    score = 0.0 if errors else 100 * sum(WEIGHTS[k] * terms[k] for k in WEIGHTS)
    return {"score": score, "errors": errors, "warns": [m for s, m in probs if s == "warn"], **terms}
