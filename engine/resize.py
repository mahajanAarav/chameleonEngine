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


EXTREME_RATIO = 15.0  # canvases this many times longer than wide (no real ad size is) keep their content together
GAP_CAP = 0.5  # ... with gaps between blocks of at most this share of the canvas's short side


def _close_gaps(layout: dict) -> None:
    """On an absurdly long canvas (20000x300, 300x20000) a layout spreads its blocks thousands of pixels apart; a
    designer keeps them as one group. Along the long axis: find the bands that hold content, cap the empty gaps
    between them, and centre the group. Bands move rigidly along one axis only, so nothing new can overlap, and
    full-length elements (the background) stay put."""
    tw, th = layout["canvas"]["width"], layout["canvas"]["height"]
    if min(tw, th) <= 0 or max(tw, th) < EXTREME_RATIO * min(tw, th):
        return
    ax = "x" if tw > th else "y"
    sz = "width" if ax == "x" else "height"
    L, short = (tw, th) if ax == "x" else (th, tw)
    if ax == "x":  # a text box far wider than its words would bridge the gaps: tighten it to its ink (same lines)
        from engine.textmeasure import measure_text
        for e in layout["elements"]:
            if e.get("type") != "text" or e.get("rotation"):
                continue
            m = measure_text(e)
            ink = m["max_line_width"] + 1.0
            if ink < e["width"] and measure_text(dict(e, width=ink))["n_lines"] == m["n_lines"]:
                al = e.get("text_align", "left")
                off = (e["width"] - ink) / 2 if al == "center" else (e["width"] - ink) if al == "right" else 0.0
                e["x"], e["width"] = e["x"] + off, ink
    movers = [e for e in layout["elements"] if e[sz] < 0.5 * L]  # full-length pieces (background, bands) stay put
    if len(movers) < 2:
        return
    spans = sorted((e[ax], e[ax] + e[sz]) for e in movers)
    bands = []
    for a, b in spans:
        if bands and a <= bands[-1][1]:
            bands[-1][1] = max(bands[-1][1], b)
        else:
            bands.append([a, b])
    cap = GAP_CAP * short
    shifts, pos = [], 0.0
    for i, (a, b) in enumerate(bands):
        new_a = a if i == 0 else pos + min(a - bands[i - 1][1], cap)
        shifts.append(new_a - a)
        pos = new_a + (b - a)
    total = pos - bands[0][0]
    centre = (L - total) / 2 - bands[0][0]
    for e in movers:
        k = next(i for i, (a, b) in enumerate(bands) if a <= e[ax] + 1e-6 and e[ax] + e[sz] <= b + 1e-6)
        e[ax] = round(e[ax] + shifts[k] + centre, 2)


HERO_GROW_MAX = 1.6  # the spotlight may grow up to this much (linear) into free space around it
HERO_GROW_SHARE = 0.45  # ... but never past this share of the canvas
HERO_GROW_MIN = 1.05  # smaller gains aren't worth moving it
HERO_GROW_SLIDE = 0.6  # ... and may slide at most this much (of its own size) to find room
HERO_GROW_GAP = 0.02  # clear space kept to every other element (share of the canvas's short side)


def _grow_hero(source: dict, layout: dict) -> None:
    """Last step: a spotlight picture surrounded by empty space grows into it (a taco in the middle of a wide canvas).
    Uniform scale only (proportions kept), it stays on the canvas, keeps a clear gap to everything it did not already
    touch, and never covers more of anything it already touched. Pictures only: a hero with captions is left alone."""
    from engine.safety import is_background
    from engine.understand import understand
    tw, th = layout["canvas"]["width"], layout["canvas"]["height"]
    if tw <= 0 or th <= 0 or max(tw, th) >= EXTREME_RATIO * min(tw, th):
        return
    heroes = understand(source).heroes()
    if not heroes:
        return
    hero = max(heroes, key=lambda u: (u.bbox[2] - u.bbox[0]) * (u.bbox[3] - u.bbox[1]))
    ids = {m["id"] for m in hero.members}
    if any(m["type"] == "text" or m.get("rotation") for m in hero.members):
        return  # captions or turned pictures: their real footprint isn't the box, leave them be
    els = [e for e in layout["elements"] if e["id"] in ids]
    if not els or any(e.get("rotation") for e in els):
        return
    x0 = min(e["x"] for e in els); y0 = min(e["y"] for e in els)
    x1 = max(e["x"] + e["width"] for e in els); y1 = max(e["y"] + e["height"] for e in els)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    gap = HERO_GROW_GAP * min(tw, th)
    others = [e for e in layout["elements"] if e["id"] not in ids and not is_background(e, layout["canvas"])
              and e.get("width", 0) > 0 and e.get("height", 0) > 0]

    def box(e):
        if e.get("type") == "text":
            from engine.finalize import _ink_inside
            return _ink_inside(e, tw, th)[1]
        return (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"])

    def inter(a, b):
        return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))

    obs = [box(e) for e in others]
    old = (x0, y0, x1, y1)
    before = [inter(old, o) for o in obs]
    cap = min(HERO_GROW_MAX, (HERO_GROW_SHARE * tw * th / (w * h)) ** 0.5)
    k = cap
    while k >= HERO_GROW_MIN:
        nw, nh = w * k, h * k
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # every spot on a grid, nearest to where the hero already is first (it may slide into the free space)
        steps = 24
        spots = [(nw / 2 + (tw - nw) * i / steps, nh / 2 + (th - nh) * j / steps)
                 for i in range(steps + 1) for j in range(steps + 1)] if tw > nw and th > nh else []
        spots.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        far = HERO_GROW_SLIDE * max(w, h)
        spots = [(cx, cy), (cx, y0 + nh / 2), (cx, y1 - nh / 2), (x0 + nw / 2, cy), (x1 - nw / 2, cy)] + [
            p for p in spots if ((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5 <= far]
        for ax, ay in spots:
            nx0 = min(max(ax - nw / 2, 0.0), tw - nw); ny0 = min(max(ay - nh / 2, 0.0), th - nh)
            if nx0 < -0.01 or ny0 < -0.01:
                continue
            new = (nx0, ny0, nx0 + nw, ny0 + nh)
            padded = (new[0] - gap, new[1] - gap, new[2] + gap, new[3] + gap)
            ok = True
            for o, b in zip(obs, before):
                if b > 0:
                    if inter(new, o) > b + 1.0:  # already touching: may not cover more of it
                        ok = False; break
                elif inter(padded, o) > 0:
                    ok = False; break
            if not ok:
                continue
            for e in els:
                e["x"] = round(nx0 + (e["x"] - x0) * k, 2)
                e["y"] = round(ny0 + (e["y"] - y0) * k, 2)
                e["width"] = e["width"] * k if e["width"] * k < 50 else round(e["width"] * k, 2)
                e["height"] = e["height"] * k if e["height"] * k < 50 else round(e["height"] * k, 2)
            return
        k -= 0.05


def _round(el: dict) -> dict:
    for k in ("x", "y", "width", "height", "corner_radius"):
        if k in el:
            if el.get("type") == "image" and k in ("width", "height") and el[k] < 50:
                continue  # a tiny picture keeps full precision: rounding 0.32 x 0.07 would bend its proportions
            el[k] = round(el[k], 2)
    return el


OVERLAP_OK = 0.85  # overlap term at or above this counts as collision-free
READ_FRAC = 0.85  # text must be at least this readable, relative to the best clean layout (real pixels behind it)
MIRROR_TOP = 10  # how many of the best layouts get a mirrored twin tried
MIRROR_GAIN = 0.15  # the twin must be at least this much more readable to be kept
COLLAGE_MIN = 4  # this many separate pictures (not touching) make a collage
SIZE_FRAC = 0.5
HERO_FRAC = 0.8  # the spotlight must keep at least this fraction of the best share any clean layout gives it
HERO_FRAC_DOMINANT = 0.8  # ... and this much when it dominates the source design (the point of the ad)
HERO_DOMINANT_SHARE = 0.33  # a spotlight covering at least this share of the source canvas counts as dominant
HERO_FLOOR = 0.5  # the spotlight keeps at least this fraction of the biggest share any clean layout can give it (capped at its original share)
HERO_FLOOR_DOMINANT = 0.6  # ... when it dominates the source design
ORIENT_HERO = 0.45  # a set may follow the canvas orientation while the spotlight keeps this share of its best size
BALANCE_FRAC = 0.9  # then: the most balanced layouts (hero kept vs headline kept), within this fraction of the best balance
LOGO_OK = 0.45  # logo term at or above this counts as a clearly visible logo (about 27% of its original relative area)


def scale_letter_spacing(source: dict, layout: dict, keep_tighter: bool = False) -> dict:
    """Letter spacing is in px, so a 117px gap that suits a 216px wordmark pushes a 120px wordmark off the canvas.
    Keep each text's spacing in the same proportion to its font size as in the source. keep_tighter: if a repair
    step already tightened the spacing further (to keep text on the canvas), leave that."""
    src = {e["id"]: e for e in source["elements"]}
    for e in layout.get("elements", []):
        s = src.get(e.get("id"))
        if e.get("type") == "text" and s and s.get("letter_spacing") and s.get("font_size"):
            want = round(float(s["letter_spacing"]) * float(e["font_size"]) / float(s["font_size"]), 2)
            have = e.get("letter_spacing")
            if keep_tighter and have is not None and abs(float(have)) < abs(want):
                continue
            e["letter_spacing"] = want
    return layout


def _backdrops(source: dict) -> list:
    """Panels: an opaque rectangle (not the background, not part of a group) that text sits on in the source.
    Returns [(panel_id, [client ids])]; clients are the texts at least 80% inside it and drawn above it."""
    from engine.safety import is_background

    def box(e):
        return (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"])

    def inside(a, b):
        iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        return iw * ih / max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)

    W, H = source["canvas"]["width"], source["canvas"]["height"]
    out = []
    for p in source["elements"]:
        if (p.get("type") != "shape" or p.get("group_id") or p.get("shape_type", "rectangle") != "rectangle"
                or float(p.get("opacity", 1)) < 0.8 or is_background(p, source["canvas"])
                or p["width"] * p["height"] < 0.05 * W * H):
            continue
        clients = [e["id"] for e in source["elements"] if e.get("type") == "text"
                   and int(e.get("z_index") or 0) > int(p.get("z_index") or 0) and inside(box(e), box(p)) >= 0.8]
        if clients:
            out.append((p["id"], clients))
    return out


def fit_backdrops(source: dict, layout: dict) -> dict:
    """Move/resize each panel so it sits behind its texts again (white text must not end up on a white page).
    A plain rectangle: changing its proportions is allowed (only images and round shapes must keep theirs)."""
    tw, th = layout["canvas"]["width"], layout["canvas"]["height"]
    by_id = {e["id"]: e for e in layout["elements"]}
    for pid, clients in _backdrops(source):
        p = by_id.get(pid)
        cs = [by_id[c] for c in clients if c in by_id]
        if p is None or not cs:
            continue
        try:
            from engine.textmeasure import measure_text
            boxes = []
            for e in cs:
                m = measure_text(e)
                ink = m["max_line_width"]
                x0 = e["x"] + {"center": (e["width"] - ink) / 2, "right": e["width"] - ink}.get(e.get("text_align", "left"), 0)
                boxes.append((x0, e["y"], x0 + ink, e["y"] + m["height"]))
        except Exception:
            boxes = [(e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]) for e in cs]
        pad = max(4.0, 0.035 * min(tw, th), 0.35 * max(e["font_size"] for e in cs))
        x0 = max(0.0, min(b[0] for b in boxes) - pad)
        y0 = max(0.0, min(b[1] for b in boxes) - pad)
        x1 = min(float(tw), max(b[2] for b in boxes) + pad)
        y1 = min(float(th), max(b[3] for b in boxes) + pad)
        # a panel that spanned the whole width in the source keeps spanning it, unless the full-width band would now
        # run over things that were not on the panel in the source (a logo or a line of text beside it)
        sp = next(e for e in source["elements"] if e["id"] == pid)
        if sp["width"] >= 0.95 * source["canvas"]["width"]:
            src_by = {e["id"]: e for e in source["elements"]}

            def hits(a, b):
                return (min(a["x"] + a["width"], b[2]) - max(a["x"], b[0]) > 1
                        and min(a["y"] + a["height"], b[3]) - max(a["y"], b[1]) > 1)

            band = (0.0, y0, float(tw), y1)
            on_src = (sp["x"], sp["y"], sp["x"] + sp["width"], sp["y"] + sp["height"])
            blocked = any(hits(e, band) and not hits(src_by[e["id"]], on_src)
                          for e in layout["elements"] if e["id"] != pid and e["id"] in src_by
                          and not (e.get("type") == "image" and e["width"] * e["height"] >= 0.9 * tw * th))
            if not blocked:
                x0, x1 = 0.0, float(tw)
        # trim the padding on any side where it would touch something that was not on the panel in the source
        src_by2 = {e["id"]: e for e in source["elements"]}
        sp_box = (sp["x"], sp["y"], sp["x"] + sp["width"], sp["y"] + sp["height"])
        cx0, cy0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        cx1, cy1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        for e in layout["elements"]:
            if e["id"] == pid or e["id"] in clients or e["id"] not in src_by2:
                continue
            if e.get("type") == "image" and e["width"] * e["height"] >= 0.9 * tw * th:
                continue
            se = src_by2[e["id"]]
            if (min(se["x"] + se["width"], sp_box[2]) - max(se["x"], sp_box[0]) > 1
                    and min(se["y"] + se["height"], sp_box[3]) - max(se["y"], sp_box[1]) > 1):
                continue  # it was on the panel in the source too (a product bleeding over it): allowed
            ex0, ey0, ex1, ey1 = e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]
            if min(ex1, x1) - max(ex0, x0) <= 0 or min(ey1, y1) - max(ey0, y0) <= 0:
                continue
            if ey1 <= cy0:
                y0 = max(y0, min(ey1 + 1, cy0))
            elif ey0 >= cy1:
                y1 = min(y1, max(ey0 - 1, cy1))
            elif ex1 <= cx0:
                x0 = max(x0, min(ex1 + 1, cx0))
            elif ex0 >= cx1:
                x1 = min(x1, max(ex0 - 1, cx1))
        p.update(x=round(x0, 2), y=round(y0, 2), width=round(x1 - x0, 2), height=round(y1 - y0, 2))
        if "corner_radius" in p and sp.get("corner_radius"):
            p["corner_radius"] = round(sp["corner_radius"] * min(p["width"] / sp["width"], p["height"] / sp["height"]), 2)
    return layout


def _finalized(source: dict, layout: dict) -> dict:
    """finalize() measures letter spacing relative to each text's current font size, so put spacing in proportion
    before it repairs anything, and again after (it may have changed font sizes)."""
    from engine.finalize import finalize

    out = scale_letter_spacing(source, finalize(scale_letter_spacing(source, layout)), keep_tighter=True)
    try:
        fit_backdrops(source, out)
    except Exception:
        pass
    try:
        _raise_tiny_text(source, out)
    except Exception:
        pass  # a polish step must never break the engine
    try:
        _keep_line_breaks(source, out)
    except Exception:
        pass
    return out


def _raise_tiny_text(source: dict, layout: dict) -> None:
    """Last polish: text the layout squeezed below a visible size is lifted to MIN_VISIBLE_FONT when that is
    safe - the text stays on the canvas and does not land on anything it was not already touching."""
    from engine.finalize import _ink_inside
    from engine.safety import is_background
    from engine.textmeasure import measure_text

    src = {e["id"]: e for e in source["elements"]}
    tw, th = layout["canvas"]["width"], layout["canvas"]["height"]
    others = lambda e: [o for o in layout["elements"] if o is not e and not is_background(o, layout["canvas"])]

    def inside(box, o, tol=1.0):
        return (box[0] >= o["x"] - tol and box[1] >= o["y"] - tol and box[2] <= o["x"] + o["width"] + tol
                and box[3] <= o["y"] + o["height"] + tol)

    def mostly_in(box, o):
        ix = max(0.0, min(box[2], o["x"] + o["width"]) - max(box[0], o["x"]))
        iy = max(0.0, min(box[3], o["y"] + o["height"]) - max(box[1], o["y"]))
        return ix * iy >= 0.8 * max((box[2] - box[0]) * (box[3] - box[1]), 1e-6)

    def touch(box, o):
        r = (o["x"], o["y"], o["x"] + o["width"], o["y"] + o["height"])
        return min(box[2], r[2]) - max(box[0], r[0]) > 0.5 and min(box[3], r[3]) - max(box[1], r[1]) > 0.5

    for e in layout["elements"]:
        if e.get("type") != "text":
            continue
        want = min(MIN_VISIBLE_FONT, src.get(e["id"], e)["font_size"])
        if e["font_size"] >= want:
            continue
        before = _ink_inside(e, tw, th)[1]
        # what it already overlapped may stay overlapped (its tag, its picture) - but a label that sat INSIDE a
        # shape/picture of its own group (a price on its tag) must stay inside it, and never grow onto a sibling text
        already = {id(o) for o in others(e) if touch(before, o) and o.get("type") != "text"}
        frames = [o for o in others(e) if o.get("type") == "shape" and mostly_in(before, o)
                  and o.get("group_id") and o.get("group_id") == e.get("group_id")]
        k = want / e["font_size"]
        mates = {id(o) for o in others(e) if o.get("group_id") and o.get("group_id") == e.get("group_id")}
        done = False
        # strict first (touch nothing new); then, so the text is at least VISIBLE, it may graze its own group-mates -
        # but a label that sat inside its tag/disc never spills out of it
        mate_text = {i for i in mates if any(id(o) == i and o.get("type") == "text" for o in others(e))}
        tiers = ((True, set()),                       # strict: touch nothing new, stay in its tag
                 (False, mates - mate_text),         # may outgrow its own pill/tag, never onto another text
                 (True, mates))                      # may graze a group-mate text, but stays inside its tag
        for keep_frames, extra in tiers:
            if done:
                break
            for width in (e["width"], min(tw - e["x"], e["width"] * k), min(tw, e["width"] * k)):
                trial = dict(e, font_size=want, width=width)
                if trial.get("letter_spacing"):
                    trial["letter_spacing"] = round(e["letter_spacing"] * k, 3)
                if e.get("rotation"):  # turn about the same centre
                    trial["x"] = e["x"] + (e["width"] - width) / 2
                # the box height matters for rotated text (it turns about the box centre): set it BEFORE checking
                new_h = measure_text(trial)["height"]
                if e.get("rotation"):
                    trial["y"] = e["y"] + (e["height"] - new_h) / 2
                trial["height"] = new_h
                ok, box = _ink_inside(trial, tw, th)
                if not ok:  # slide inside the canvas, if the text fits at all
                    trial["x"] -= max(0.0, box[2] - tw) + min(0.0, box[0])
                    trial["y"] -= max(0.0, box[3] - th) + min(0.0, box[1])
                    ok, box = _ink_inside(trial, tw, th)
                skip = already | extra
                if ok and (not keep_frames or all(inside(box, f) for f in frames)) and \
                        not any(touch(box, o) for o in others(e) if id(o) not in skip):
                    e.update(trial)
                    done = True
                    break


MIN_VISIBLE_FONT = 6  # px; smaller text is effectively invisible on the rendered PNG


def _panel_intruders(source: dict, layout: dict) -> int:
    """Texts that were not on a panel in the source but now sit on one (blue text on a navy panel is unreadable)."""
    by = {e["id"]: e for e in layout["elements"]}
    n = 0
    for pid, clients in _backdrops(source):
        p = by.get(pid)
        if p is None:
            continue
        for e in layout["elements"]:
            if e.get("type") != "text" or e["id"] in clients:
                continue
            cx, cy = e["x"] + e["width"] / 2, e["y"] + min(e["height"], e["font_size"] * 1.2) / 2
            n += p["x"] <= cx <= p["x"] + p["width"] and p["y"] <= cy <= p["y"] + p["height"]
    return n


ORDER_BAL = 0.8  # a headline that was above the pictures stays above if hero/headline balance keeps 80% of the best
CATALOGUE_GAIN = 1.05  # a banner catalogue re-flow must show this much more product (linear, total picture area)
INVERSION_GAP = 0.75  # "clearly smaller than the headline" in the source


def _inversions(source: dict, layout: dict) -> int:
    """Type hierarchy: how many texts that were clearly smaller than the headline in the source are now LARGER than it
    (a sub-line shouting over the headline reads as a mistake). Headline = the biggest non-fine-print text."""
    from engine.understand import _fine_like
    W, H = source["canvas"]["width"], source["canvas"]["height"]
    src = [e for e in source["elements"] if e.get("type") == "text" and not _fine_like(e, W, H)]
    if len(src) < 2:
        return 0
    ref = max(e["font_size"] for e in src)
    heads = {e["id"] for e in src if e["font_size"] >= 0.98 * ref}
    out = {e["id"]: e for e in layout["elements"]}
    top = max((out[i]["font_size"] for i in heads if i in out), default=0.0)
    return sum(1 for e in src if e["id"] not in heads and e["font_size"] < INVERSION_GAP * ref and e["id"] in out
               and out[e["id"]]["font_size"] > 1.02 * top)


def _keep_line_breaks(source: dict, layout: dict) -> None:
    """Text that was scaled together with its box (font and width by the same factor, give or take rounding) should
    break into the same lines as in the source. A font a hair larger than the box can wrap 'JUST FOR YOU:' into two
    lines that overflow the panel; trim the font back to the box's factor when that happens."""
    from engine.textmeasure import measure_text
    src = {e["id"]: e for e in source["elements"] if e.get("type") == "text"}
    for o in layout["elements"]:
        e = src.get(o.get("id"))
        if e is None or o.get("type") != "text" or e["width"] <= 0 or e["font_size"] <= 0:
            continue
        kw, kf = o["width"] / e["width"], o["font_size"] / e["font_size"]
        if not (kf > kw and kf <= 1.04 * kw + 0.6 / max(e["font_size"], 1e-6)):  # + whole-px rounding of small fonts
            continue
        n0 = measure_text(e)["n_lines"]
        if measure_text(o)["n_lines"] <= n0:
            continue
        for f in (e["font_size"] * kw, e["font_size"] * kw * 0.985, e["font_size"] * kw * 0.97):
            if f < MIN_VISIBLE_FONT <= o["font_size"] or f < 1:
                break  # never trade visibility (or the 1 px rule) for a line break
            trial = dict(o, font_size=round(f, 2))
            if o.get("letter_spacing"):
                trial["letter_spacing"] = round(o["letter_spacing"] * f / o["font_size"], 3)
            if measure_text(trial)["n_lines"] <= n0:
                o.update(font_size=trial["font_size"], letter_spacing=trial.get("letter_spacing", o.get("letter_spacing")))
                if o.get("letter_spacing") is None:
                    o.pop("letter_spacing", None)
                break


def _fix_inversions(source: dict, layout: dict) -> None:
    """Repair what _inversions counts: a text that was clearly smaller than the headline is brought back just under
    the headline's size (never below the visible minimum). Its box only shrinks, so it can't land on anything new."""
    from engine.understand import _fine_like
    from engine.textmeasure import measure_text
    W, H = source["canvas"]["width"], source["canvas"]["height"]
    src = [e for e in source["elements"] if e.get("type") == "text" and not _fine_like(e, W, H)]
    if len(src) < 2:
        return
    ref = max(e["font_size"] for e in src)
    heads = {e["id"] for e in src if e["font_size"] >= 0.98 * ref}
    out = {e["id"]: e for e in layout["elements"]}
    top = max((out[i]["font_size"] for i in heads if i in out), default=0.0)
    for e in src:
        o = out.get(e["id"])
        if o is None or e["id"] in heads or e["font_size"] >= INVERSION_GAP * ref or o["font_size"] <= 1.02 * top:
            continue
        new = max(MIN_VISIBLE_FONT, round(top * max(e["font_size"] / ref, 0.6), 2))
        if new >= o["font_size"]:
            continue
        k = new / o["font_size"]
        o["font_size"] = new
        if o.get("letter_spacing"):
            o["letter_spacing"] = round(o["letter_spacing"] * k, 3)
        h = measure_text(o)["height"]
        if h < o["height"]:  # keep the text where its block was centred
            o["y"] += (o["height"] - h) / 2
            o["height"] = h


def _visible_text(source: dict, layout: dict) -> int:
    """How many texts are still visible (>= MIN_VISIBLE_FONT, or at least their source size if that was smaller).
    Counted, not just pass/fail, so the layout that keeps the most text visible wins when none keeps all."""
    src = {e["id"]: e for e in source["elements"]}
    n = 0
    for e in layout["elements"]:
        if e.get("type") == "text" and e["id"] in src:
            n += e["font_size"] >= min(MIN_VISIBLE_FONT, src[e["id"]]["font_size"])
    return n


def _mirror(layout: dict) -> dict:
    """The same layout flipped left to right (rotations flip too). Positions only; nothing else changes."""
    import copy

    out = copy.deepcopy(layout)
    tw = out["canvas"]["width"]
    for e in out["elements"]:
        e["x"] = round(tw - e["x"] - e["width"], 2)
        if e.get("rotation"):
            e["rotation"] = -e["rotation"]
    return out


def candidates(source: dict[str, Any], target_canvas: dict[str, Any]) -> list:
    """All candidate layouts as (name, output). Index 0 is always the safety net."""
    from engine.layout import (ANCHOR_PARAMS, GROW_SPLIT_PARAMS, GROW_STACK_PARAMS, ROW_PARAMS, ROW_TIGHT_PARAMS, SPLIT_PARAMS,
                               SPLIT_WIDE_PARAMS, SPREAD_PARAMS, STACK_PARAMS, STACK_TIGHT_PARAMS, layout_row, layout_split, layout_split_grow, layout_spread,
                               layout_stack, layout_stack_grow, layout_anchor)
    from engine.understand import understand

    tw, th = target_canvas["width"], target_canvas["height"]
    canvas = {"width": tw, "height": th}
    from engine.finalize import finalize

    cands = [("safety", _finalized(source, safety_resize(source, target_canvas)))]

    design = understand(source)
    templates = [(layout_spread, SPREAD_PARAMS), (layout_anchor, ANCHOR_PARAMS)]
    # a collage (several separate pictures) only works as its original composition, scaled
    # pictures that carry their own caption (a group of picture + label) are a set of products a designer would happily
    # re-flow into a row or column; only loose, uncaptioned cut-outs scattered over the canvas form a collage
    loose = [u for u in design.units if u.role in ("product", "image")
             and not any(m["type"] == "text" for m in u.members)]
    collage = len(loose) >= COLLAGE_MIN
    if not collage:
        if tw / th >= 2.5:
            templates.append((layout_row, ROW_PARAMS + ROW_TIGHT_PARAMS))
        if tw / th <= 1.6:
            from engine.layout import story_variants
            story = 0.5 <= tw / th <= 0.6 and tw >= 500
            from engine.layout import head_on_top
            stack_ps = STACK_PARAMS + STACK_TIGHT_PARAMS + (story_variants(STACK_TIGHT_PARAMS + STACK_PARAMS[::4]) if story else [])
            if head_on_top(design):  # the title was above the product: also try keeping it there
                stack_ps = stack_ps + [dict(P, text_first=True) for P in stack_ps[::2]]
            templates.append((layout_stack, stack_ps))
            grow_ps = GROW_STACK_PARAMS + (story_variants(GROW_STACK_PARAMS) if story else [])
            if head_on_top(design):
                grow_ps = grow_ps + [dict(P, text_first=True) for P in grow_ps[::2]]
            templates.append((layout_stack_grow, grow_ps))
        if 1.0 <= tw / th <= 3.0:
            templates.append((layout_split, SPLIT_PARAMS + SPLIT_WIDE_PARAMS))
            templates.append((layout_split_grow, GROW_SPLIT_PARAMS))
    ids = {e["id"] for e in source["elements"]}
    import engine.layout as _lay
    _lay.TARGET = (float(tw), float(th))
    for fn, params in templates:
        for pi, P in enumerate(params):
            try:
                placed = fn(design, tw, th, P)
            except Exception:
                placed = None
            if placed and set(placed) == ids:
                cand = fit_backdrops(source, scale_letter_spacing(
                    source, {"canvas": canvas, "elements": [_round(placed[e["id"]]) for e in source["elements"]]}))
                try:  # lift tiny text where that is safe, so one 5px footer word can't disqualify a good layout
                    _raise_tiny_text(source, cand)
                except Exception:
                    pass
                try:  # a block scaled as a whole keeps its line breaks (rounding must not push a word down)
                    _keep_line_breaks(source, cand)
                except Exception:
                    pass
                try:  # a sub-line must never shout over the headline
                    _fix_inversions(source, cand)
                except Exception:
                    pass
                cands.append((f"{fn.__name__}#{pi}", cand))
    if tw >= 2.5 * th:  # banner strips only: a catalogue page may line its product cards up along the strip
        try:
            from engine.understand import catalogue_variant
            cat = catalogue_variant(design)
        except Exception:
            cat = None
        if cat is not None:
            card_imgs = {m["id"]: m for u in cat.units for part in (u.parts or []) for m in part if m["type"] == "image"}

            src_area = sum(m["width"] * m["height"] for m in card_imgs.values())

            def card_scale(c):  # how much product the viewer gets: total picture area, as a linear scale
                a = sum(e["width"] * e["height"] for e in c["elements"] if e["id"] in card_imgs)
                return (a / max(src_area, 1e-6)) ** 0.5
            # against the layouts that keep things apart (anchors keep pictures big by letting them overlap)
            beat = CATALOGUE_GAIN * max((card_scale(c) for n, c in cands
                                         if n.split("#")[0] in ("safety", "layout_spread", "layout_row")), default=0.0)
            for pi, P in enumerate(ROW_PARAMS + ROW_TIGHT_PARAMS):
                try:
                    placed = layout_row(cat, tw, th, P)
                except Exception:
                    placed = None
                if placed and set(placed) == ids:
                    cand = fit_backdrops(source, scale_letter_spacing(
                        source, {"canvas": canvas, "elements": [_round(placed[e["id"]]) for e in source["elements"]]}))
                    for fix in (_raise_tiny_text, _keep_line_breaks, _fix_inversions):
                        try:
                            fix(source, cand)
                        except Exception:
                            pass
                    if card_scale(cand) >= beat:  # only when the products actually come out bigger
                        cands.append((f"catalogue_row#{pi}", cand))
    try:  # layouts suggested by any plugged-in model (none ship with the engine)
        from engine.proposer import propose
        cands += [(n, scale_letter_spacing(source, c)) for n, c in propose(source, target_canvas)]
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
    # where the picture behind the text is poor, try the left-right mirror of the best layouts and keep it only if the
    # text gets clearly more readable (it flips reading order, so it has to earn its place)
    for name, c, m in sorted(scored, key=lambda t: -t[2]["score"])[:MIRROR_TOP]:
        if m["text_readable"] >= 0.95:
            continue
        mc = _mirror(c)
        mm = metrics(source, mc)
        if not mm["errors"] and mm["text_readable"] >= m["text_readable"] + MIRROR_GAIN:
            scored.append((name + "+mirror", mc, mm))
    # the spotlight image must keep close to the biggest share any clean layout can give it
    # size readability comes before the spotlight rule: in tiny banners a big picture must not cost the text its size
    best_size = max((m["readability"] for _, _, m in scored if m["overlap"] >= OVERLAP_OK), default=0.0)
    best_hero = max((m["hero_ratio"] for _, _, m in scored
                     if m["overlap"] >= OVERLAP_OK and m["readability"] >= SIZE_FRAC * best_size), default=0.0)
    from engine.understand import understand
    sw, sh = source["canvas"]["width"], source["canvas"]["height"]
    hero_area = sum(max(0.0, u.bbox[2] - u.bbox[0]) * max(0.0, u.bbox[3] - u.bbox[1]) for u in understand(source).heroes())
    frac = HERO_FRAC_DOMINANT if hero_area / (sw * sh) >= HERO_DOMINANT_SHARE else HERO_FRAC
    best_read = max((m["text_readable"] for _, _, m in scored if m["overlap"] >= OVERLAP_OK), default=0.0)
    # every element must stay visible (organisers' recap) and text that sits on a panel stays the only text on it:
    # prefer layouts where no text shrinks below a visible size and no other text lands on a panel
    vis = {name: _visible_text(source, c) - _panel_intruders(source, c) for name, c, _ in scored}
    best_vis = max((v for v in vis.values()), default=0)
    pool = [(n, c, m) for n, c, m in scored if m["overlap"] >= OVERLAP_OK and vis[n] >= best_vis
            and m["readability"] >= SIZE_FRAC * best_size] or scored
    # spotlight vs headline: a hero is not forced to grow beyond its original share, and neither the hero nor the
    # headline may be sacrificed for the other. Among layouts that keep the hero at least HERO_FLOOR of what is
    # possible, pick the most balanced one: the smaller of (hero kept, headline kept) as high as possible.
    hero_cap = max(min(max((m["hero_ratio"] for _, _, m in pool), default=0.0), 1.0), 1e-6)
    head_cap = max(max((m["head_raw"] for _, _, m in pool), default=0.0), 1e-6)

    def balance(m):
        return min(1.0, m["hero_ratio"] / hero_cap, m["head_raw"] / head_cap)

    hero_floor = (HERO_FLOOR_DOMINANT if frac == HERO_FRAC_DOMINANT else HERO_FLOOR) * hero_cap
    # a set of products/steps follows the canvas: stacked on a tall canvas, in a row on a wide one, as long as the
    # spotlight keeps ORIENT_HERO of the best share (a designer move, not a size win)
    sets = [u for u in understand(source).units if len(getattr(u, "parts", []) or []) >= 2]
    tall, wide = th >= 1.25 * tw, tw >= 1.25 * th

    def follows(c):
        if not sets or not (tall or wide):
            return True
        by = {e["id"]: e for e in c["elements"]}
        for u in sets:
            ys = []
            for part in u.parts:
                img = next((m for m in part if m["type"] == "image"), part[0])
                e = by.get(img["id"])
                if e:
                    ys.append((e["y"] + e["height"] / 2, e["height"]))
            if len(ys) < 2:
                continue
            spread = max(y for y, _ in ys) - min(y for y, _ in ys)
            stacked = spread > 0.5 * min(h for _, h in ys)
            if stacked != tall:
                return False
        return True
    best_bal = max((balance(m) for _, _, m in pool if m["hero_ratio"] >= hero_floor), default=0.0)
    inv = {name: _inversions(source, c) for name, c, _ in scored}
    best_inv = min((inv[n] for n, _, _ in pool), default=0)
    best, best_key = None, (-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1.0)
    from engine.layout import head_on_top
    _d = understand(source)
    _top = head_on_top(_d)
    _hid = _d.first("headline").members[0]["id"] if _top else None
    _pids = {m["id"] for u in _d.by_role("product") + _d.by_role("image") for m in u.members if m["type"] == "image"}

    def order_kept(c):
        """A headline that was above the pictures is still above them (only matters when everything else ties)."""
        if not _top:
            return True
        by = {e["id"]: e for e in c["elements"]}
        h = by.get(_hid)
        ps = [by[i] for i in _pids if i in by]
        if h is None or not ps:
            return True
        return h["y"] + h["height"] / 2 <= min(p["y"] + p["height"] / 2 for p in ps)

    def key_of(name, c, m, v, i):
        value = picker.predict(m, name, tw, th) if picker else m["score"]
        # collisions first; when NO layout is collision-free, the cleaner one still wins (graded, not pass/fail)
        return (round(min(m["overlap"], OVERLAP_OK), 2), v >= best_vis, m["logo"] >= LOGO_OK, m["readability"] >= SIZE_FRAC * best_size,
                m["hero_ratio"] >= hero_floor, i <= best_inv,
                follows(c) and m["hero_ratio"] >= ORIENT_HERO * hero_cap,
                order_kept(c) and balance(m) >= ORDER_BAL * best_bal,  # title stays on top if that costs little
                balance(m) >= BALANCE_FRAC * best_bal,
                m["text_readable"] >= READ_FRAC * best_read, value)

    best_m, best_name = None, None
    for name, c, m in scored:
        key = key_of(name, c, m, vis[name], inv[name])
        if key > best_key:
            best, best_key, best_m, best_name = c, key, m, name
    # the winner's text sits on a poor background (green type on a green band): try its mirror image too - only the
    # top-scoring layouts got a mirrored twin above, and the winner is not always among them
    if best is not None and best_m is not None and best_m["text_readable"] < 0.95:
        try:
            mc = _mirror(best)
            mm = metrics(source, mc)
            if not mm["errors"] and mm["text_readable"] >= best_m["text_readable"] + MIRROR_GAIN:
                mk = key_of(best_name + "+mirror", mc, mm, _visible_text(source, mc) - _panel_intruders(source, mc),
                            _inversions(source, mc))
                if mk[:-1] >= best_key[:-1]:
                    best = mc
        except Exception:
            pass
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
        out = _finalized(source, _smart(source, target_canvas))
        try:
            _grow_hero(source, out)
        except Exception:
            pass
        try:
            _close_gaps(out)
        except Exception:
            pass
        return out
    except Exception:
        pass
    try:
        return _finalized(source, safety_resize(source, target_canvas))
    except Exception:
        return _baseline_stretch(source, target_canvas)
