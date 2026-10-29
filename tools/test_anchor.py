"""Do things that visually belong together stay together?   python -m tools.test_anchor [--sheet out.png]

Two look-alikes of real critique cases (a bar under three burgers + a huge 'mmm'; a product with an aura behind it
and a shadow under it). For every target size we check that each bundled part keeps its position and size relative
to its bundle (within 2%) and that the outputs are rule-clean.
"""

import argparse

from engine.resize import resize
from engine.rules import check
from engine.safety import _footprint
from engine.understand import understand

ASSETS = "solstice_bottle.png"
BG = {"id": "bg", "type": "image", "asset_id": "solstice_bg_gradient.png", "x": 0, "y": 0, "width": 1080, "height": 1080,
      "fit": "cover", "z_index": 0}


def txt(i, c, x, y, w, size, **kw):
    return {"id": i, "type": "text", "x": x, "y": y, "width": w, "height": size * 1.3, "content": c,
            "font_family": "Solstice Sans", "font_size": size, "font_weight": kw.pop("bold", "bold"),
            "color": kw.pop("color", "rgba(240,178,66,1)"), "text_align": "center", "z_index": 6, **kw}


def burgers():
    els = [dict(BG)]
    els.append({"id": "bar", "type": "shape", "shape_type": "rectangle", "x": 140, "y": 760, "width": 800, "height": 70,
                "fill_color": "rgba(190,60,40,1)", "z_index": 3})
    for i, x in enumerate((160, 410, 660)):
        els.append({"id": f"burger{i}", "type": "image", "asset_id": ASSETS, "x": x, "y": 500, "width": 260,
                    "height": 260, "fit": "contain", "z_index": 4})
    els.append(txt("mmm", "mmm", 90, 180, 900, 220))
    els.append(txt("tag", "Taste the difference", 240, 900, 600, 34, bold="regular", color="rgba(255,255,255,1)"))
    return {"canvas": {"width": 1080, "height": 1080}, "elements": els}


def aura():
    els = [dict(BG)]
    els.append({"id": "aura", "type": "shape", "shape_type": "ellipse", "x": 280, "y": 240, "width": 520, "height": 520,
                "fill_color": "rgba(255,255,255,1)", "opacity": 0.35, "z_index": 2})
    els.append({"id": "shadow", "type": "shape", "shape_type": "ellipse", "x": 330, "y": 690, "width": 420,
                "height": 60, "fill_color": "rgba(0,0,0,1)", "opacity": 0.4, "z_index": 3})
    els.append({"id": "product", "type": "image", "asset_id": ASSETS, "x": 360, "y": 340, "width": 360, "height": 360,
                "fit": "contain", "z_index": 4})
    els.append(txt("headline", "Fresh at Solstice", 90, 60, 900, 64, color="rgba(255,255,255,1)"))
    els.append(txt("sub", "New summer collection now in store", 140, 800, 800, 28, bold="regular",
                   color="rgba(255,255,255,1)"))
    els.append(txt("price", "8", 440, 880, 200, 70, color="rgba(255,255,255,1)"))
    return {"canvas": {"width": 1080, "height": 1080}, "elements": els}


TARGETS = [(1080, 1350), (1600, 400), (1080, 1920), (728, 90), (300, 250), (970, 250)]


def bundles(src):
    return [u for u in understand(src).units if len(u.members) > 1 and u.role in ("product", "image")]


def rel(el, box):
    x0, y0, x1, y1 = _footprint(el)
    w, h = box[2] - box[0], box[3] - box[1]
    return ((x0 + x1) / 2 - box[0]) / w, ((y0 + y1) / 2 - box[1]) / h, (x1 - x0) / w, (y1 - y0) / h


def check_design(name, src, sheet, expect):
    found = bundles(src)
    ids = [sorted(m["id"] for m in u.members) for u in found]
    print(f"{name}: bundles detected: {ids}")
    want = sorted(sorted(g) for g in (expect if expect and isinstance(expect[0], list) else [expect]))
    ok = sorted(ids) == want
    if not ok:
        print(f"   WRONG: expected bundles {want}")
    worst = 0.0
    for tw, th in TARGETS:
        out = resize(src, {"width": tw, "height": th})
        errs = [m for s, m in check(src, out) if s == "error"]
        by_out = {e["id"]: e for e in out["elements"]}
        by_src = {e["id"]: e for e in src["elements"]}
        for u in found:
            sb = _union([by_src[m["id"]] for m in u.members])
            ob = _union([by_out[m["id"]] for m in u.members])
            for m in u.members:
                a, b = rel(by_src[m["id"]], sb), rel(by_out[m["id"]], ob)
                worst = max(worst, max(abs(x - y) for x, y in zip(a, b)))
        if errs:
            ok = False
            print(f"   {tw}x{th}: RULE ERRORS {errs[:2]}")
        sheet.append((f"{name} {tw}x{th}", out))
    print(f"   largest deviation of any bundled part from its original place in the bundle: {worst:.3f} (limit 0.02)")
    return ok and worst <= 0.02


def _union(els):
    bs = [_footprint(e) for e in els]
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="")
    a = ap.parse_args()
    sheet = []
    from tools.real_ads import ADS
    results = [check_design("burgers", burgers(), sheet, ["burger0", "burger1", "burger2", "bar"]),
               check_design("aura", aura(), sheet, ["product", "aura", "shadow"]),
               check_design("word-art", ADS["mmm_wordart"]["source"], sheet, [["b0", "b1", "b2"], ["m1", "m2", "m3"]])]
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
            im.thumbnail((420, 330))
            cell = Image.new("RGB", (440, 370), "white")
            cell.paste(im, (10, 30))
            ImageDraw.Draw(cell).text((10, 8), label, fill="black")
            cells.append(cell)
        cols = 4
        img = Image.new("RGB", (cols * 440, ((len(cells) + cols - 1) // cols) * 370), "white")
        for i, c in enumerate(cells):
            img.paste(c, ((i % cols) * 440, (i // cols) * 370))
        img.save(a.sheet)
        print("sheet:", a.sheet)
    print("PASS" if all(results) else "FAIL")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
