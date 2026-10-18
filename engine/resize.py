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
    try:
        return safety_resize(source, target_canvas)
    except Exception:
        return _baseline_stretch(source, target_canvas)
