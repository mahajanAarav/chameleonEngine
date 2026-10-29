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
    """Mean luminance and busyness of an image's pixels under a canvas rectangle.

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
    return float(lum[mask].mean()), float(np.hypot(gx, gy)[mask].mean())
