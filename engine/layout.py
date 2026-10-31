"""Layout templates. Each returns {element_id: new_element} or None if it can't work.

layout_stack: portrait/square/story targets. One centred column: logo, ribbon, product,
text, badges (wrapping rows), button. Spare height becomes gaps (capped) then margins.
Story shapes (9:16) keep content out of the top 14% and bottom 35%.

layout_split: moderately wide targets. Media column on the left, text column on the right.

layout_spread: keep the original composition. Sizes scale uniformly, positions are
remapped proportionally, so a taller canvas spreads the same arrangement out.

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


def _media(unit, h_max, w_max):
    """An image unit as a list of elements. A bundle (image + its bar/aura/shadow, or a cluster of images) is scaled
    as one block so the parts keep their relative position and size."""
    if len(unit.members) == 1 and unit.members[0]["type"] == "image":
        return [_image(unit, h_max, w_max)]
    k = min(w_max / max(unit.w, 1e-6), h_max / max(unit.h, 1e-6))
    if len(getattr(unit, "parts", []) or []) >= 2:
        arranged = _arrange_set(unit, h_max, w_max, k)
        if arranged is not None:
            return arranged
    return _xform(unit, k, 0, 0)


class _Piece:
    def __init__(self, members):
        from engine.understand import _bbox
        self.members = members
        self.bbox = _bbox(members)
        self.w, self.h = self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1]


def _tight_piece(members):
    """A set piece re-arranged on its own: a caption that floated far above (or below) its picture is pulled in
    close, so the empty space between them doesn't make every piece tall and small. Copies; the source is untouched."""
    out = [copy.deepcopy(m) for m in members]
    imgs = [m for m in out if m["type"] == "image"]
    txts = [m for m in out if m["type"] == "text"]
    if not imgs or not txts:
        return out
    top = min(m["y"] for m in imgs)
    bot = max(m["y"] + m["height"] for m in imgs)
    ih = bot - top
    above = [t for t in txts if t["y"] + t["height"] <= top + 1]
    below = [t for t in txts if t["y"] >= bot - 1]
    want = 0.08 * ih
    if above:
        gap = top - max(t["y"] + t["height"] for t in above)
        if gap > want:
            for t in above:
                t["y"] += gap - want
    if below:
        gap = min(t["y"] for t in below) - bot
        if gap > want:
            for t in below:
                t["y"] -= gap - want
    return out


TARGET = (0.0, 0.0)  # the canvas being laid out (set by resize.candidates); lets a set match its orientation
ORIENT_KEEP = 0.75  # a set may give up this much size (linear) to follow the canvas: stack on tall, row on wide


def _arrange_set(unit, h_max, w_max, k_as_is):
    """An ordered set (before / after / right after, a menu of products) re-arranged to suit the space: the original
    line, a row, a column, or a grid, keeping reading order. Each piece keeps its own inner layout (label over
    picture). On a tall canvas it prefers stacking, on a wide one a row - as long as the pieces stay at least
    ORIENT_KEEP of the biggest size any arrangement allows. Returns None when the original arrangement is best."""
    import math
    pieces = [_Piece(_tight_piece(m)) for m in unit.parts]
    n = len(pieces)
    pw, ph = max(p.w for p in pieces), max(p.h for p in pieces)
    gap = 0.12 * min(pw, ph)
    options = []
    for cols in sorted({n, 1, math.ceil(math.sqrt(n)), math.ceil(n / 2)}):
        rows = math.ceil(n / cols)
        W = cols * pw + (cols - 1) * gap
        H = rows * ph + (rows - 1) * gap
        options.append((min(w_max / W, h_max / H), cols))
    tw, th = TARGET
    if tw >= BANNER_RATIO * th > 0:  # a banner: pieces flow side by side at one scale, each only as wide as itself
        flow = _flow_rows(pieces, h_max, w_max)
        if flow is not None and flow[0] >= FLOW_KEEP * k_as_is:
            return flow[1]
    k_top = max([k for k, _ in options] + [k_as_is])
    tall, wide = th >= 1.25 * tw > 0, tw >= 1.25 * th > 0
    ok = [(k, c) for k, c in options if k >= ORIENT_KEEP * k_top]
    if tall and ok:
        best = min(ok, key=lambda t: (t[1], -t[0]))  # fewest columns = most stacked
    elif wide and ok:
        best = max(ok, key=lambda t: (t[1], t[0]))   # most columns = a row
    else:
        best = max(options)
        best = best if best[0] >= 1.1 * k_as_is else (k_as_is, None)  # otherwise it must beat the original by 10%
    as_is_fits = (unit.set_axis == "y" and tall) or (unit.set_axis == "x" and wide)
    if as_is_fits and best[1] is not None and (best[1] == 1) == (unit.set_axis == "y") and best[0] < 1.1 * k_as_is:
        best = (k_as_is, None)  # the original already follows the canvas and is as big: keep it
    if best[1] is None:
        return None
    k, cols = best
    out = []
    rows_n = math.ceil(n / cols)
    for i, p in enumerate(pieces):
        r, c = divmod(i, cols)
        in_row = cols if r < rows_n - 1 else n - cols * (rows_n - 1)
        shift = (cols - in_row) * (pw + gap) / 2  # a short last row is centred
        cx = (shift + c * (pw + gap) + pw / 2) * k
        cy = (r * (ph + gap) + ph / 2) * k
        out += _xform(p, k, cx, cy)
    return out


BANNER_RATIO = 2.5  # target width / height from which a canvas counts as a banner strip
FLOW_KEEP = 0.6  # a banner flow's smallest card may be this much smaller than the composition (it fills the strip)
FLOW_SPREAD = 1.6  # in a banner flow, card scales stay within this factor of each other


def _flow_rows(pieces, h_max, w_max):
    """Product cards along a banner, in 1-3 rows, reading order kept. Cards get a common VISUAL height (a tall card
    and a wide one end up the same height, the way a designer lines up a catalogue), each card scale kept within
    FLOW_SPREAD of the others; each takes only its own width. Returns (smallest scale, elements) or None."""
    n = len(pieces)
    asp = [p.w / max(p.h, 1e-6) for p in pieces]
    best = None
    for r in range(1, min(3, n) + 1):
        # split in order into r rows with balanced total aspect (= balanced width at equal height)
        total = sum(asp)
        rows, cur, acc = [], [], 0.0
        for i, a in enumerate(asp):
            if cur and acc + a / 2 > total / r * (len(rows) + 1) and len(rows) < r - 1:
                rows.append(cur); cur = []
            cur.append(i); acc += a
        rows.append(cur)
        gap_f = 0.08  # gap as a share of the row height
        # row height hh: each row's width = hh * (sum aspects + gaps) <= w_max; all rows + gaps <= h_max
        need = max(sum(asp[i] for i in row) + gap_f * (len(row) - 1) for row in rows)
        hh = min(w_max / max(need, 1e-6), h_max / (r + gap_f * (r - 1)))
        if best is None or hh > best[0] * 1.02:
            best = (hh, rows)
    if best is None:
        return None
    hh, rows = best
    ks = [hh / max(p.h, 1e-6) for p in pieces]
    lo = max(ks) / FLOW_SPREAD  # nothing shrinks to a speck next to the others
    ks = [max(k, lo) for k in ks]
    hi = min(ks) * FLOW_SPREAD
    ks = [min(k, hi) for k in ks]
    gap = 0.08 * hh
    widths = [[pieces[i].w * ks[i] for i in row] for row in rows]
    heights = [max(pieces[i].h * ks[i] for i in row) for row in rows]
    W = max(sum(w) + gap * (len(w) - 1) for w in widths)
    Ht = sum(heights) + gap * (len(rows) - 1)
    f = min(1.0, w_max / max(W, 1e-6), h_max / max(Ht, 1e-6))  # clamping may have made it a bit too big: fit
    out, y = [], 0.0
    for row, ws, h in zip(rows, widths, heights):
        x = (W - sum(ws) - gap * (len(ws) - 1)) / 2
        for i, w in zip(row, ws):
            p, k = pieces[i], ks[i] * f
            out += _xform(p, k, (x + w / 2) * f, (y + h - p.h * ks[i] / 2) * f)  # bottom-aligned on the row
            x += w + gap
        y += h + gap
    return min(ks) * f, out


def _pill(unit, h):
    """Rounded shape + one label, rebuilt at height h (label font from h, width from the label)."""
    shape = next(m for m in unit.members if m["type"] == "shape")
    label = next(m for m in unit.members if m["type"] == "text")
    fs = max(6, int(h * 0.42))
    w = measure_text(label, fs, 10000)["max_line_width"] + 1.1 * h
    s, t = copy.deepcopy(shape), copy.deepcopy(label)
    if shape.get("shape_type") == "ellipse":  # a round badge/button stays round: keep its shape, fit the label inside
        w = h * shape["width"] / max(shape["height"], 1e-6)
        fs, m, _ = fit_size(label, 0.74 * w, 0.62 * h, max(6, int(h * 0.42)), min_size=5)
        s.update(width=w, height=h, x=0.0, y=0.0)
        t.update(font_size=fs, width=w, x=0.0, y=(h - m["height"]) / 2)
        t["height"] = m["height"]
        return [s, t], w
    ratio = (shape.get("corner_radius") or 0) / max(shape["height"], 1e-6)
    s.update(width=w, height=h, x=0.0, y=0.0)
    if "corner_radius" in s:
        s["corner_radius"] = ratio * h
    t.update(font_size=fs, width=w, x=0.0, y=h / 2 - CAP_CENTER * fs)
    t["height"] = measure_text(t, fs, w)["height"]
    return [s, t], w


def _logo_hmax(design: Design, unit, TW: float, TH: float) -> float:
    """Tallest the logo may be: at most twice its original share of the canvas area (a corner mark must not
    become the biggest thing in a banner)."""
    sw, sh = design.canvas["width"], design.canvas["height"]
    return unit.h * (2.0 * TW * TH / (sw * sh)) ** 0.5


def _head_cap(design: Design, TW: float, TH: float) -> float:
    """Biggest sensible headline: 1.6x its original size, scaled with the square root of the canvas area."""
    h = design.first("headline")
    if h is None:
        return 1e9
    sw, sh = design.canvas["width"], design.canvas["height"]
    cap = 1.6 * h.members[0]["font_size"] * (TW * TH / (sw * sh)) ** 0.5
    if TW / TH >= 2.2:  # short, wide banners: designers set the headline against the height (up to ~22% of it)
        cap = max(cap, 0.22 * TH)
    return cap


def _ratio(unit, el, head):
    """Font size relative to the headline. A plain-text button stays at least 60% of it."""
    r = max(0.15, min(0.9, el["font_size"] / head["font_size"]))
    from engine.understand import PRICE
    if PRICE.search(str(el.get("content", ""))) and len(str(el.get("content", "")).split()) <= 3:
        r = max(r, 0.5)  # a price must not shrink into the small print
    return max(r, 0.6) if unit.role == "cta_text" else r


def _ratios_without_head(design: Design, units: list) -> list:
    """Texts sized against the biggest font in the design when the headline is not one of them (it sits inside
    a lockup that is placed as a block). The stack size S then stands for the headline size, so small texts stay
    small instead of growing to headline size."""
    ref = max([design.ref_font] + [u.members[0]["font_size"] for u in units])
    return [(u.members[0], max(0.15, min(1.0, u.members[0]["font_size"] / ref))) for u in units]


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


def _scale_col(c, k):
    """Shrink a column uniformly by k (positions, sizes, fonts, corner radii)."""
    for e in c["els"]:
        for key in ("x", "y", "width", "height"):
            e[key] *= k
        if e["type"] == "text":
            e["font_size"] = max(1, int(round(e["font_size"] * k)))
        if e["type"] == "shape" and "corner_radius" in e:
            e["corner_radius"] *= k
    c["w"] *= k
    c["h"] *= k


def _shift(els, dx, dy):
    for e in els:
        e["x"] += dx
        e["y"] += dy


def _decorate(design: Design, TW: float, TH: float, out: dict, k_cap: float = 1.0):
    """Place decoration (same shape, inside the canvas) where it covers text, logo and product least.

    Tries the original relative spot and the four corners; if every spot still clashes it shrinks the
    shape a few times. Everything already in `out` counts as content.
    """
    from engine.score import _area, _inter, _rect
    sw, sh = design.canvas["width"], design.canvas["height"]
    content = [_rect(e) for e in out.values() if e["type"] in ("text", "image") or e.get("group_id")]
    content = [r for r in content if _area(r) > 0]
    for u in design.by_role("decoration"):
        k = min(k_cap, TW / sw, 0.9 * min(TW, TH) / max(u.w, u.h, 1e-6))
        base = ((u.bbox[0] + u.bbox[2]) / 2 / sw * TW, (u.bbox[1] + u.bbox[3]) / 2 / sh * TH)
        best = None
        for shrink in (1.0, 0.75, 0.55):
            kk = k * shrink
            w, h = u.w * kk, u.h * kk
            spots = [base, (w / 2, h / 2), (TW - w / 2, h / 2), (w / 2, TH - h / 2), (TW - w / 2, TH - h / 2)]
            for sx, sy in spots:
                els = _xform(u, kk, sx, sy)
                x0, y0, x1, y1 = _extent(els)
                _shift(els, -min(0, x0) - max(0, x1 - TW), -min(0, y0) - max(0, y1 - TH))
                box = _extent(els)
                clash = sum(_inter(box, r) / _area(r) for r in content)
                moved = abs(sx - base[0]) + abs(sy - base[1])
                key = (round(clash, 3), -shrink, moved)
                if best is None or key < best[0]:
                    best = (key, els)
            if best[0][0] == 0.0:
                break
        for e in best[1]:
            out[e["id"]] = e


# ---------- the row template ----------

def layout_row(design: Design, TW: float, TH: float, P: dict):
    by = design.by_role
    pad = max(2.0, round(0.08 * TH * P.get("pad", 1.0)))
    gap = max(4.0, round(0.03 * TW * P.get("pad", 1.0)))
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
    for u in by("logo"):  # a lockup (logo + slogan) scales as one block
        cols.append(_col(_media(u, min(ch * P["logo"], _logo_hmax(design, u, TW, TH)), 0.25 * TW * P.get("wcap", 1.0))))
    for u in sorted(by("product") + by("image"), key=lambda u: u.order):
        full = bool(P.get("fullh")) and u.role == "product"
        wcap = (0.68 if len(getattr(u, "parts", []) or []) >= 2 and TW >= BANNER_RATIO * TH else 0.3)
        c = _col(_media(u, ((TH - 2 * pad) if full else ch) * P["prod"], wcap * TW * P.get("wcap", 1.0)))
        c["full"] = full
        cols.append(c)

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
            if (w <= 0.2 * TW * P.get("wcap", 1.0) and h * n + gb * (n - 1) <= ch) or h < 12:
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
            if w <= 0.3 * TW * P.get("wcap", 1.0) or h < 12:
                break
            h *= 0.92
        cols.append(_col(pe))

    # text column
    heads = by("headline")
    items = []
    if heads:
        hd = heads[0].members[0]
        rest = sorted(by("supporting") + by("text") + by("cta_text"), key=lambda u: u.order)
        # text that reads before the headline in the source (a kicker) stays before it
        items += [(u.members[0], _ratio(u, u.members[0], hd)) for u in rest if u.order < heads[0].order]
        items.append((hd, 1.0))
        items += [(u.members[0], _ratio(u, u.members[0], hd)) for u in rest if u.order >= heads[0].order]
    elif by("supporting") + by("text") + by("cta_text"):
        rest = sorted(by("supporting") + by("text") + by("cta_text"), key=lambda u: u.order)
        items += _ratios_without_head(design, rest)
    n_cols = len(cols) + (1 if items else 0)
    if items and P.get("tfrac") and cols:
        room = avail - P["tfrac"] * avail - gap * (n_cols - 1)  # width the other columns may keep
        have = sum(c["w"] for c in cols)
        if have > room > 0:
            for c in cols:
                _scale_col(c, max(0.35, room / have))
    fine_cap = None  # fine print must stay smaller than the smallest body text
    fixed_w = sum(c["w"] for c in cols) + gap * (n_cols - 1)
    Wt = avail - fixed_w
    if items:
        if Wt < max(24.0, 0.15 * TW):
            return None
        S, parts, total_h, ok = fit_stack(items, Wt, ch, min(ch * 0.6, _head_cap(design, TW, TH)), extra_h=badge_row_h,
                                          gap_ratio=0.3)
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
    full_right = 0.0
    for c in cols:
        if c.get("full"):
            _shift(c["els"], x, pad + (TH - 2 * pad - c["h"]) / 2)
            full_right = max(full_right, x + c["w"])
        else:
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
        fx = full_right + gap if full_right else pad
        wfp = TW - pad - fx - wm_w
        if wfp < 40:
            return None
        cap = strip_h / 1.2 if fine_cap is None else min(strip_h / 1.2, fine_cap)
        size, m, ok = fit_size(el, wfp, strip_h, max_size=cap, min_size=3)
        e = copy.deepcopy(el)
        e.update(font_size=size, x=fx, y=TH - pad - strip_h + (strip_h - m["height"]) / 2, width=wfp,
                 height=m["height"])
        out[e["id"]] = e

    _decorate(design, TW, TH, out)

    # background covers the canvas
    for u in by("bg"):
        e = copy.deepcopy(u.members[0])
        e.update(x=0.0, y=0.0, width=float(TW), height=float(TH), fit="cover")
        out[e["id"]] = e
    return out


ROW_TIGHT_PARAMS = [
    {"logo": lg, "prod": 1.0, "cta": ct, "badges": bm, "wcap": 1.0, "tfrac": tf, "pad": pd, "fullh": fh}
    for lg in (0.5, 0.3) for ct in (0.38, 0.28) for bm in ("col", "row") for tf in (0.22, 0.32, 0.45, 0.58)
    for pd in (1.0, 0.5) for fh in (False, True)
]
ROW_PARAMS = [
    {"logo": lg, "prod": pr, "cta": ct, "badges": bm, "wcap": wc}
    for lg in (0.75, 0.5, 0.3) for pr in (1.0, 0.7) for ct in (0.5, 0.38, 0.28) for bm in ("col", "row")
    for wc in (1.0, 0.5)
]


# ---------- column builders shared by the stack and split templates ----------

def _pill_rows(units, h, Wc, gap_x):
    """Badge pills in centred rows that wrap at width Wc. Returns (local elements, width, height)."""
    while True:
        built = [_pill(u, h) for u in units]
        if max(w for _, w in built) <= Wc or h <= 10:
            break
        h *= 0.92
    rows: list[list] = [[]]
    row_w = [0.0]
    for b in built:
        w = b[1]
        if rows[-1] and row_w[-1] + gap_x + w > Wc:
            rows.append([])
            row_w.append(0.0)
        row_w[-1] += (gap_x if rows[-1] else 0) + w
        rows[-1].append(b)
    els = []
    for i, row in enumerate(rows):
        x = (Wc - row_w[i]) / 2
        for pe, pw in row:
            _shift(pe, x, i * (h + gap_x))
            els += pe
            x += pw + gap_x
    return els, Wc, len(rows) * h + (len(rows) - 1) * gap_x


def head_on_top(design: Design) -> bool:
    """Did the headline sit above every picture in the source (a title over the product)?"""
    head = design.first("headline")
    pics = design.by_role("product") + design.by_role("image")
    if head is None or not pics:
        return False
    return head.bbox[3] <= min(u.bbox[1] for u in pics) + 0.02 * design.canvas["height"]


def _column(design: Design, Wc: float, H: float, P: dict, parts: set):
    """Blocks (top to bottom) for the chosen parts, sized for a column Wc wide and H tall.

    Parts: logo, ribbon, product, text, badges, cta, odd. Text gets whatever height is left.
    Returns (items, fine_cap) or None if the text cannot fit. fine_cap = size limit for fine print.
    """
    by = design.by_role
    gmin = max(4.0, P.get("need_gap", 0.012) * H)
    sc = max(1.0, min(Wc, H) / 800)  # size caps below were tuned for ~1080px canvases
    items: list = []
    logo_items = []
    if "logo" in parts:
        for u in by("logo"):
            # the column (Wc x H) stands in for the canvas here: slightly smaller, so the cap errs small
            logo_items.append(_col(_media(u, min(P.get("logo_h", 0.12) * H, _logo_hmax(design, u, Wc, H)), P["logo"] * Wc)))
    if not P.get("logo_last"):
        items += logo_items
    if "ribbon" in parts:
        for u in by("ribbon"):
            k = min(1.0, 0.6 * Wc / max(u.w, 1e-6), 0.08 * H / max(u.h, 1e-6))
            items.append(_col(_xform(u, k, 0, 0)))
    prod_items = []
    if "product" in parts:
        for u in sorted(by("product") + by("image"), key=lambda u: u.order):
            prod_items.append(_col(_media(u, P["prod"] * H, P.get("pw", 0.85) * Wc)))
    if not P.get("text_first"):
        items += prod_items

    text_at, texts_src = None, []
    if "text" in parts:
        rest = sorted(by("supporting") + by("text") + by("cta_text"), key=lambda u: u.order)
        heads = by("headline")
        if heads:
            hd = heads[0].members[0]
            texts_src += [(u.members[0], _ratio(u, u.members[0], hd)) for u in rest if u.order < heads[0].order]
            texts_src.append((hd, 1.0))
            texts_src += [(u.members[0], _ratio(u, u.members[0], hd)) for u in rest if u.order >= heads[0].order]
        else:
            texts_src = _ratios_without_head(design, rest)
        if texts_src:
            text_at = len(items)
            items.append(None)  # filled in once we know how much height is left
    if P.get("text_first"):  # the headline sat above the pictures in the source: keep it on top
        items += prod_items

    badges = sorted(by("badge"), key=lambda u: u.order)
    simple = [u for u in badges if _is_simple_pill(u)]
    if "badges" in parts and simple:
        h_b = min(max(0.04 * H, 18.0 * sc), 56.0 * sc)
        els, w, h = _pill_rows(simple, h_b, Wc, 0.4 * h_b)
        items.append({"els": els, "w": w, "h": h})
    if "cta" in parts:
        for u in by("cta"):
            if _is_simple_pill(u):
                h_c = min(max(P["cta"] * H, 26.0 * sc), 120.0 * sc)
                while True:
                    pe, w = _pill(u, h_c)
                    if w <= Wc or h_c <= 14:
                        break
                    h_c *= 0.92
                items.append(_col(pe))
            else:
                items.append(_col(_xform(u, min(1.0, 0.8 * Wc / u.w, 0.1 * H / u.h), 0, 0)))
    if "odd" in parts:
        for u in by("group") + by("shape") + [b for b in badges if not _is_simple_pill(b)]:
            items.append(_col(_xform(u, min(1.0, 0.8 * Wc / max(u.w, 1e-6), 0.1 * H / max(u.h, 1e-6)), 0, 0)))

    if P.get("logo_last"):  # the logo signed off the source design (under the text): keep it last
        items += logo_items
    fine_cap = None
    if text_at is not None:
        used = sum(i["h"] for i in items if i)
        h_text = H - used - gmin * (len(items) - 1)
        if h_text < 20:
            return None
        S, parts_fit, _, ok = fit_stack(texts_src, Wc, h_text, min(P["hcap"] * Wc, P.get("hcap_abs", 1e9)),
                                        min_size=6)
        if not ok:
            return None
        fine_cap = max(3, int(min(s for s, _ in parts_fit) * 0.85))
        els, y = [], 0.0
        for (el, _), (size, m) in zip(texts_src, parts_fit):
            e = copy.deepcopy(el)
            e.update(font_size=size, x=0.0, y=y, width=Wc, height=m["height"])
            els.append(e)
            y += m["height"] + 0.3 * S
        items[text_at] = {"els": els, "w": Wc, "h": y - 0.3 * S}
    return items, fine_cap


def _flow(items: list, top: float, H: float, x0: float, Wc: float, out: dict, g_cap: float = 0.07,
          min_gap: float = 0.012) -> bool:
    """Place blocks top to bottom in a column: spare height becomes gaps (capped), then outer margins."""
    n = len(items)
    free = H - sum(i["h"] for i in items)
    if free < max(4.0, min_gap * H) * (n - 1) - 0.5:
        return False
    g = min(free / (n - 1), g_cap * H) if n > 1 else 0.0
    y = top + (free - g * max(n - 1, 0)) / 2
    for it in items:
        _shift(it["els"], x0 + (Wc - it["w"]) / 2, y)
        y += it["h"] + g
        for e in it["els"]:
            out[e["id"]] = e
    return True


def _finish(design: Design, TW: float, TH: float, out: dict, pad: float, strip_h: float, edge: float,
            fine_cap):
    """Fine print and watermark along `edge`, decoration (same shape, inside), background (cover)."""
    by = design.by_role
    Wc = TW - 2 * pad
    wm_w = 0.0
    for u in by("watermark"):
        e = _image(u, strip_h, 0.25 * Wc)
        e["x"], e["y"] = TW - pad - e["width"], edge - e["height"]
        wm_w = e["width"] + 0.02 * TW
        out[e["id"]] = e
    for u in by("fine_print"):
        el = u.members[0]
        wfp = Wc - wm_w
        cap = strip_h / 1.2 if fine_cap is None else min(strip_h / 1.2, fine_cap)
        size, m, ok = fit_size(el, wfp, strip_h, max_size=max(cap, 4), min_size=3)
        e = copy.deepcopy(el)
        e.update(font_size=size, x=pad, y=edge - m["height"], width=wfp, height=m["height"])
        out[e["id"]] = e
    _decorate(design, TW, TH, out)
    for u in by("bg"):
        e = copy.deepcopy(u.members[0])
        e.update(x=0.0, y=0.0, width=float(TW), height=float(TH), fit="cover")
        out[e["id"]] = e


def _band(design: Design, TW: float, TH: float, pad: float, P: dict | None = None):
    """Vertical band for content: story shapes keep out of the top 14% / bottom 35%; a strip for fine print."""
    story = 0.5 <= TW / TH <= 0.6 and TW >= 500
    P = P or {}
    top = P.get("st", 0.14) * TH if story else pad
    bottom = P.get("sb", 0.65) * TH if story else TH - pad
    has_strip = bool(design.by_role("fine_print") or design.by_role("watermark"))
    strip_h = min(max(0.045 * TH, 12.0), 56.0 * max(1.0, TH / 1080)) if has_strip else 0.0
    band_bottom = bottom - (strip_h + 0.5 * pad if strip_h else 0.0)
    edge = band_bottom + 0.5 * pad + strip_h if strip_h else band_bottom
    return top, band_bottom - top, strip_h, edge


def layout_stack(design: Design, TW: float, TH: float, P: dict):
    pad = max(4.0, round(0.06 * min(TW, TH) * P.get("pad", 1.0)))
    Wc = TW - 2 * pad
    top, H, strip_h, edge = _band(design, TW, TH, pad, P)
    if Wc < 40 or H < 60:
        return None
    parts = {"logo", "product", "text", "badges", "cta", "odd"} | (set() if P.get("rc") else {"ribbon"})
    P = dict(P, hcap_abs=min(P.get("hcap_abs", 1e9), _head_cap(design, TW, TH)))
    col = _column(design, Wc, H, P, parts)
    if col is None or not col[0]:
        return None
    out: dict[str, dict] = {}
    if not _flow(col[0], top, H, pad, Wc, out, P.get("gcap", 0.07), P.get("need_gap", 0.012)):
        return None
    if P.get("rc"):
        for u in design.by_role("ribbon"):
            k = min(1.0, 0.35 * TW / max(u.w, 1e-6))
            els = _xform(u, k, TW - pad - u.w * k / 2, top + u.h * k / 2)
            x0, y0, x1, y1 = _extent(els)
            _shift(els, -max(0, x1 - TW + pad // 2), -min(0, y0))
            for e in els:
                out[e["id"]] = e
    _finish(design, TW, TH, out, pad, strip_h, edge, col[1])
    return out


def layout_split(design: Design, TW: float, TH: float, P: dict):
    pad = max(4.0, round(0.05 * min(TW, TH) * P.get("pad", 1.0)))
    gap = max(6.0, 0.04 * TW * P.get("pad", 1.0))
    avail = TW - 2 * pad
    Wm = P["mw"] * (avail - gap)
    Wt = avail - gap - Wm
    top, H, strip_h, edge = _band(design, TW, TH, pad)
    if Wm < 40 or Wt < 80 or H < 60:
        return None
    P = dict(P, hcap_abs=min(P.get("hcap_abs", 1e9), _head_cap(design, TW, TH)))
    if P.get("logo_text"):  # the picture gets the whole media column; the logo joins the text (as in Heinz)
        logo, head = design.first("logo"), design.first("headline")
        last = bool(logo and head and logo.order > head.order)
        left = _column(design, Wm, H, P, {"product"})
        right = _column(design, Wt, H, dict(P, logo_last=last), {"logo", "ribbon", "text", "badges", "cta", "odd"})
    else:
        left = _column(design, Wm, H, P, {"logo", "product"})
        right = _column(design, Wt, H, P, {"ribbon", "text", "badges", "cta", "odd"})
    if left is None or right is None or not left[0] or not right[0]:
        return None
    out: dict[str, dict] = {}
    if not (_flow(left[0], top, H, pad, Wm, out, 0.07, P.get("need_gap", 0.012))
            and _flow(right[0], top, H, pad + Wm + gap, Wt, out, 0.07, P.get("need_gap", 0.012))):
        return None
    _finish(design, TW, TH, out, pad, strip_h, edge, right[1])
    return out


STACK_PARAMS = [
    {"logo": 0.45, "prod": pf, "hcap": hc, "cta": ct, "gcap": gc, "rc": rc}
    for pf in (0.3, 0.42, 0.55, 0.68) for hc in (0.05, 0.08, 0.13, 0.2) for ct in (0.06, 0.09)
    for gc in (0.07, 0.18) for rc in (False, True)
]
SPLIT_WIDE_PARAMS = [
    {"mw": mw, "logo": 0.7, "logo_h": 0.18, "prod": pf, "hcap": hc, "cta": 0.1, "pad": pd, "pw": 0.97}
    for mw in (0.5, 0.58, 0.66) for pf in (0.9, 1.0) for hc in (0.08, 0.12) for pd in (1.0, 0.5)
]
# picture fills the media column at full height, logo moves into the text column (keeps its source order)
SPLIT_WIDE_PARAMS += [
    {"mw": mw, "logo": 0.6, "logo_h": 0.14, "prod": 1.0, "hcap": hc, "cta": 0.1, "pad": pd, "pw": 0.97, "logo_text": True}
    for mw in (0.4, 0.5, 0.58) for hc in (0.08, 0.12, 0.16) for pd in (1.0, 0.5)
]
STACK_TIGHT_PARAMS = [
    {"logo": 0.45, "prod": pf, "hcap": hc, "cta": 0.07, "gcap": 0.07, "rc": False, "pad": 0.5, "pw": pw}
    for pf in (0.45, 0.55, 0.68) for hc in (0.08, 0.13, 0.2) for pw in (0.85, 1.0)
]
SPLIT_PARAMS = [
    {"mw": mw, "logo": 0.7, "logo_h": 0.18, "prod": pf, "hcap": hc, "cta": ct}
    for mw in (0.38, 0.46) for pf in (0.6, 0.8, 1.0) for hc in (0.05, 0.08, 0.12) for ct in (0.1, 0.15)
]


def layout_anchor(design: Design, TW: float, TH: float, P: dict):
    """Photo-anchored: every unit stays on the same picture content it covered in the original.

    The background photo is cropped differently at a new shape (cover), so a proportional spread puts text over other
    parts of the photo than the designer chose. Here each unit's centre is mapped through the photo: source canvas ->
    picture pixel -> new canvas. Only for photo-like backgrounds (busy images); smooth gradients are left to the others.
    """
    from engine import pixels
    from engine.safety import _fit_unit, _keep_text_inside

    bgu = design.first("bg")
    if bgu is None or bgu.members[0]["type"] != "image" or bgu.members[0].get("fit", "contain") != "cover":
        return None
    asset = bgu.members[0].get("asset_id", "")
    size, st = pixels.asset_size(asset), pixels.asset_stats(asset)
    if not size or not st or st["busy"] < 0.008:
        return None
    iw, ih = size
    sw, sh = design.canvas["width"], design.canvas["height"]
    fs, ft = max(sw / iw, sh / ih), max(TW / iw, TH / ih)
    k = ft / fs * P["grow"]
    out: dict[str, dict] = {}
    for u in design.units:
        if u.role == "bg":
            e = copy.deepcopy(u.members[0])
            e.update(x=0.0, y=0.0, width=float(TW), height=float(TH), fit="cover")
            out[e["id"]] = e
            continue
        ucx, ucy = (u.bbox[0] + u.bbox[2]) / 2, (u.bbox[1] + u.bbox[3]) / 2
        nx = ((ucx - sw / 2) / fs) * ft + TW / 2
        ny = ((ucy - sh / 2) / fs) * ft + TH / 2
        els = _xform(u, k, nx, ny)
        _fit_unit(els, TW, TH)
        for e in els:
            out[e["id"]] = e
    _keep_text_inside(list(out.values()), TW, TH)
    return out


ANCHOR_PARAMS = [{"grow": g} for g in (1.0, 1.3, 1.6)]


def layout_spread(design: Design, TW: float, TH: float, P: dict):
    from engine.safety import _fit_unit, _keep_text_inside
    sw, sh = design.canvas["width"], design.canvas["height"]
    sx, sy = TW / sw, TH / sh
    s = min(sx, sy)
    out: dict[str, dict] = {}
    for u in design.units:
        if u.role == "bg":
            e = copy.deepcopy(u.members[0])
            e.update(x=0.0, y=0.0, width=float(TW), height=float(TH), fit="cover")
            out[e["id"]] = e
            continue
        els = _xform(u, s, (u.bbox[0] + u.bbox[2]) / 2 * sx, (u.bbox[1] + u.bbox[3]) / 2 * sy)
        _fit_unit(els, TW, TH)
        for e in els:
            out[e["id"]] = e
    _keep_text_inside(list(out.values()), TW, TH)
    return out


SPREAD_PARAMS = [{}]


# ---------- grow-to-fit: the biggest product / button / text that still works ----------

def _grow(fn, design: Design, TW: float, TH: float, P: dict):
    """Binary-search a common growth factor s for product, button, logo and headline cap.

    A layout is accepted if it builds, the headline stays at least P["hmin"] x min(TW, TH) and the gaps
    stay at least P["need_gap"] x height. The largest accepted s wins.
    """
    head = design.first("headline")
    base = min(TW, TH)

    def make(s):
        Q = dict(P)
        Q["prod"], Q["hcap"], Q["cta"] = P["prod"] * s, P["hcap"] * s, P["cta"] * s
        Q["logo"] = min(P["logo"] * s ** 0.5, 0.9)
        Q["hcap_abs"] = 0.075 * (TW * TH) ** 0.5  # a headline never balloons past ~1.5x its original relative size
        return fn(design, TW, TH, Q)

    def ok(out):
        if not out:
            return False
        if head is not None:
            e = out.get(head.members[0]["id"])
            if e is not None and e["font_size"] < P["hmin"] * base:
                return False
        return True

    lo, hi = 0.4, 2.5
    best = make(lo)
    if not ok(best):
        return None
    for _ in range(9):
        mid = (lo + hi) / 2
        o = make(mid)
        if ok(o):
            lo, best = mid, o
        else:
            hi = mid
    return best


def layout_stack_grow(design, TW, TH, P):
    return _grow(layout_stack, design, TW, TH, P)


def layout_split_grow(design, TW, TH, P):
    return _grow(layout_split, design, TW, TH, P)


GROW_STACK_PARAMS = [
    {"logo": 0.45, "prod": 0.3, "hcap": 0.1, "cta": 0.07, "gcap": 0.18, "rc": rc, "hmin": hm, "need_gap": ng}
    for hm in (0.04, 0.055, 0.07) for ng in (0.02, 0.04) for rc in (False, True)
]
GROW_SPLIT_PARAMS = [
    {"mw": mw, "logo": 0.7, "logo_h": 0.18, "prod": 0.7, "hcap": 0.08, "cta": 0.1, "hmin": hm, "need_gap": ng}
    for mw in (0.38, 0.46) for hm in (0.04, 0.055, 0.07) for ng in (0.02, 0.04)
]


def story_variants(params: list) -> list:
    """Copies of a stack grid with a roomier story safe zone (the app's own bars cover about the top and bottom 13%)."""
    return [dict(p, st=0.12, sb=sb) for p in params for sb in (0.78, 0.86)]
