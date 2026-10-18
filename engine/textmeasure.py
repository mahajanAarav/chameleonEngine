"""Measure text exactly the way the renderer wraps and draws it.

Same skia widths and greedy wrapper the renderer uses, with the brand fonts,
but with cached typefaces so the layout search can measure thousands of times.
Shared by the engine (to fit text) and the checker (to verify it).
"""

from functools import lru_cache
from pathlib import Path

import skia  # type: ignore

from renderer.converter.brand_fonts import load_brand_font_manager
from renderer.converter.wrap import wrap_text

_FONTS_DIR = Path(__file__).resolve().parent.parent / "brand_kit" / "fonts"
DEFAULT_LINE_HEIGHT = 1.2


@lru_cache(maxsize=1)
def _font_manager():
    return load_brand_font_manager(str(_FONTS_DIR))


@lru_cache(maxsize=64)
def _typeface(family: str, weight: str, style: str):
    return skia.Typeface.MakeFromData(_font_manager().lookup(family, weight, style))


@lru_cache(maxsize=1024)
def _font(family: str, weight: str, style: str, size: float):
    return skia.Font(_typeface(family, weight, style), size)


@lru_cache(maxsize=4096)
def _widths(family: str, weight: str, style: str, size: float, text: str) -> tuple:
    if not text:
        return ()
    f = _font(family, weight, style, size)
    return tuple(f.getWidths(f.textToGlyphs(text)))


def _style(el: dict) -> tuple[str, str]:
    bold = (el.get("font_weight") or "regular").lower() == "bold"
    italic = (el.get("font_style") or "normal") == "italic"
    weight = "bold" if bold else "regular"
    style = "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"
    return weight, style


def measure_text(el: dict, font_size: float | None = None, width: float | None = None) -> dict:
    """Wrap `el`'s content at `font_size` into `width` the way the renderer does.

    Returns lines, widest line width (px), pitch (px between baselines) and
    the text block height (lines x pitch).
    """
    size = float(font_size if font_size is not None else el["font_size"])
    box_w = float(width if width is not None else el["width"])
    content = str(el.get("content", ""))
    weight, style = _style(el)
    widths = _widths(el.get("font_family", "Montserrat"), weight, style, size, content)
    lines = wrap_text(content, list(widths), box_w).split("\n")
    pos, line_w = 0, []
    for ln in lines:
        line_w.append(sum(widths[pos:pos + len(ln)]))
        pos += len(ln) + 1  # the newline replaced one space
    pitch = size * float(el.get("line_height") or DEFAULT_LINE_HEIGHT)
    return {
        "lines": lines,
        "n_lines": len(lines),
        "max_line_width": max(line_w) if line_w else 0.0,
        "pitch": pitch,
        "height": len(lines) * pitch,
    }
