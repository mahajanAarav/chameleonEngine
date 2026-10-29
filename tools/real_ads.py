"""Look-alikes of the real ads in Purva's "Project Chameleon Testing Material" (boxes read off the screenshots;
every picture is one of our three stand-in assets, since only geometry matters to the engine).

    python -m tools.real_ads [--sheet out.png]

For each ad and target size it reports:
  hero    how much of the canvas the spotlight image keeps (output share / source share; 1.0 = same share)
  text    the biggest text growth vs its source size relative to the canvas (flags tiny text blowing up)
  rules   hard-rule errors
"""

import argparse

from engine.resize import resize
from engine.rules import check
from engine.safety import _footprint

BG, LOGO, PROD = "solstice_bg_gradient.png", "solstice_logo_lockup.png", "solstice_bottle.png"
WHITE = "rgba(255,255,255,1)"


def img(i, asset, x, y, w, h, z=4, fit="contain", **kw):
    return {"id": i, "type": "image", "asset_id": asset, "x": x, "y": y, "width": w, "height": h, "fit": fit,
            "z_index": z, **kw}


def txt(i, c, x, y, w, size, bold=True, color=WHITE, z=6, align="left", **kw):
    return {"id": i, "type": "text", "x": x, "y": y, "width": w, "height": round(size * 1.25), "content": c,
            "font_family": "Solstice Sans", "font_size": size, "font_weight": "bold" if bold else "regular",
            "color": color, "text_align": align, "z_index": z, **kw}


def bg(w, h):
    return img("bg", BG, 0, 0, w, h, z=0, fit="cover")


def design(w, h, els, hero):
    return {"source": {"canvas": {"width": w, "height": h}, "elements": els}, "hero": hero}


def mcd(labels):
    els = [bg(632, 316), img("logo", LOGO, 50, 118, 72, 75, z=5),
           {"id": "divider", "type": "shape", "shape_type": "rectangle", "x": 131, "y": 115, "width": 2, "height": 180,
            "fill_color": WHITE, "z_index": 5},
           img("potato", PROD, 160, 140, 100, 175), img("fries", PROD, 295, 128, 125, 187),
           img("box", PROD, 465, 140, 125, 175),
           txt("copyright", "©2005 McDonald's", 40, 276, 80, 7, bold=False, color="rgba(255,255,255,0.6)")]
    if labels:
        els += [txt("before", "before", 165, 62, 90, 26), txt("after", "after", 330, 62, 70, 26),
                txt("right_after", "right after", 455, 62, 140, 26)]
    return design(632, 316, els, ["potato", "fries", "box"])


def heinz():
    els = [bg(888, 1252), img("tower", PROD, 70, 30, 350, 1170), txt("headline", "No one grows ketchup like Heinz.", 400, 140, 450, 56),
           img("logo", LOGO, 480, 1060, 300, 100, z=5)]
    return design(888, 1252, els, ["tower"])


def ikea():
    els = [bg(1377, 2048), txt("headline", "Fresh at IKEA", 120, 110, 760, 150),
           txt("sub", "New summer collection now in store", 125, 430, 820, 56, bold=False),
           {"id": "shadow", "type": "shape", "shape_type": "ellipse", "x": 480, "y": 1620, "width": 600, "height": 60,
            "fill_color": "rgba(0,0,0,1)", "opacity": 0.25, "z_index": 3},
           img("cushion", PROD, 325, 655, 750, 1010),
           {"id": "tag_bg", "type": "shape", "shape_type": "rectangle", "x": 1012, "y": 893, "width": 104, "height": 46,
            "fill_color": "rgba(190,70,30,1)", "z_index": 3, "group_id": "tag"},
           txt("tag_label", "New", 1012, 900, 104, 30, align="center", group_id="tag"),
           txt("model", "GULLBERGSÖ", 1012, 950, 280, 34), txt("kind", "Cushion cover", 1012, 990, 280, 34, bold=False),
           txt("price", "8€", 1012, 1040, 200, 90),
           txt("l1", "IKEA.pt", 190, 1775, 120, 34, bold=False), txt("l2", "Click & Collect", 392, 1775, 200, 34, bold=False),
           txt("l3", "Deliveries", 690, 1775, 150, 34, bold=False), img("logo", LOGO, 898, 1728, 348, 140, z=5),
           txt("copy", "© Inter IKEA Systems B.V. 2022", 40, 1760, 180, 12, bold=False, color="rgba(255,255,255,0.6)",
               rotation=-90)]
    return design(1377, 2048, els, ["cushion"])


def pizza():
    els = [bg(500, 707), txt("headline", "See the Leaning Tower of Pizza", 55, 75, 400, 30),
           img("tower", PROD, 65, 215, 285, 440), img("logo", LOGO, 350, 530, 100, 95, z=5),
           txt("tag", "Visit the Italian places now...", 250, 672, 240, 12, bold=False)]
    return design(500, 707, els, ["tower"])


def starbucks():
    els = [bg(1920, 1080), img("d1", PROD, 515, 275, 222, 490), img("d2", PROD, 685, 395, 270, 500),
           img("d3", PROD, 955, 310, 270, 490), img("d4", PROD, 1150, 575, 290, 380),
           img("logo", LOGO, 1743, 57, 125, 125, z=5)]
    return design(1920, 1080, els, ["d1", "d2", "d3", "d4"])


def ford():
    els = [bg(1920, 1080), img("logo", LOGO, 65, 765, 215, 80, z=5),
           txt("headline", "AnyWhere, AnyTime", 62, 860, 700, 56),
           txt("body", "Watch our most impressive F-150 Raptor adapt to all nature conditions - (desert, jungle and Snow). "
                       "Equipped with a high-powered 3.5-liter EcoBoost engine and Terrain Management System, the F-150 "
                       "Raptor takes on all obstacles, taking it to a frightening new level", 62, 945, 980, 20, bold=False)]
    return design(1920, 1080, els, [])


ADS = {"mcd_copyright_only": mcd(False), "mcd_with_labels": mcd(True), "heinz": heinz(), "ikea": ikea(),
       "pizza": pizza(), "starbucks": starbucks(), "ford": ford()}
TARGETS = [(1080, 1080), (1080, 1920), (1600, 400), (728, 90), (300, 250), (1200, 628)]


def union(els):
    bs = [_footprint(e) for e in els]
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


def share(els, cw, ch):
    x0, y0, x1, y1 = union(els)
    return (x1 - x0) * (y1 - y0) / (cw * ch)


def evaluate(name, ad, tw, th):
    src = ad["source"]
    sw, sh = src["canvas"]["width"], src["canvas"]["height"]
    out = resize(src, {"width": tw, "height": th})
    by_src = {e["id"]: e for e in src["elements"]}
    by_out = {e["id"]: e for e in out["elements"]}
    errs = [m for s, m in check(src, out) if s == "error"]
    hero = None
    if ad["hero"]:
        hero = share([by_out[i] for i in ad["hero"]], tw, th) / share([by_src[i] for i in ad["hero"]], sw, sh)
    worst, who = 0.0, ""
    for e in src["elements"]:
        if e["type"] == "text":
            g = (by_out[e["id"]]["font_size"] / min(tw, th)) / (e["font_size"] / min(sw, sh))
            if g > worst:
                worst, who = g, e["id"]
    return out, hero, worst, who, errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="")
    a = ap.parse_args()
    sheet = []
    print(f"{'ad':20s} {'target':>10s}  hero-share  biggest text growth        rules")
    for name, ad in ADS.items():
        for tw, th in TARGETS:
            out, hero, worst, who, errs = evaluate(name, ad, tw, th)
            hs = f"{hero:6.2f}" if hero is not None else "   n/a"
            flag = "  <-- grew too much" if worst > 2.2 else ""
            print(f"{name:20s} {tw:>5d}x{th:<5d}  {hs}      {worst:5.2f}x ({who}){flag}   {len(errs)} errors")
            sheet.append((f"{name} {tw}x{th}", out))
    if a.sheet:
        from pathlib import Path

        from PIL import Image, ImageDraw

        from renderer.converter.convert import render_design_to_png
        tmp = Path(a.sheet).with_suffix("")
        tmp.mkdir(parents=True, exist_ok=True)
        cells = []
        for i, (label, out) in enumerate(sheet):
            p = tmp / f"c{i}.png"
            render_design_to_png(out, Path("brand_kit/assets"), p)
            im = Image.open(p).convert("RGB")
            im.thumbnail((380, 300))
            cell = Image.new("RGB", (400, 340), "white")
            cell.paste(im, (10, 28))
            ImageDraw.Draw(cell).text((10, 8), label, fill="black")
            cells.append(cell)
        cols = 6
        img_ = Image.new("RGB", (cols * 400, ((len(cells) + cols - 1) // cols) * 340), "white")
        for i, c in enumerate(cells):
            img_.paste(c, ((i % cols) * 400, (i // cols) * 340))
        img_.save(a.sheet)
        print("sheet:", a.sheet)


if __name__ == "__main__":
    main()
