"""Understand a design: units, roles, importance, reading order.

Roles come from geometry and style only; ids are never read (the hidden
designs carry no labels). Unknown things fall back to generic roles.
"""

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

    def first(self, role: str):
        found = self.by_role(role)
        return found[0] if found else None


def _bbox(members):
    boxes = [_footprint(m) for m in members]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _is_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


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

    # 4. texts: headline = largest font; fine print; supporting; plain-text button
    if singles_text:
        fs = lambda u: u.members[0]["font_size"]
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
            if (not has_button and m.get("font_weight") == "bold" and m.get("color") != hc
                    and u.order > head.order):
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
    return Design(canvas=canvas, units=units)
