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


_FINE = re.compile(r"©|®|™|\(c\)|copyright|all rights|www\.|https?://|\.com\b|\.co\.", re.I)


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
                if dx <= gap and dy <= 0 and v_overlap >= 0.5 * min(a.h, b.h):
                    big = a if _area(a.bbox) >= _area(b.bbox) else b
                    small = b if big is a else a
                    merge(big, small)
                    changed = True
                    break
            if changed:
                break

    # 2. halos and bases behind an anchor image
    anchors = [u for u in units if u.role in ("product", "image") and u.members[0]["type"] == "image"]
    for a in anchors:
        acx, acy = (a.bbox[0] + a.bbox[2]) / 2, (a.bbox[1] + a.bbox[3]) / 2
        for s in list(units):
            if s is a or not free(s) or s.role == "product" or s.z > a.z:
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
            if any(m.get("rotation") for m in u.members):
                u.role = "ribbon"
            elif "shape" in types and "text" in types:
                pills.append(u)
            else:
                u.role = "group"

    # 2. pills: the button is the biggest non-uppercase pill; the rest are badges
    def shape_area(u):
        s = next(m for m in u.members if m["type"] == "shape")
        return s["width"] * s["height"]

    def label(u):
        return " ".join(str(m.get("content", "")) for m in u.members if m["type"] == "text")

    for u in pills:
        u.role = "badge"
    buttons = [u for u in pills if not _is_upper(label(u))]
    if buttons:
        max(buttons, key=shape_area).role = "cta"

    # 3. images: logo (wide, near top), watermark (small, low), product (largest)
    logos = [u for u in singles_img if u.w / max(u.h, 1e-6) >= 2 and u.w <= 0.5 * W and cy(u) <= 0.3 * H]
    if logos:
        max(logos, key=lambda u: u.z).role = "logo"
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

    for u in units:
        if u.role == "other":
            u.role = "group" if len(u.members) > 1 else "text"
        u.importance = IMPORTANCE.get(u.role, 0.5)
    units = _text_bundles(units, canvas)
    units = _attach(units, canvas)
    return Design(canvas=canvas, units=units)
