"""Fit text into boxes: largest whole-number font size that wraps without overflow.

Integer sizes only (the renderer draws at int(font_size)). Widths and wrapping
come from engine/textmeasure.py, i.e. exactly what the renderer will do.
"""

from engine.textmeasure import measure_text


def fit_size(el: dict, width: float, max_h: float, max_size: float, min_size: int = 5):
    """Largest size in [min_size, max_size] whose wrapped text fits width x max_h.

    Returns (size, measure, ok). If nothing fits, returns min_size with ok=False.
    """
    lo, hi = int(min_size), max(int(max_size), int(min_size))

    def fits(s):
        m = measure_text(el, s, width)
        return m["max_line_width"] <= width + 0.5 and m["height"] <= max_h + 0.01, m

    ok, m = fits(hi)
    if ok:
        return hi, m, True
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid)[0]:
            lo = mid
        else:
            hi = mid - 1
    ok, m = fits(lo)
    return lo, m, ok


def fit_stack(items: list, width: float, max_h: float, max_size: float, min_size: int = 5,
              gap_ratio: float = 0.3, extra_h: float = 0.0):
    """Fit a stack of texts sharing one width. items = [(element, ratio_to_first)].

    The first item gets size S, the others max(min_size, round(S * ratio)).
    Finds the largest S such that the whole stack (plus gaps and `extra_h`) fits max_h.
    Returns (S, [(size, measure), ...], total_height, ok).
    """

    def build(S):
        total, parts = extra_h, []
        for el, r in items:
            s = max(min_size, int(round(S * r)))
            m = measure_text(el, s, width)
            if m["max_line_width"] > width + 0.5:
                return None
            parts.append((s, m))
            total += m["height"]
        total += gap_ratio * S * (len(items) - 1 + (1 if extra_h else 0))
        return total, parts

    lo, hi = int(min_size), max(int(max_size), int(min_size))

    def feasible(S):
        b = build(S)
        return b is not None and b[0] <= max_h + 0.01

    if feasible(hi):
        lo = hi
    else:
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if feasible(mid):
                lo = mid
            else:
                hi = mid - 1
    b = build(lo)
    if b is None:  # a word is wider than the box even at the smallest size
        parts = [(min_size, measure_text(el, min_size, width)) for el, _ in items]
        return lo, parts, sum(m["height"] for _, m in parts), False
    return lo, b[1], b[0], b[0] <= max_h + 0.01
