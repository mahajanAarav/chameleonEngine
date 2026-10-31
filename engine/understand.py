"""Understand a design: units, roles, importance, reading order.

Roles come from geometry and style only; ids are never read (the hidden
designs carry no labels). Unknown things fall back to generic roles.
"""

import re
from dataclasses import dataclass, field

from engine.safety import _footprint, _units, is_background

IMPORTANCE = {
    "bg": 0.0, "headline": 1.0, "logo": 0.95, "product": 0.9, "cta": 0.9, "cta_text": 0.9,
    "supporting": 0.7, "badge": 0.5, "ribbon": 0.45, "text": 0.5, "group": 0.5, "image": 0.5,
    "shape": 0.3, "watermark": 0.2, "fine_print": 0.15, "decoration": 0.1,
}


@dataclass
class Unit:
    uid: str
    members: list
    role: str = "other"
    bbox: tuple = (0, 0, 0, 0)
    z: int = 0
    importance: float = 0.5
    order: int = 0
    parts: list = field(default_factory=list)  # an ordered set: the pieces the layout may re-arrange (row/column/grid)
    set_axis: str = ""

    @property
    def w(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def h(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass
class Design:
    canvas: dict
    units: list = field(default_factory=list)
    ref_font: float = 0.0  # biggest font that is not fine print (headline size, even when it sits inside a lockup)

    def by_role(self, role: str) -> list:
        return [u for u in self.units if u.role == role]

    def hero_score(self, u) -> float:
        """How much an image unit looks like the point of the ad: its share of the canvas, boosted when it is a
        cut-out subject (transparent edges) and when it sits near the middle."""
        W, H = self.canvas["width"], self.canvas["height"]
        share = _area(u.bbox) / (W * H)
        score = share ** 0.5
        ids = [m.get("asset_id") for m in u.members if m["type"] == "image"]
        try:
            from engine import pixels
            if any(pixels.is_cutout(i) for i in ids if i):
                score *= 1.4
        except Exception:
            pass
        cx, cy = (u.bbox[0] + u.bbox[2]) / 2, (u.bbox[1] + u.bbox[3]) / 2
        off = (((cx - W / 2) / (W / 2)) ** 2 + ((cy - H / 2) / (H / 2)) ** 2) ** 0.5 / 1.414
        return score * (0.7 + 0.3 * (1 - min(1.0, off)))

    def heroes(self) -> list:
        """The spotlight: the image unit that most looks like the point of the ad (a bundle or cluster counts as one),
        plus any other image unit at least 70% as spotlight-like."""
        imgs = [u for u in self.units if u.role in ("product", "image")]
        if not imgs:
            return []
        scores = {id(u): self.hero_score(u) for u in imgs}
        top = max(scores.values())
        return [u for u in imgs if scores[id(u)] >= 0.7 * top]

    def first(self, role: str):
        found = self.by_role(role)
        return found[0] if found else None


def _bbox(members):
    boxes = [_footprint(m) for m in members]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


COLLAGE_IMAGES = 4  # this many separate pictures make a collage: none of them is a corner logo
_FINE = re.compile(r"©|®|™|\(c\)|copyright|all rights|www\.|https?://|\.com\b|\.co\.|@\w|"
                   r"\b[\w-]+\.(com|net|org|co|uk|io|tv|pt|de|fr|es|it|ca|us|me|app|shop|store)\b", re.I)


def _fine_like(el: dict, W: float, H: float) -> bool:
    """Tiny text, or legal / web-address text that is small, is fine print however large it is next to nothing else."""
    rel = el["font_size"] / min(W, H)
    return rel < 0.017 or (bool(_FINE.search(str(el.get("content", "")))) and rel < 0.05)


_CTA = re.compile(r"^\s*(shop|buy|order|get|learn|discover|visit|book|try|sign|join|call|find|explore|download|start|see|"
                  r"subscribe|register|reserve|claim|save)\b", re.I)
PRICE = re.compile(r"(€|\$|£|¥)\s?\d|\d+([.,]\d{1,2})?\s?(€|\$|£|¥)|\d+\s?%\s?(off|rabatt|desc)", re.I)


def _is_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _near_edge(u, W, H, band=0.25) -> bool:
    cx, cy = (u.bbox[0] + u.bbox[2]) / 2 / W, (u.bbox[1] + u.bbox[3]) / 2 / H
    return min(cx, 1 - cx) <= band or min(cy, 1 - cy) <= band


def _corner_dist(u, W, H) -> float:
    cx, cy = (u.bbox[0] + u.bbox[2]) / 2 / W, (u.bbox[1] + u.bbox[3]) / 2 / H
    return min(cx, 1 - cx) + min(cy, 1 - cy)


def _framed_text(units: list, W: float, H: float):
    """A word drawn on top of a small piece of artwork that surrounds it (a price inside an arc of text, a word on a
    badge picture) is one piece of design: merge them so they move and scale together. Big pictures (products,
    photos) are not frames: text over them is ordinary overlap. Returns the merged unit if it holds the headline."""
    head_unit = None
    frames = [u for u in units if len(u.members) == 1 and u.members[0]["type"] == "image"
              and u.role in ("logo", "image", "watermark") and _area(u.bbox) <= 0.15 * W * H]
    for f in frames:
        for t in [u for u in units if len(u.members) == 1 and u.members[0]["type"] == "text"
                  and u.role in ("headline", "supporting", "text", "cta_text")]:
            ix = max(0.0, min(f.bbox[2], t.bbox[2]) - max(f.bbox[0], t.bbox[0]))
            iy = max(0.0, min(f.bbox[3], t.bbox[3]) - max(f.bbox[1], t.bbox[1]))
            if t.z >= f.z and ix * iy >= 0.7 * max(_area(t.bbox), 1e-6):
                was_head = t.role == "headline"
                f.members += t.members
                f.bbox = _bbox(f.members)
                f.z = max(f.z, t.z)
                f.order = min(f.order, t.order)
                f.role = "image"
                units.remove(t)
                if was_head:
                    head_unit = f
                break
    if head_unit is not None:  # the next biggest single text leads the remaining copy
        rest = [u for u in units if len(u.members) == 1 and u.members[0]["type"] == "text"
                and u.role in ("supporting", "text", "cta_text")]
        if rest:
            new_head = max(rest, key=lambda u: (u.members[0]["font_size"], -u.order))
            for u in rest:
                if u.role == "headline":
                    u.role = "supporting"
            new_head.role = "headline"
    return head_unit


_PRICE = re.compile(r"[$€£¥¢%]|\d[\d.,]*\s*(off|%)|\d+[.,]\d\d", re.I)


def _picture_led(u) -> bool:
    """A group whose biggest member is a picture (a product card with a price tag or an 'Only at' sticker) is not a
    pill/badge, even though it holds a shape and a text: the tag belongs to the picture."""
    imgs = [m["width"] * m["height"] for m in u.members if m["type"] == "image"]
    shapes = [m["width"] * m["height"] for m in u.members if m["type"] == "shape"]
    return bool(imgs) and max(imgs) >= max(shapes, default=0.0)


def _on_picture(t, imgs) -> bool:
    for m in imgs:
        ix = max(0.0, min(t["x"] + t["width"], m["x"] + m["width"]) - max(t["x"], m["x"]))
        iy = max(0.0, min(t["y"] + t["height"], m["y"] + m["height"]) - max(t["y"], m["y"]))
        if ix * iy >= 0.7 * t["width"] * t["height"]:
            return True
    return False


_TITLE_LOCKUPS = set()


def _classify_groups(units: list, W: float, H: float):
    """Give grouped units (that are not pills or ribbons) a real role instead of a generic "group":

    * picture + caption : the picture fills most of the group  -> product / image (sized like one)
    * brand lockup      : small picture + small short text near an edge (logo + slogan) -> logo
    * headline lockup   : the group holding the biggest text in the design -> scales as one block like
                          word-art, and counts as the headline for importance
    Returns the headline lockup unit, if any.
    """
    def texts(u):
        return [m for m in u.members if m["type"] == "text"]

    def fs(u):
        return max((m["font_size"] for m in texts(u)), default=0.0)

    groups = [u for u in units if len(u.members) > 1 and u.role == "group"]
    single_head = max((u.members[0]["font_size"] for u in units if len(u.members) == 1 and u.role in
                       ("headline", "supporting", "text", "cta_text")), default=0.0)
    top_fs = max((fs(u) for u in groups), default=0.0)
    for u in groups:
        imgs = [m for m in u.members if m["type"] == "image"]
        img_area = sum(m["width"] * m["height"] for m in imgs)
        big = [t for t in texts(u) if t["font_size"] >= 0.999 * fs(u)]
        if (imgs and fs(u) >= single_head and fs(u) >= top_fs and big
                and all(_on_picture(t, imgs) for t in big)):
            continue  # words printed ON the artwork (a ribbon, a banner) with the biggest type: headline lockup below
        if imgs and img_area >= 0.35 * _area(u.bbox) and img_area >= 0.03 * W * H:
            u.role = "product"
        elif (imgs and img_area <= 0.06 * W * H and _near_edge(u, W, H) and fs(u) <= 0.045 * min(W, H)
              and all(len(str(m.get("content", "")).split()) <= 4 for m in texts(u))
              and not any(_PRICE.search(str(m.get("content", ""))) for m in texts(u))):  # a price tag is no slogan
            u.role = "logo"
    # several picture groups: the biggest is the product, the rest are images (each still a spotlight candidate)
    pics = [u for u in groups if u.role == "product"]
    for u in pics:
        if u is not max(pics, key=lambda v: _area(v.bbox)):
            u.role = "image"
    lockups = [u for u in groups if u.role == "group" and texts(u)]
    if not lockups:
        return None
    top = max(lockups, key=fs)
    if fs(top) < single_head:
        if fs(top) >= 0.7 * single_head:  # nearly headline-sized title lockup (icon + title): a block, ranked high
            top.role = "image"
            top.importance = IMPORTANCE["logo"]
            _TITLE_LOCKUPS.add(id(top))
        return None
    if single_head > 0:  # the lockup is the headline: single texts that called themselves headline step down
        for u in units:
            if u.role == "headline":
                u.role = "supporting"
    top.role = "image"
    return top


HIDDEN_MIN = 0.05  # this much of a picture hidden behind another = they were drawn as one and must stay together


def _occluded(a, b) -> bool:
    """Does one of these overlapping pictures hide part of the other? Measured on the real pixels (transparency),
    falling back to box overlap when an image can't be read. Pictures that only touch can be taken apart and
    re-arranged; a picture whose hidden part is missing from its file can't be shown on its own."""
    ia = [m for m in a.members if m["type"] == "image"]
    ib = [m for m in b.members if m["type"] == "image"]
    try:
        from engine.pixels import hidden_fraction
        worst = None
        for x in ia:
            for y in ib:
                lo, up = (x, y) if int(x.get("z_index") or 0) <= int(y.get("z_index") or 0) else (y, x)
                f = hidden_fraction(lo, up)
                if f is None:
                    worst = None
                    raise ValueError
                worst = f if worst is None else max(worst, f)
        if worst is not None:
            return worst >= HIDDEN_MIN
    except Exception:
        pass
    ix = max(0.0, min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0]))
    iy = max(0.0, min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1]))
    return ix * iy >= 0.25 * min(_area(a.bbox), _area(b.bbox))


_CONNECTOR = re.compile(r"^\s*(from|by|with|at|and|&|x|presented by|powered by|brought to you by|sponsored by|"
                        r"in partnership with|courtesy of|only at|only on|available at|exclusively at)\s*[:.,]?\s*$", re.I)


def _attach_connectors(units: list, W: float, H: float) -> list:
    """A connector word ("from", "by", "presented by", ...) only makes sense next to the thing it introduces (usually a
    logo). If it touches or sits right beside a picture/logo unit, it joins that unit and moves with it, so it can
    never end up floating on its own ("from" ... from whom?)."""
    gap = 0.04 * min(W, H)
    for t in [u for u in units if len(u.members) == 1 and u.members[0]["type"] == "text"
              and u.role not in ("headline", "bg") and _CONNECTOR.match(str(u.members[0].get("content", "")))]:
        best, best_d = None, None
        for u in units:
            if u is t or u.role in ("bg", "headline") or not any(m["type"] == "image" for m in u.members):
                continue
            dx = max(u.bbox[0] - t.bbox[2], t.bbox[0] - u.bbox[2], 0.0)
            dy = max(u.bbox[1] - t.bbox[3], t.bbox[1] - u.bbox[3], 0.0)
            d = (dx * dx + dy * dy) ** 0.5
            # prefer the logo / the unit holding a logo when several pictures are equally close
            has_logo = u.role == "logo" or any(m["type"] == "image" and _area(_bbox([m])) <= 0.12 * W * H
                                              for m in u.members if len(u.members) > 1)
            key = d - (0.5 * gap if has_logo else 0.0)
            if d <= gap and (best_d is None or key < best_d):
                best, best_d = u, key
        if best is not None:
            best.members += t.members
            best.bbox = _bbox(best.members)
            best.z = max(best.z, t.z)
            best.order = min(best.order, t.order)
            units.remove(t)
    return units


def _attach_underlines(units: list, W: float, H: float) -> list:
    """A thin wide stroke (a hand-drawn underline, a rule) right under a text underlines THAT text: it joins the text,
    together with the lines stacked directly above it that read as one phrase ("So many / ways to / Save!"), and the
    block scales as one type lockup. Otherwise the stroke would drift off and underline nothing."""
    def is_stroke(u):
        if len(u.members) != 1 or u.members[0]["type"] not in ("image", "shape") or u.role == "bg":
            return False
        return u.w >= 4 * max(u.h, 1e-6) and u.h <= 0.08 * H and u.w >= 0.1 * W

    def single_text(u):
        return len(u.members) == 1 and u.members[0]["type"] == "text" and u.role not in ("bg", "fine_print")

    def hover(a, b):
        return max(0.0, min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0]))

    for st in [u for u in units if is_stroke(u)]:
        best, best_d = None, None
        for t in units:
            if not single_text(t):
                continue
            fs = t.members[0]["font_size"]
            d = st.bbox[1] - t.bbox[3]  # stroke top below text bottom (negative = they overlap)
            ty = (t.bbox[1] + t.bbox[3]) / 2
            if -0.6 * fs <= d <= 0.6 * fs and st.bbox[1] >= ty and hover(st, t) >= 0.6 * min(st.w, t.w):
                if best_d is None or abs(d) < best_d:
                    best, best_d = t, abs(d)
        if best is None:
            continue
        block = [best]
        while True:  # lines stacked right above, overlapping horizontally: same phrase
            top = min(block, key=lambda u: u.bbox[1])
            nxt = [t for t in units if single_text(t) and t not in block and (t.bbox[1] + t.bbox[3]) / 2 < top.bbox[1]
                   and top.bbox[1] - t.bbox[3] <= 0.8 * t.members[0]["font_size"]
                   and hover(t, top) >= 0.5 * min(t.w, top.w)]
            if not nxt:
                break
            block.append(max(nxt, key=lambda t: t.bbox[3]))
        imp = max(t.importance for t in block)
        lead = block[0]
        for t in block[1:] + [st]:
            lead.members += t.members
            lead.z = max(lead.z, t.z)
            lead.order = min(lead.order, t.order)
            units.remove(t)
        lead.bbox = _bbox(lead.members)
        lead.role = "image"  # a type lockup: keeps its own composition, scales as one block
        lead.importance = imp
    return units


CATALOGUE_MIN = 4  # product cards (picture + its own caption/price) that make a page a catalogue
CATALOGUE_SPREAD = 6.0  # biggest card at most this many times the smallest (else one is the hero, not a peer)
BITE_MIN = 0.2  # this much of a picture's outline follows a picture in front of it = it was cut out from behind it


def _bitten(a: dict, b: dict) -> bool:
    """Is one of these pictures partly hidden by the other, so its hidden part is missing from its file? Either the
    front picture's pixels cover it (hidden_fraction) or its outline follows the front picture (a bite)."""
    try:
        from engine.pixels import hidden_fraction, bite_fraction
    except Exception:
        return False
    za, zb = int(a.get("z_index") or 0), int(b.get("z_index") or 0)
    orders = [(a, b)] if za < zb else [(b, a)] if zb < za else [(a, b), (b, a)]  # same layer: either may be behind
    for lo, up in orders:
        hf, bf = hidden_fraction(lo, up), bite_fraction(lo, up)
        if (hf is not None and hf >= HIDDEN_MIN) or (bf is not None and bf >= BITE_MIN):
            return True
    return False


def _attach_bitten(units: list, W: float, H: float) -> list:
    """Pictures that only exist together travel together, whatever unit each one sits in (a logo behind a person's
    head, a product half behind another). Separating them would show a logo or product with a piece missing, and we
    can never paint the missing piece back. Inside an ordered set the two pieces become one piece."""
    def imgs(u):
        return [m for m in u.members if m["type"] == "image" and not (m["width"] >= 0.95 * W and m["height"] >= 0.95 * H)]

    def touch(m, n):
        return (min(m["x"] + m["width"], n["x"] + n["width"]) - max(m["x"], n["x"]) > 0 and
                min(m["y"] + m["height"], n["y"] + n["height"]) - max(m["y"], n["y"]) > 0)

    def part_of(u, m):
        for i, part in enumerate(u.parts or []):
            if any(x is m for x in part):
                return i
        return None

    for u in units:  # inside one set: bitten pieces become one piece
        merged = True
        while merged and u.parts and len(u.parts) >= 2:
            merged = False
            for i in range(len(u.parts)):
                for j in range(i + 1, len(u.parts)):
                    pi = [m for m in u.parts[i] if m["type"] == "image"]
                    pj = [m for m in u.parts[j] if m["type"] == "image"]
                    if any(touch(m, n) and _bitten(m, n) for m in pi for n in pj):
                        u.parts[i] = u.parts[i] + u.parts[j]
                        del u.parts[j]
                        merged = True
                        break
                if merged:
                    break

    changed = True
    while changed:
        changed = False
        cand = [u for u in units if u.role != "bg" and imgs(u)]
        for i, a in enumerate(cand):
            for b in cand[i + 1:]:
                pair = next(((m, n) for m in imgs(a) for n in imgs(b) if touch(m, n) and _bitten(m, n)), None)
                if pair is None:
                    continue
                m, n = pair
                keep, gone = (a, b) if (len(a.parts or []), a.importance, _area(a.bbox)) >= \
                    (len(b.parts or []), b.importance, _area(b.bbox)) else (b, a)
                anchor = m if keep is a else n
                if gone.parts:  # both are sets: too tangled to re-arrange - keep the composition
                    keep.parts, keep.set_axis = [], ""
                elif keep.parts:
                    k = part_of(keep, anchor)
                    if k is None:
                        keep.parts, keep.set_axis = [], ""
                    else:
                        keep.parts[k] = keep.parts[k] + gone.members
                keep.members += gone.members
                keep.bbox = _bbox(keep.members)
                keep.z = max(keep.z, gone.z)
                keep.order = min(keep.order, gone.order)
                keep.importance = max(keep.importance, gone.importance)
                units.remove(gone)
                changed = True
                break
            if changed:
                break
    # a set whose pieces were glued together may be left with one piece: then it is just a unit
    for u in units:
        if u.parts and len(u.parts) < 2:
            u.parts, u.set_axis = [], ""
    return units


def _attach(units: list, canvas: dict) -> list:
    """Bundle things that visually belong together, from geometry alone.

    * cluster : images that touch or sit within ~3% of each other side by side (e.g. three burgers)
    * halo    : a shape or image BEHIND an image that contains its centre (an aura, a glow)
    * base    : a shape or image behind an image, directly under it (a bar the product stands on, a shadow)
    The bundle keeps the anchor's role, moves and scales as one unit, so relative position and size survive.
    """
    m = min(canvas["width"], canvas["height"])
    free = lambda u: len(u.members) == 1 and u.members[0]["type"] in ("shape", "image") and u.role in (
        "decoration", "shape", "image", "product")
    gap = 0.03 * m

    def merge(a, b):
        a.members += b.members
        a.bbox = _bbox(a.members)
        a.z = max(a.z, b.z)
        a.order = min(a.order, b.order)
        units.remove(b)

    # 1. clusters of touching images
    changed = True
    while changed:
        changed = False
        imgs = [u for u in units if u.role in ("product", "image") and all(m["type"] == "image" for m in u.members)]
        for i, a in enumerate(imgs):
            for b in imgs[i + 1:]:
                dx = max(a.bbox[0] - b.bbox[2], b.bbox[0] - a.bbox[2])
                dy = max(a.bbox[1] - b.bbox[3], b.bbox[1] - a.bbox[3])
                v_overlap = min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1])
                ix = min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0])
                iy = min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1])
                stacked = ix > 0 and iy > 0 and _occluded(a, b)  # one hides part of the other: they only exist together
                if (dx <= gap and dy <= 0 and v_overlap >= 0.5 * min(a.h, b.h)) or stacked:
                    big = a if _area(a.bbox) >= _area(b.bbox) else b
                    small = b if big is a else a
                    merge(big, small)
                    changed = True
                    break
            if changed:
                break

    # 1b. a set: 3+ similar pictures (or picture + caption groups) lined up in a row OR a column keep their order and
    # travel as one unit, but the layout may re-arrange the parts (row / column / grid) to fit the new shape
    def find_set(axis):
        lo, hi = (0, 2) if axis == "x" else (1, 3)
        olo, ohi = (1, 3) if axis == "x" else (0, 2)
        pics = sorted([u for u in units if u.role in ("product", "image") and any(m["type"] == "image" for m in u.members)],
                      key=lambda u: u.bbox[lo])
        row = []
        for u in pics:
            if row:
                prev = row[-1]
                over = min(prev.bbox[ohi], u.bbox[ohi]) - max(prev.bbox[olo], u.bbox[olo])
                span = min(prev.bbox[ohi] - prev.bbox[olo], u.bbox[ohi] - u.bbox[olo])
                similar = 0.4 <= _area(u.bbox) / max(_area(prev.bbox), 1e-6) <= 2.5
                close = u.bbox[lo] - prev.bbox[hi] <= max(prev.bbox[hi] - prev.bbox[lo], u.bbox[hi] - u.bbox[lo])
                if not (over >= 0.5 * span and similar and close):
                    if len(row) >= 3:
                        break
                    row = []
            row.append(u)
        return row if len(row) >= 3 else []

    for axis in ("x", "y"):
        row = find_set(axis)
        if not row:
            continue
        parts = [list(u.members) for u in row]  # reading order (left to right, or top to bottom)
        lead = max(row, key=lambda u: _area(u.bbox))
        lead.role = "product"
        for u in row:
            if u is not lead:
                merge(lead, u)
        lead.parts = parts
        lead.set_axis = axis

    # 2. halos and bases behind an anchor image
    anchors = [u for u in units if u.role in ("product", "image") and u.members[0]["type"] == "image"]
    for a in anchors:
        acx, acy = (a.bbox[0] + a.bbox[2]) / 2, (a.bbox[1] + a.bbox[3]) / 2
        for s in list(units):
            if s is a or not free(s) or s.role == "product" or s.z > a.z:
                continue
            if s.members[0]["type"] == "shape" and any(  # a panel that text sits on is a backdrop, not an accessory
                    t.members[0]["type"] == "text" and s.bbox[0] <= (t.bbox[0] + t.bbox[2]) / 2 <= s.bbox[2]
                    and s.bbox[1] <= (t.bbox[1] + t.bbox[3]) / 2 <= s.bbox[3] for t in units if len(t.members) == 1):
                continue
            sb = s.bbox
            if s.members[0]["type"] == "image" and s.role == "image" and _area(sb) >= _area(a.bbox):
                continue  # a bigger image is not an accessory of a smaller one
            ratio = _area(sb) / max(_area(a.bbox), 1e-6)
            halo = sb[0] <= acx <= sb[2] and sb[1] <= acy <= sb[3] and 0.5 <= ratio <= 8
            h_over = min(sb[2], a.bbox[2]) - max(sb[0], a.bbox[0])
            base = (h_over >= 0.6 * min(sb[2] - sb[0], a.w) and acy <= sb[1] <= a.bbox[3] + 0.06 * m
                    and sb[3] >= a.bbox[3] - 0.05 * a.h and sb[3] - sb[1] <= 1.2 * a.h)
            if halo or base:
                merge(a, s)
                acx, acy = (a.bbox[0] + a.bbox[2]) / 2, (a.bbox[1] + a.bbox[3]) / 2
    return units


def _text_bundles(units: list, canvas: dict) -> list:
    """Text pieces that are really one piece of artwork become a single block that scales as a unit:
    * lockups: boxes that overlap a lot and differ in size (staggered words like "express / your")
    * word-art: short pieces (a letter or two) standing side by side on one line (letters that grow in size)
    Normal stacked headlines and body copy are left alone so they can still re-wrap."""
    pieces = [u for u in units if len(u.members) == 1 and u.members[0]["type"] == "text"
              and u.role in ("headline", "supporting", "text") and not u.members[0].get("rotation")]

    def tie(a, b):
        ea, eb = a.members[0], b.members[0]
        ia = max(0.0, min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0]))
        ib = max(0.0, min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1]))
        small = max(min(a.w * a.h, b.w * b.h), 1e-6)
        ratio = max(ea["font_size"], eb["font_size"]) / max(min(ea["font_size"], eb["font_size"]), 1e-6)
        if ia * ib / small >= 0.25 and ratio >= 1.3:
            return True
        short = len(str(ea.get("content", "")).strip()) <= 3 and len(str(eb.get("content", "")).strip()) <= 3
        gap = max(a.bbox[0] - b.bbox[2], b.bbox[0] - a.bbox[2])
        return bool(short and ib >= 0.6 * min(a.h, b.h) and gap <= 0.35 * max(ea["font_size"], eb["font_size"]))

    changed = True
    while changed:
        changed = False
        for i, a in enumerate(pieces):
            for b in pieces[i + 1:]:
                if tie(a, b):
                    a.members += b.members
                    a.bbox = _bbox(a.members)
                    a.z = max(a.z, b.z)
                    a.order = min(a.order, b.order)
                    a.role = "image"
                    units.remove(b)
                    pieces.remove(b)
                    changed = True
                    break
            if changed:
                break
    return units


def understand(source: dict) -> Design:
    canvas = source["canvas"]
    W, H = canvas["width"], canvas["height"]
    elements = source["elements"]
    units = []
    for i, members in enumerate(_units(elements)):
        uid = members[0].get("group_id") or members[0]["id"]
        units.append(Unit(uid=uid, members=members, bbox=_bbox(members),
                          z=max(int(m.get("z_index") or 0) for m in members)))

    def cx(u): return (u.bbox[0] + u.bbox[2]) / 2
    def cy(u): return (u.bbox[1] + u.bbox[3]) / 2

    # reading order: top to bottom, then left to right
    for n, u in enumerate(sorted(units, key=lambda u: (round(cy(u) / (0.04 * H)), cx(u)))):
        u.order = n

    # 1. things decided by structure alone
    pills, singles_text, singles_img = [], [], []
    for u in units:
        m0 = u.members[0]
        if len(u.members) == 1:
            if is_background(m0, canvas):
                u.role = "bg"
            elif m0["type"] == "shape":
                u.role = "decoration" if (m0.get("opacity", 1) <= 0.35) else "shape"
            elif m0["type"] == "image":
                singles_img.append(u)
            else:
                singles_text.append(u)
        else:
            types = {m["type"] for m in u.members}
            if any(m.get("rotation") for m in u.members) and "shape" in types:
                u.role = "ribbon"
            elif "shape" in types and "text" in types and not _picture_led(u):
                pills.append(u)
            else:
                u.role = "group"

    # 2. pills: the button is the biggest non-uppercase pill; the rest are badges
    def shape_area(u):
        s = next(m for m in u.members if m["type"] == "shape")
        return s["width"] * s["height"]

    def label(u):
        return " ".join(str(m.get("content", "")) for m in u.members if m["type"] == "text")

    def pill_shape(u):
        return next(m for m in u.members if m["type"] == "shape")

    def siblings(a, b):
        sa, sb = pill_shape(a), pill_shape(b)
        return (sa.get("fill_color") == sb.get("fill_color")
                and abs(sa["height"] - sb["height"]) <= 0.25 * max(sa["height"], sb["height"]))

    for u in pills:
        u.role = "badge"
    tags = {id(u) for u in pills for v in pills if v is not u and siblings(u, v) and not _CTA.search(label(u))}
    buttons = [u for u in pills if (not _is_upper(label(u)) or _CTA.search(label(u))) and id(u) not in tags]
    if buttons:
        max(buttons, key=shape_area).role = "cta"

    # 3. images: logo (wide, near top), watermark (small, low), product (largest)
    logos = [u for u in singles_img if u.w / max(u.h, 1e-6) >= 2 and u.w <= 0.5 * W and cy(u) <= 0.3 * H]
    if logos:
        max(logos, key=lambda u: u.z).role = "logo"
    elif 2 <= len(singles_img) < COLLAGE_IMAGES:
        biggest = max(singles_img, key=lambda u: u.w * u.h)
        corner = [u for u in singles_img if u is not biggest and u.w * u.h <= 0.04 * W * H and _near_edge(u, W, H)]
        if corner:
            min(corner, key=lambda u: _corner_dist(u, W, H)).role = "logo"
    for u in singles_img:
        if u.role != "other":
            continue
        area = u.w * u.h
        if area <= 0.05 * W * H and cy(u) >= 0.8 * H:
            u.role = "watermark"
    rest = [u for u in singles_img if u.role == "other"]
    if rest:
        big = max(rest, key=lambda u: u.w * u.h)
        big.role = "product" if big.w * big.h >= 0.04 * W * H else "image"
    for u in singles_img:
        if u.role == "other":
            u.role = "image"

    # 4. texts: fine print first (never a headline, even when it is the only text), then headline = largest font,
    #    supporting, plain-text button
    if singles_text:
        fs = lambda u: u.members[0]["font_size"]
        for u in singles_text:
            if _fine_like(u.members[0], W, H):
                u.role = "fine_print"
        singles_text = [u for u in singles_text if u.role == "other"]
    for u in list(singles_text):
        m = u.members[0]
        if m["font_size"] >= 0.2 * min(W, H) and _area(u.bbox) >= 0.2 * W * H and len(str(m.get("content", "")).split()) <= 2:
            u.role = "image"  # word-art that dominates the canvas: keep its proportion like a picture
            singles_text.remove(u)
    if singles_text:
        head = max(singles_text, key=lambda u: (fs(u), -u.order))
        head.role = "headline"
        for u in singles_text:
            if u is head:
                continue
            m = u.members[0]
            small = fs(u) / min(W, H) <= 0.017
            faint_low = m.get("opacity", 1) < 0.8 and cy(u) > 0.85 * H
            if small or faint_low:
                u.role = "fine_print"
        left = sorted([u for u in singles_text if u.role == "other"], key=lambda u: u.order)
        hc = head.members[0].get("color")
        has_button = any(u.role == "cta" for u in units)
        for u in left:
            m = u.members[0]
            said_cta = bool(_CTA.search(str(m.get("content", "")))) and len(str(m.get("content", "")).split()) <= 6
            if not has_button and u.order > head.order and (
                    said_cta or (m.get("font_weight") == "bold" and m.get("color") != hc)):
                u.role = "cta_text"
        ctas = [u for u in left if u.role == "cta_text"]
        for u in ctas[:-1]:
            u.role = "text"
        for u in left:
            if u.role == "other" and u.order > head.order:
                u.role = "supporting"
        for u in left:
            if u.role == "other":
                u.role = "text"

    head_lockup = _classify_groups(units, W, H)
    framed = _framed_text(units, W, H)
    if framed is not None and head_lockup is None:
        head_lockup = framed
    for u in units:
        if u.role == "other":
            u.role = "group" if len(u.members) > 1 else "text"
        u.importance = IMPORTANCE["logo"] if id(u) in _TITLE_LOCKUPS else IMPORTANCE.get(u.role, 0.5)
    _TITLE_LOCKUPS.clear()
    if head_lockup is not None:
        head_lockup.importance = IMPORTANCE["headline"]
    units = _text_bundles(units, canvas)
    units = _attach(units, canvas)
    units = _attach_connectors(units, W, H)
    units = _attach_underlines(units, W, H)
    units = _attach_bitten(units, W, H)
    fonts = [m["font_size"] for u in units if u.role not in ("fine_print", "bg") for m in u.members
             if m["type"] == "text" and not _fine_like(m, W, H)]
    return Design(canvas=canvas, units=units, ref_font=max(fonts, default=0.0))


def catalogue_variant(design: "Design"):
    """A catalogue page (4+ product cards - picture + its own price/caption - scattered over the page, similar in
    size) seen as ONE set the layout may re-flow, in reading order. Returned as a separate copy, used only for wide
    banner candidates: the cards can line up along the strip instead of shrinking the whole page into a corner.
    None when the page is not a catalogue (or already has a set)."""
    import copy
    if any(u.parts for u in design.units):
        return None
    cards = [u for u in design.units if u.role in ("product", "image")
             and any(x["type"] == "image" for x in u.members) and any(x["type"] == "text" for x in u.members)]
    if len(cards) < CATALOGUE_MIN:
        return None
    areas = sorted(_area(u.bbox) for u in cards)
    if areas[-1] > CATALOGUE_SPREAD * areas[0]:
        return None
    d = copy.deepcopy(design)
    cards = [u for u in d.units if u.uid in {c.uid for c in cards} and u.role in ("product", "image")]
    H0 = d.canvas["height"]
    cards.sort(key=lambda u: (round(((u.bbox[1] + u.bbox[3]) / 2) / (0.12 * H0)), (u.bbox[0] + u.bbox[2]) / 2))
    lead = max(cards, key=lambda u: _area(u.bbox))
    lead.parts = [list(u.members) for u in cards]
    for u in cards:
        if u is not lead:
            lead.members += u.members
            lead.z = max(lead.z, u.z)
            lead.order = min(lead.order, u.order)
            d.units.remove(u)
    lead.bbox = _bbox(lead.members)
    lead.role, lead.set_axis = "product", "x"
    lead.importance = max(lead.importance, IMPORTANCE["product"])
    return d
