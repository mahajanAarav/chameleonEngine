"""Read (never change) image pixels to tell what an image is and what sits behind text.

Everything is cached and works on small copies (longest side 192 px), so it is fast. Missing or unreadable assets
return None and callers fall back to geometry alone.
"""

from functools import lru_cache
from pathlib import Path

import numpy as np

ASSETS = Path(__file__).resolve().parent.parent / "brand_kit" / "assets"
SMALL = 192


@lru_cache(maxsize=256)
def asset_array(asset_id: str):
    """RGBA float array (h, w, 4) in 0..1, longest side <= SMALL, or None."""
    try:
        from PIL import Image

        im = Image.open(ASSETS / str(asset_id)).convert("RGBA")
        im.thumbnail((SMALL, SMALL))
        return np.asarray(im, dtype=np.float32) / 255.0
    except Exception:
        return None


def luminance(rgb: np.ndarray) -> np.ndarray:
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def to_linear(c: np.ndarray) -> np.ndarray:
    """sRGB 0..1 to linear light (what contrast ratios are defined on)."""
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def rel_luminance(rgb: np.ndarray) -> np.ndarray:
    return luminance(to_linear(rgb))


@lru_cache(maxsize=256)
def asset_stats(asset_id: str):
    """transparent (share of clearly transparent pixels), mean_alpha, busy (edge strength), luma; or None."""
    a = asset_array(asset_id)
    if a is None:
        return None
    alpha = a[..., 3]
    lum = luminance(a[..., :3])
    gy, gx = np.gradient(lum)
    seen = alpha >= 0.1
    return {"transparent": float((alpha < 0.1).mean()), "mean_alpha": float(alpha.mean()),
            "visible": float(seen.mean()), "alpha_visible": float(alpha[seen].mean()) if seen.any() else 0.0,
            "busy": float(np.hypot(gx, gy).mean()), "luma": float(lum.mean())}


def is_cutout(asset_id: str) -> bool:
    """A subject cut out of its background: a real share of the image is transparent and what remains is solid."""
    s = asset_stats(asset_id)
    return bool(s) and 0.12 <= s["transparent"] <= 0.97 and s["alpha_visible"] >= 0.6


def is_soft(asset_id: str) -> bool:
    """A glow, aura or shadow: what is visible is faint (low opacity), not a solid subject."""
    s = asset_stats(asset_id)
    return bool(s) and s["visible"] > 0.02 and s["alpha_visible"] < 0.5


def luma_under(asset_id: str, img_box: tuple, fit: str, rect: tuple):
    """Mean (linear) luminance and busyness of an image's pixels under a canvas rectangle.

    img_box = (x, y, w, h) of the image element on the canvas; fit = cover / contain / fill; rect = (x0, y0, x1, y1)
    on the canvas. Returns (mean_luma, busy) or None if the image or overlap is unavailable.
    """
    a = asset_array(asset_id)
    if a is None:
        return None
    ih, iw = a.shape[:2]
    x, y, w, h = img_box
    if w <= 0 or h <= 0:
        return None
    if fit == "fill":
        sx, sy = w / iw, h / ih
    elif fit == "cover":
        sx = sy = max(w / iw, h / ih)
    else:
        sx = sy = min(w / iw, h / ih)
    ox, oy = x + (w - iw * sx) / 2, y + (h - ih * sy) / 2
    c0, c1 = int(max(0, (rect[0] - ox) / sx)), int(min(iw, np.ceil((rect[2] - ox) / sx)))
    r0, r1 = int(max(0, (rect[1] - oy) / sy)), int(min(ih, np.ceil((rect[3] - oy) / sy)))
    if c1 - c0 < 1 or r1 - r0 < 1:
        return None
    patch = a[r0:r1, c0:c1]
    lum = luminance(patch[..., :3])
    mask = patch[..., 3] > 0.5
    if not mask.any():
        return None
    gy, gx = np.gradient(lum) if min(lum.shape) > 1 else (np.zeros_like(lum), np.zeros_like(lum))
    return float(rel_luminance(patch[..., :3])[mask].mean()), float(np.hypot(gx, gy)[mask].mean())


@lru_cache(maxsize=256)
def asset_size(asset_id: str):
    """Natural (width, height) of an asset, or None."""
    try:
        from PIL import Image

        with Image.open(ASSETS / str(asset_id)) as im:
            return im.size
    except Exception:
        return None


def hidden_fraction(lower: dict, upper: dict, grid: int = 40):
    """How much of `lower`'s visible picture is covered by `upper`'s visible pixels, in the source layout.

    0.0 = they only touch (or overlap where one is transparent): safe to take apart.
    Higher = part of the lower picture is hidden; that part does not exist in its file, so separating them would
    show a picture with a piece missing. Returns None when an asset can't be read (caller falls back to boxes).
    """
    a, b = asset_array(lower.get("asset_id")), asset_array(upper.get("asset_id"))
    if a is None or b is None or lower["width"] <= 0 or lower["height"] <= 0 or upper["width"] <= 0 or upper["height"] <= 0:
        return None
    seen = covered = 0
    for i in range(grid):
        for j in range(grid):
            u, v = (i + 0.5) / grid, (j + 0.5) / grid
            ya, xa = min(int(v * a.shape[0]), a.shape[0] - 1), min(int(u * a.shape[1]), a.shape[1] - 1)
            if a[ya, xa, 3] < 0.5:
                continue
            seen += 1
            cx, cy = lower["x"] + u * lower["width"], lower["y"] + v * lower["height"]
            ub, vb = (cx - upper["x"]) / upper["width"], (cy - upper["y"]) / upper["height"]
            if 0 <= ub < 1 and 0 <= vb < 1:
                yb, xb = min(int(vb * b.shape[0]), b.shape[0] - 1), min(int(ub * b.shape[1]), b.shape[1] - 1)
                covered += b[yb, xb, 3] >= 0.5
    return covered / seen if seen else 0.0


def bite_fraction(lower: dict, upper: dict):
    """How much of `lower`'s outline runs along `upper`'s opaque pixels, in the source layout.

    A picture that was cut out from behind another one (a logo behind a person's head) has an outline that FOLLOWS
    the front picture: a bite. The bitten part does not exist in its file, so the two can't be shown apart. Two
    products that merely touch share only a few outline pixels. Returns 0..1, or None when an asset can't be read.
    """
    a, b = asset_array(lower.get("asset_id")), asset_array(upper.get("asset_id"))
    if a is None or b is None or min(lower["width"], lower["height"], upper["width"], upper["height"]) <= 0:
        return None
    op = a[..., 3] >= 0.5
    h, w = op.shape
    if h < 3 or w < 3:
        return 0.0
    pad = np.pad(op, 1, constant_values=False)
    inner = pad[1:-1, 1:-1]
    hole_next = ~pad[:-2, 1:-1] | ~pad[2:, 1:-1] | ~pad[1:-1, :-2] | ~pad[1:-1, 2:]
    edge = inner & hole_next
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = False  # the file's own border is a crop, not a bite
    ys, xs = np.nonzero(edge)
    if len(xs) < 8:
        return 0.0
    cx = lower["x"] + (xs + 0.5) / w * lower["width"]
    cy = lower["y"] + (ys + 0.5) / h * lower["height"]
    r = max(2.0, 0.02 * min(lower["width"], lower["height"]))
    bh, bw = b.shape[:2]
    hit = np.zeros(len(xs), bool)
    for dx, dy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)):
        ub = (cx + dx - upper["x"]) / upper["width"]
        vb = (cy + dy - upper["y"]) / upper["height"]
        inside = (ub >= 0) & (ub < 1) & (vb >= 0) & (vb < 1)
        xb = np.clip((ub * bw).astype(int), 0, bw - 1)
        yb = np.clip((vb * bh).astype(int), 0, bh - 1)
        hit |= inside & (b[yb, xb, 3] >= 0.5)
    return float(hit.mean())
