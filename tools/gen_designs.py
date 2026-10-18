"""Synthetic Solstice-style test designs.

generate(seed) -> source design (deterministic). Seeds divisible by 5 form the
held-out split, which we never tune on.
"""

import argparse
import json
import random
from pathlib import Path

from engine.textmeasure import measure_text

BG, LOGO, PRODUCT = "solstice_bg_gradient.png", "solstice_logo_lockup.png", "solstice_bottle.png"
MISSING = "solstice_holiday_badge_2025.png"
ORANGE, PLUM, RED = "rgba(232,106,58,1)", "rgba(43,27,46,1)", "rgba(220,60,50,1)"
WHITE = "rgba(255,255,255,1)"

CANVASES = [(1080, 1080), (1080, 1350), (1080, 1920), (1200, 628), (1600, 900), (1080, 566)]
HEADLINES = [
    "Chase the Light",
    "Summer Starts Here",
    "Golden Hour in a Bottle",
    "Taste the Season",
    "Introducing the All-New Limited-Batch Solstice Chase the Light Botanical Sparkling Collection — Crafted Exclusively for Golden Hour Gatherings",
    "New Season, New Sparkle: Meet the Botanical Infusions Everyone Is Talking About",
]
SUBHEADS = [
    "Botanical sparkling infusions, crafted for golden hour.",
    "Small-batch botanical infusions blended with wild honey, blood orange zest and a hint of sea salt, made for long summer evenings.",
    "Refreshingly different.",
]
BADGES = ["NEW FLAVOR", "LIMITED EDITION", "AWARD WINNING 2026", "SMALL BATCH", "ZERO SUGAR"]
CTAS = ["Shop the Summer Line", "Order Now", "Discover More", "Get Yours Today"]
LEGAL = "Please drink responsibly. Botanical Sparkling Co., 2026. Void where prohibited. See solstice.com/terms for full details."


def split_of(seed: int) -> str:
    return "heldout" if seed % 5 == 0 else "train"


def _text(eid, content, x, y, w, size, *, serif=False, bold=False, color=WHITE, align="center", z=5, **extra):
    el = {
        "id": eid, "type": "text", "x": x, "y": y, "width": w, "height": 0, "z_index": z,
        "content": content, "font_family": "Solstice Serif" if serif else "Solstice Sans",
        "font_size": int(size), "font_weight": "bold" if bold else "regular",
        "color": color, "text_align": align, **extra,
    }
    while measure_text(el)["max_line_width"] > w and el["font_size"] > 8:
        el["font_size"] = int(el["font_size"] * 0.92)
    el["height"] = round(measure_text(el)["height"], 1)
    return el


def _pill(prefix, label, cx, y, h, color, size, z=3):
    """Rounded rectangle plus a label sitting in it (label boxes are top-anchored)."""
    probe = _text(prefix + "_label", label, 0, 0, 2000, size, bold=True)
    w = round(measure_text(probe)["max_line_width"] + h * 1.2)
    x = round(cx - w / 2)
    bg = {"id": prefix + "_bg", "type": "shape", "shape_type": "rectangle", "x": x, "y": y, "width": w, "height": h,
          "fill_color": color, "corner_radius": h / 2, "z_index": z, "group_id": prefix}
    lab = _text(prefix + "_label", label, x, round(y + (h - size * 1.2) / 2 - 0.15 * size), w, size, bold=True,
                z=z + 2, group_id=prefix)
    return [bg, lab], w


def generate(seed: int) -> dict:
    r = random.Random(seed)
    W, H = r.choice(CANVASES)
    u = min(W, H) / 1080
    wide = W / H >= 1.5
    els: list[dict] = []

    els.append({"id": "bg", "type": "image", "asset_id": BG, "x": 0, "y": 0, "width": W, "height": H,
                "fit": "cover", "z_index": 0})

    # content column: whole canvas, or the right half for wide designs
    cx0, cx1 = (W * 0.52, W * 0.96) if wide else (W * 0.05, W * 0.95)
    cw = cx1 - cx0
    ccx = (cx0 + cx1) / 2
    mx = (W * 0.26) if wide else W / 2  # centre of the media column

    for attempt in range(8):
        k = 0.9 ** attempt
        body: list[dict] = []
        y = 50 * u * k

        logo_w = 320 * u * k
        logo_h = logo_w / r.choice([3.0, 3.2])
        body.append({"id": "logo", "type": "image", "asset_id": LOGO, "x": round(mx - logo_w / 2), "y": round(y),
                     "width": round(logo_w), "height": round(logo_h), "fit": "contain", "z_index": 5})

        has_product = r.random() < 0.75
        yt = y
        if wide:
            y = y + logo_h + 20 * u
            if has_product:
                ps = min(H - y - 60 * u, W * 0.4) * k ** 0.5
                body.append({"id": "product", "type": "image", "asset_id": PRODUCT, "x": round(mx - ps / 2),
                             "y": round(y), "width": round(ps), "height": round(ps), "fit": "contain", "z_index": 3})
            y = max(50 * u * k, (H - 0.8 * H) / 2)  # text column starts near the top third
        else:
            y += logo_h + 30 * u * k
            if has_product:
                ps = min(0.36 * H, 0.55 * W) * k ** 0.5
                body.append({"id": "product", "type": "image", "asset_id": PRODUCT, "x": round(W / 2 - ps / 2),
                             "y": round(y), "width": round(ps), "height": round(ps), "fit": "contain", "z_index": 3})
                y += ps + 30 * u * k

        text_start_y = y
        hs = r.choice([44, 52, 60, 72]) * u * k
        head = _text("headline", r.choice(HEADLINES), round(cx0), round(y), round(cw), hs, serif=True, bold=True, z=5)
        if r.random() < 0.5 and len(head["content"]) > 12:
            head["style_runs"] = [{"start": 6, "end": 16, "color": "rgba(240,178,66,1)"}]
        body.append(head)
        y += head["height"] + 24 * u * k

        if r.random() < 0.7:
            sub = _text("subhead", r.choice(SUBHEADS), round(cx0 + cw * 0.05), round(y), round(cw * 0.9),
                        r.choice([22, 24, 28]) * u * k, color="rgba(255,255,255,0.85)", z=5)
            body.append(sub)
            y += sub["height"] + 28 * u * k

        n_badges = r.choice([0, 0, 1, 2, 3])
        if n_badges:
            labels = r.sample(BADGES, n_badges)
            size = 15 * u * max(k, 0.8)
            h = round(50 * u * max(k, 0.8))
            built = [_pill(f"badge{i + 1}", lab, 0, round(y), h, r.choice([ORANGE, PLUM, ORANGE]), size)
                     for i, lab in enumerate(labels)]
            gap = 20 * u
            total = sum(w for _, w in built) + gap * (len(built) - 1)
            if total > cw:  # too wide for one row: keep two at most
                built = built[:2]
                total = sum(w for _, w in built) + gap
            x = ccx - total / 2
            for parts, w in built:
                dx = round(x - parts[0]["x"] - 0)
                for p in parts:
                    p["x"] += dx
                body.extend(parts)
                x += w + gap
            y += h + 30 * u * k

        ch = round(90 * u * max(k, 0.8))
        if r.random() < 0.65:
            parts, w = _pill("cta", r.choice(CTAS), ccx, round(y), ch, ORANGE, 22 * u * max(k, 0.8))
            body.extend(parts)
            y += ch
        else:
            cta = _text("cta", r.choice(CTAS), round(cx0), round(y), round(cw), 30 * u * k, bold=True,
                        color=ORANGE, z=5)
            body.append(cta)
            y += cta["height"]

        if y <= H - 70 * u or attempt == 7:
            break

    els.extend(body)
    # when the text column is shorter than the canvas in a wide design, centre it vertically
    if wide:
        used = [e for e in body if e["id"] not in ("logo", "product")]
        top = min(e["y"] for e in used)
        bottom = max(e["y"] + e["height"] for e in used)
        shift = round((H - (bottom - top)) / 2 - top)
        for e in used:
            e["y"] += shift

    # optional extras
    if r.random() < 0.5:
        for i, (d, ox, oy, op) in enumerate([(500, -100, -100, 0.15), (300, 0.65, 0.65, 0.12)][: r.choice([1, 2])]):
            d = round(d * u)
            x = round(ox * W) if isinstance(ox, float) else round(ox * u)
            yy = round(oy * H) if isinstance(oy, float) else round(oy * u)
            els.append({"id": f"deco_circle_{i + 1}", "type": "shape", "shape_type": "ellipse", "x": x, "y": yy,
                        "width": d, "height": d, "fill_color": WHITE, "opacity": op, "z_index": 1})
    if r.random() < 0.3:
        rw, rh = round(300 * u), round(54 * u)
        rx, ry = round(W - rw - 40 * u), round(30 * u)
        rot = r.choice([-12, -8, 8, 12])
        els.append({"id": "ribbon_bg", "type": "shape", "shape_type": "rectangle", "x": rx, "y": ry, "width": rw,
                    "height": rh, "fill_color": RED, "corner_radius": 6 * u, "rotation": rot, "z_index": 4,
                    "group_id": "ribbon"})
        els.append(_text("ribbon_label", "SUNSET SALE", rx, round(ry + (rh - 24 * u) / 2 - 3 * u), rw, 20 * u,
                         bold=True, z=6, rotation=rot, group_id="ribbon"))
    if r.random() < 0.3:
        els.append({"id": "holiday_watermark", "type": "image", "asset_id": r.choice([MISSING, PRODUCT]),
                    "x": round(W - 230 * u), "y": round(H - 100 * u), "width": round(180 * u),
                    "height": round(80 * u), "z_index": 2})
    if r.random() < 0.5:
        els.append(_text("legal_text", LEGAL, round(60 * u), round(H - 40 * u), round(W - 120 * u), 12 * u,
                         color="rgba(255,255,255,0.6)", z=6))

    return {"canvas": {"width": W, "height": H}, "elements": els}


def generate_set(split: str, n: int, start: int = 1) -> list[tuple[int, dict]]:
    out, seed = [], start
    while len(out) < n:
        if split == "all" or split_of(seed) == split:
            out.append((seed, generate(seed)))
        seed += 1
    return out


def validate_source(src: dict) -> list:
    """A generated design should pass the strict checker against itself (identity resize)."""
    from tools.check import check
    # decoration bleed and a rotated ribbon poking out are deliberate (as in the official samples)
    intended = ("deco_circle", "ribbon_bg")
    return [p for p in check(src, src) if p[0] == "error" and not p[1].startswith(intended)]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train", choices=["train", "heldout", "all"])
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    bad = 0
    for seed, src in generate_set(a.split, a.n):
        errs = validate_source(src)
        bad += bool(errs)
        print(f"seed {seed:3d} {src['canvas']['width']}x{src['canvas']['height']} "
              f"{len(src['elements'])} elements" + (f"  INVALID: {errs[:2]}" if errs else ""))
        if a.out:
            Path(a.out).mkdir(parents=True, exist_ok=True)
            json.dump({"source": src}, open(Path(a.out) / f"design_{seed:03d}.json", "w"), indent=1)
    print("invalid designs:", bad)
