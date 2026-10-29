"""Does the engine look at the real pixels behind text?    python -m tools.test_pixels [--sheet out.png]

Builds a synthetic background photo in a scratch folder (dark left third, bright middle third, busy noisy right
third), a design with white text on it, and checks that for every target size the engine's choice has text
that is at least as readable as the engine WITHOUT the readability rule would produce (it must never be worse), and
reports how much better it gets.
"""

import argparse
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

import engine.pixels as pixels
import engine.resize as R
from engine.rules import check
from engine.score import metrics

W, H = 1920, 1080
TARGETS = [(1080, 1080), (1080, 1920), (1600, 400), (728, 90), (300, 250), (1200, 628)]


def make_assets(folder: Path):
    rng = np.random.default_rng(1)
    a = np.zeros((H, W, 3), dtype=np.float32)
    a[:, : W // 3] = 0.08
    a[:, W // 3: 2 * W // 3] = 0.93
    a[:, 2 * W // 3:] = rng.random((H, W - 2 * W // 3, 1)) * np.array([1.0, 1.0, 1.0])
    Image.fromarray((a * 255).astype("uint8")).save(folder / "photo.png")
    Image.open(Path("brand_kit/assets/solstice_logo_lockup.png")).save(folder / "logo.png")


def design():
    white = "rgba(255,255,255,1)"
    return {"canvas": {"width": W, "height": H}, "elements": [
        {"id": "bg", "type": "image", "asset_id": "photo.png", "x": 0, "y": 0, "width": W, "height": H, "fit": "cover", "z_index": 0},
        {"id": "logo", "type": "image", "asset_id": "logo.png", "x": 65, "y": 765, "width": 215, "height": 80, "z_index": 5},
        {"id": "headline", "type": "text", "x": 62, "y": 860, "width": 700, "height": 70, "content": "AnyWhere, AnyTime",
         "font_family": "Solstice Sans", "font_size": 56, "font_weight": "bold", "color": white, "z_index": 6},
        {"id": "body", "type": "text", "x": 62, "y": 945, "width": 980, "height": 85, "content": "Watch our most impressive "
         "F-150 Raptor adapt to all nature conditions. Equipped with a high-powered engine and Terrain Management System.",
         "font_family": "Solstice Sans", "font_size": 20, "font_weight": "regular", "color": white, "z_index": 6}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="")
    a = ap.parse_args()
    folder = Path(tempfile.mkdtemp(prefix="pix_"))
    make_assets(folder)
    pixels.ASSETS = folder
    pixels.asset_array.cache_clear()
    pixels.asset_stats.cache_clear()
    src = design()
    ok = True
    outs = []
    print(f"{'target':>10s}  text readability before -> after (1.00 = comfortable)")
    for tw, th in TARGETS:
        tgt = {"width": tw, "height": th}
        R.READ_FRAC, R.MIRROR_TOP = 0.0, 0   # before: no readability rule, no mirrored candidates
        off = R.resize(src, tgt)
        R.READ_FRAC, R.MIRROR_TOP = 0.85, 10  # after
        on = R.resize(src, tgt)
        r_off, r_on = metrics(src, off)["text_readable"], metrics(src, on)["text_readable"]
        bad = [m for s, m in check(src, on) if s == "error"]
        good = r_on >= r_off - 1e-6 and not bad
        ok &= good
        print(f"{tw:>5d}x{th:<4d}  {r_off:.2f} -> {r_on:.2f}   {'ok' if good else 'WORSE or rule errors'}")
        outs.append((f"{tw}x{th}", on))
    if a.sheet:
        from PIL import ImageDraw

        from renderer.converter.convert import render_design_to_png
        cells = []
        for i, (label, o) in enumerate(outs):
            p = folder / f"o{i}.png"
            render_design_to_png(o, folder, p, fonts_dir="brand_kit/fonts")
            im = Image.open(p).convert("RGB")
            im.thumbnail((380, 300))
            c = Image.new("RGB", (400, 340), "white")
            c.paste(im, (10, 28))
            ImageDraw.Draw(c).text((10, 8), label, fill="black")
            cells.append(c)
        sheet = Image.new("RGB", (3 * 400, 2 * 340), "white")
        for i, c in enumerate(cells):
            sheet.paste(c, ((i % 3) * 400, (i // 3) * 340))
        sheet.save(a.sheet)
        print("sheet:", a.sheet)
    print("PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
