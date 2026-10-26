# Notes for the organisers

## Questions that would change what we build

1. **Which fields besides x, y, width, height and font_size may change?** We also change `corner_radius` (scaled with
   the shape) and, for image backgrounds, set `fit: cover`. We never change text, font family, colours, `rotation`,
   `opacity`, `z_index`, `group_id` or `style_runs`. Is `text_align` allowed to change? We keep it as is.
2. **Do bleeding decorations and rotated corners count as off-canvas?** We keep every element, including the full
   rotated footprint, fully inside the canvas, and pull edge-bleeding decoration inside (same shape, smaller).
3. **How should elements that cannot fit at extreme sizes behave?** At 320x50 with a 140-character headline, text cannot
   be readable. We keep everything on-canvas and as large as fits, and never hide or drop elements.
4. **Is the target-size catalogue published?** We assumed standard platform sizes (25 in `tools/sizes.py`).
5. **Do hidden designs all use the Solstice brand kit** (fonts, three assets)? Our role detection uses geometry and
   style only, so other kits should work, but our test designs are all Solstice.
6. **Model rules:** list of allowed models, hardware limits (the rules mention an M5 Pro, exact cores and RAM are TBD),
   and the code-freeze date. We ship no model; any model can plug in through `engine/proposer.py`.
7. **How are the "perfect" reference layouts defined?** If scoring is coordinate closeness to a reference, knowing whether
   it compares boxes (IoU), centres, or font sizes would let us target it directly.

## What we are telling you about our submission

- Deterministic, offline, no network, no model; runs in Docker with `--network none`.
- Never crashes: the safety net is always a candidate and any error falls back to it.
- Swappable model slot with safeguards (geometry only, same rule checks as our own layouts).
- Honest numbers: see `README.md`, "Honest status".
