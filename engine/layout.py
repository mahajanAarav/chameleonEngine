"""Layout templates. Each returns {element_id: new_element} or None if it can't work.

layout_row: wide banners. Columns left to right: logo, product, text (headline,
supporting text, plain button text), badges, ribbon/other, button. Fine print and
the watermark share a thin strip along the bottom. Decoration keeps its shape.
"""

import copy

from engine.textfit import fit_size, fit_stack
from engine.textmeasure import measure_text
from engine.understand import Design

CAP_CENTER = 0.72  # cap-height centre of top-anchored text, in font sizes below the box top


# ---------- small builders (all return new dicts; the source is never touched) ----------

def _image(unit, h_max, w_max):
    src = unit.members[0]
    k = min(w_max / src["width"], h_max / src["height"])
    e = copy.deepcopy(src)
    e["width"], e["height"], e["x"], e["y"] = src["width"] * k, src["height"] * k, 0.0, 0.0
    return e


def _pill(unit, h):
    """Rounded shape + one label, rebuilt at height h (label font from h, width from the label)."""
    shape = next(m for m in unit.members if m["type"] == "shape")
    label = next(m for m in unit.members if m["type"] == "text")
    fs = max(6, int(h * 0.42))
    w = measure_text(label, fs, 10000)["max_line_width"] + 1.1 * h
    s, t = copy.deepcopy(shape), copy.deepcopy(label)
    ratio = (shape.get("corner_radius") or 0) / max(shape["height"], 1e-6)
    s.update(width=w, height=h, x=0.0, y=0.0)
    if "corner_radius" in s:
        s["corner_radius"] = ratio * h
    t.update(font_size=fs, width=w, x=0.0, y=h / 2 - CAP_CENTER * fs)
    t["height"] = measure_text(t, fs, w)["height"]
    return [s, t], w


def _is_simple_pill(unit):
    kinds = [m["type"] for m in unit.members]
    return kinds.count("shape") == 1 and kinds.count("text") == 1 and len(kinds) == 2


def _xform(unit, k, cx, cy):
    """Scale a unit uniformly by k about its centre and move that centre to (cx, cy)."""
    ucx, ucy = (unit.bbox[0] + unit.bbox[2]) / 2, (unit.bbox[1] + unit.bbox[3]) / 2
    out = []
    for m in unit.members:
        e = copy.deepcopy(m)
        mcx, mcy = m["x"] + m["width"] / 2, m["y"] + m["height"] / 2
        e["width"], e["height"] = m["width"] * k, m["height"] * k
        e["x"] = cx + (mcx - ucx) * k - e["width"] / 2
        e["y"] = cy + (mcy - ucy) * k - e["height"] / 2
        if e["type"] == "text":
            e["font_size"] = max(1, int(round(m["font_size"] * k)))
        if e["type"] == "shape" and "corner_radius" in e:
            e["corner_radius"] = m["corner_radius"] * k
        out.append(e)
    return out


def _extent(els):
    from engine.safety import _footprint
    boxes = [_footprint(e) for e in els]
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def _col(els):
    """Normalise a group of elements into a column: shift to local origin, report w and h."""
    x0, y0, x1, y1 = _extent(els)
    for e in els:
        e["x"] -= x0
        e["y"] -= y0
    return {"w": x1 - x0, "h": y1 - y0, "els": els}


def _shift(els, dx, dy):
    for e in els:
        e["x"] += dx
        e["y"] += dy


# ---------- the row template ----------

def layout_row(design: Design, TW: float, TH: float, P: dict):
    by = design.by_role
    pad = max(3.0, round(0.08 * TH))
    gap = max(4.0, round(0.03 * TW))
    out: dict[str, dict] = {}

    fine, wms = by("fine_print"), by("watermark")
    strip_h = min(max(round(0.12 * TH), 7), 24) if (fine or wms) else 0
    top, bottom = pad, TH - pad - (strip_h + pad / 2 if strip_h else 0)
    ch = bottom - top
    if ch < 12:
        return None
    avail = TW - 2 * pad
    cols = []

    # media
    for u in by("logo"):
        e = _image(u, ch * P["logo"], 0.25 * TW)
        cols.append(_col([e]))
    for u in by("product") + by("image"):
        e = _image(u, ch * P["prod"], 0.3 * TW)
        cols.append(_col([e]))

    # badges: stacked column, or a row inside the text column
    badges = sorted(by("badge"), key=lambda u: u.order)
    badges_simple = [u for u in badges if _is_simple_pill(u)]
    badge_row_h = 0.0
    if badges_simple and P["badges"] == "col":
        n = len(badges_simple)
        gb = max(2.0, ch * 0.06)
        h = min((ch - (n - 1) * gb) / n, 0.22 * TH + 10)
        while True:
            built = [_pill(u, h) for u in badges_simple]
            w = max(b[1] for b in built)
            if (w <= 0.2 * TW and h * n + gb * (n - 1) <= ch) or h < 12:
                break
            h *= 0.92
        els = []
        for i, (pe, pw) in enumerate(built):
            _shift(pe, (w - pw) / 2, i * (h + gb))
            els += pe
        cols.append(_col(els))
    elif badges_simple:
        badge_row_h = min(0.13 * TH, ch * 0.25)
        badge_row_h = max(badge_row_h, 14.0)

    # ribbons and any unit we have no template for: scaled to fit and parked in a column
    odd = by("ribbon") + by("group") + by("shape") + [u for u in badges if not _is_simple_pill(u)]
    odd = [u for u in odd if u.role != "decoration"]
    for u in odd:
        k = min(1.0, 0.45 * ch / max(u.h, 1e-6), 0.2 * TW / max(u.w, 1e-6))
        cols.append(_col(_xform(u, k, 0, 0)))

    # button
    for u in by("cta"):
        if not _is_simple_pill(u):
            cols.append(_col(_xform(u, min(1.0, 0.5 * ch / max(u.h, 1e-6)), 0, 0)))
            continue
        h = ch * P["cta"]
        while True:
            pe, w = _pill(u, h)
            if w <= 0.3 * TW or h < 12:
                break
            h *= 0.92
        cols.append(_col(pe))

    # text column
    heads = by("headline")
    items = []
    if heads:
        hd = heads[0].members[0]
        items.append((hd, 1.0))
        for u in sorted(by("supporting") + by("text") + by("cta_text"), key=lambda u: u.order):
            e = u.members[0]
            items.append((e, max(0.3, min(0.9, e["font_size"] / hd["font_size"]))))
    elif by("supporting") + by("text") + by("cta_text"):
        for u in by("supporting") + by("text") + by("cta_text"):
            items.append((u.members[0], 1.0))
    n_cols = len(cols) + (1 if items else 0)
    fine_cap = None  # fine print must stay smaller than the smallest body text
    fixed_w = sum(c["w"] for c in cols) + gap * (n_cols - 1)
    Wt = avail - fixed_w
    if items:
        if Wt < max(24.0, 0.15 * TW):
            return None
        S, parts, total_h, ok = fit_stack(items, Wt, ch, ch * 0.6, extra_h=badge_row_h, gap_ratio=0.3)
        if not ok:
            return None
        fine_cap = max(3, int(min(s for s, _ in parts) * 0.85))
        texts, y = [], 0.0
        gap_t = 0.3 * S
        widest = 0.0
        for (el, _), (size, m) in zip(items, parts):
            e = copy.deepcopy(el)
            e.update(font_size=size, x=0.0, y=y, width=Wt, height=m["height"])
            texts.append(e)
            widest = max(widest, m["max_line_width"])
            y += m["height"] + gap_t
        # tighten the box to the text so the column can sit flush; keep the wrap identical
        for e, (size, m) in zip(texts, parts):
            tight = widest + 0.5
            if measure_text(e, size, tight)["n_lines"] == m["n_lines"]:
                e["width"] = tight
        col_w = widest + 0.5
        if badge_row_h:
            n = len(badges_simple)
            built = [_pill(u, badge_row_h) for u in badges_simple]
            row_w = sum(b[1] for b in built) + (n - 1) * 0.5 * badge_row_h
            k = min(1.0, col_w / row_w) if row_w else 1.0
            if k < 1.0:
                built = [_pill(u, max(12.0, badge_row_h * k)) for u in badges_simple]
                row_w = sum(b[1] for b in built) + (n - 1) * 0.5 * badge_row_h * k
            x = max(0.0, (col_w - row_w) / 2)
            by_y = y if items else 0.0
            for pe, pw in built:
                _shift(pe, x, by_y)
                texts += pe
                x += pw + 0.5 * badge_row_h * k
        text_col = _col(texts)
        # place the text column right after logo/product, before the badges and the button
        n_media = len(by("logo")) + len(by("product")) + len(by("image"))
        cols.insert(n_media, text_col)
        if text_col["h"] > ch + 0.5:
            return None
    elif badge_row_h:
        pass

    # horizontal spread: leftover width goes between columns, the rest becomes side margin
    natural = sum(c["w"] for c in cols) + gap * (len(cols) - 1)
    if natural > avail + 0.5:
        return None
    extra = avail - natural
    extra_gap = min(extra / (len(cols) - 1), 0.1 * TW) if len(cols) > 1 else 0.0
    x = pad + (avail - natural - extra_gap * max(len(cols) - 1, 0)) / 2
    for c in cols:
        _shift(c["els"], x, top + (ch - c["h"]) / 2)
        x += c["w"] + gap + extra_gap
        for e in c["els"]:
            out[e["id"]] = e

    # bottom strip: fine print (fitted to one line where possible) and the watermark
    wm_w = 0.0
    for u in wms:
        e = _image(u, strip_h, 0.2 * TW)
        e["x"], e["y"] = TW - pad - e["width"], TH - pad - strip_h + (strip_h - e["height"]) / 2
        wm_w = e["width"] + gap
        out[e["id"]] = e
    for u in fine:
        el = u.members[0]
        wfp = avail - wm_w
        cap = strip_h / 1.2 if fine_cap is None else min(strip_h / 1.2, fine_cap)
        size, m, ok = fit_size(el, wfp, strip_h, max_size=cap, min_size=3)
        e = copy.deepcopy(el)
        e.update(font_size=size, x=pad, y=TH - pad - strip_h + (strip_h - m["height"]) / 2, width=wfp,
                 height=m["height"])
        out[e["id"]] = e

    # decoration: same shape, scaled so it fits, centred where it was (relative), clamped inside
    for u in by("decoration"):
        k = min(1.0, 0.9 * TH / max(u.h, 1e-6), 0.9 * TW / max(u.w, 1e-6))
        ucx = (u.bbox[0] + u.bbox[2]) / 2 / design.canvas["width"] * TW
        ucy = (u.bbox[1] + u.bbox[3]) / 2 / design.canvas["height"] * TH
        els = _xform(u, k, ucx, ucy)
        x0, y0, x1, y1 = _extent(els)
        _shift(els, -min(0, x0) - max(0, x1 - TW), -min(0, y0) - max(0, y1 - TH))
        for e in els:
            out[e["id"]] = e

    # background covers the canvas
    for u in by("bg"):
        e = copy.deepcopy(u.members[0])
        e.update(x=0.0, y=0.0, width=float(TW), height=float(TH), fit="cover")
        out[e["id"]] = e
    return out


ROW_PARAMS = [
    {"logo": lg, "prod": pr, "cta": ct, "badges": bm}
    for lg in (0.75, 0.5) for pr in (1.0, 0.7) for ct in (0.5, 0.38) for bm in ("col", "row")
]
