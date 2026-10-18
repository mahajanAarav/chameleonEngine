# Chameleon Engine: research findings and build plan

## Context
We implement one function, `resize(source, target_canvas)` in `engine/resize.py`. The starter baseline stretches every element non-uniformly, so circles become ovals, pills become bars, and text falls to 1-9px. Scoring has two parts: structural checks on the JSON, and an AI judge on the rendered PNG. Targets come from a fixed catalogue of real platform sizes; designs are hidden, and the samples use the Solstice brand kit.

Goal: a deterministic, offline, no-model engine that rebuilds the layout for each target shape (the "move the furniture" idea) and never breaks a hard rule.

## Research findings that shape the design
- **Self-check is weak.** `engine/main.py:37-68` only warns, ignores rotation, size and overlap. We need our own strict checker.
- **Use the real text measurer.** `renderer/converter/wrap.py` (`char_widths`, `wrap_text`) uses skia, the same code the renderer uses. The engine imports it, so wraps match exactly. `renderer/` is already copied into the Docker image. fontTools is not installed.
- **Integer font sizes only.** The renderer measures at the float size but draws at `int(font_size)` (`cr_renderer/text_utils.py:191`).
- **Wrapping gaps.** `wrap_text` ignores `letter_spacing`, `capitalize` and `max_lines`, and does not break words longer than the box. Measure these ourselves and keep a width safety margin (about 3%).
- **Text is top-anchored.** The first baseline is about 1.05 x size below the box top for Sans and 1.0 x for Serif; line pitch is `font_size x line_height` (default 1.2). Ink is not centred in its box, so centring labels in pills needs measured ink (cap height ~0.70 x size), not box maths. Verify with a pixel-measure probe.
- **Image rule:** non-cover images must keep the source box aspect within ~5% (`resize.py` docstring). Background = full canvas, `cover`. Logos and products use `contain`.
- **Catalogue sizes are real formats** (RULES.md). We build our own list from standard sizes (below).
- **Web research was low-yield:** only patents on constraint-based layout; they confirm the prioritised-constraint approach but give no usable code. Standard IAB and social sizes found: 728x90, 300x250, 336x280, 300x600, 160x600, 300x50, 1080x1080, 1080x1350, 1080x1920, 1200x627, 1200x1200, 851x315.
- **Extreme case (L3, 728x90):** 17 elements, 90px of height. Nothing may be hidden, so low-priority items (fine print, watermark, extra badges) shrink to small-but-inside; the headline, logo, product and CTA are protected.

## Architecture (all in `engine/`; dev tools outside it in `tools/`)

### 1. Safety net (`engine/safety.py`)
Uniform scale (no stretch), centred; background covers the canvas; edge-bleeding decoration pulled inside as a circle/rect of the same shape; rotated elements' full rotated footprint (width x |cos| + height x |sin|) kept inside; `corner_radius` scaled; sizes rounded; font >= 1. `resize()` wraps the smart engine in try/except and falls back to this, so output is always valid.

### 2. Understand (`engine/understand.py`)
- Merge elements into **units**: grouped elements (same `group_id`) move and scale together; pill units are a rounded rectangle plus its label.
- Infer roles from geometry and style only (never from ids): background, main image, logo (small wide image near top, high z), headline (largest font), supporting text, fine print (smallest font, low opacity, bottom edge), CTA/badges (pill units by size and order), decoration (shape with no text, low opacity/z, may bleed or rotate), and unknown (default: keep relative order, treat as mid importance).
- Reading order from original y then x; importance rank (headline, logo, product, CTA highest; fine print and decoration lowest). Unknown roles degrade gracefully to scaled placement rather than guessing.

### 3. Arrange (`engine/layout.py`), gentlest tool first
Pick by target aspect ratio vs source:
1. **Near-same ratio:** uniform scale about the centre (plus tidy margins).
2. **Taller than source:** vertical stack. Stretch the gaps between blocks proportionally with minimum gaps (gap carving), then grow the main image and text.
3. **Wider than source:** fold into columns: media block (logo + product) on one side, text block (headline, supporting text, CTA/badges) on the other, split at empty strips that do not cut a group.
4. **Ultra-wide (banner, ~8:1):** single row: logo, then headline + supporting text, then CTA. Badges drop to a small trailing row; fine print and watermark become small chips; rotated ribbon rotates about its centre with a footprint check.
5. **Ultra-tall (e.g. 160x600 / 1080x1920 story):** stack with story safe zones (about 14% top and 35% bottom kept free of key text).
If any step would push a protected element below its minimum size, shrink the lowest-importance elements first, then repeat.

### 4. Fit text (`engine/textfit.py`)
Binary search integer font size from the scaled original down to a readable floor (about 11px for body, 9px for fine print in tiny banners; the floor is a tunable parameter). Wrap with the real skia widths, then set the box height to the true wrapped height (lines x size x line_height) and place by measured ink. Preserve the headline > supporting > fine print size ratio. Pass `style_runs` through untouched. Centre pill labels vertically using measured ink.

### 5. Candidates and scoring (`engine/score.py`)
Generate several candidate layouts (templates x parameter variants), reject any that break a hard rule, score the rest with weighted terms:
- collisions (text over text, text over product), text on busy image;
- readability (font size vs floor);
- hierarchy kept;
- alignment and even spacing;
- image size in proportion;
- balanced whitespace and margins.
Keep the best. If none pass, use the safety net. No AI model ships in the engine.

## Measuring stick (built before the smart engine) in `tools/`
- `tools/gen_designs.py`: synthetic design generator (varying text length, group counts, badge counts, with/without product, logos, rotated ribbon, decoration, long run-on headlines, missing asset). Fixed seeds; a **held-out split we never tune on**.
- `tools/sizes.py`: catalogue of about 25 target sizes (list above plus IG Story, YouTube 1280x720, Twitter 1600x900, Pinterest 1000x1500, LinkedIn banner, 970x250, 320x50, A4-ish).
- `tools/check.py`: strict rule checker: ids equal, no extras, rotated footprint inside canvas, image aspect within 5%, no `fill` on content images, text content/family unchanged, font >= floor, text fully inside canvas after real wrapping, group integrity.
- `tools/metrics.py`: code-based quality metrics (overlap area, min font, spacing evenness, alignment).
- `tools/judge.py` / agent prompt: dev-only pairwise judge. Per your choice, Claude subagents view pairs of PNGs (engine A vs engine B) and pick the better one; used to calibrate scorer weights, never shipped.
- `tools/report.py`: one command that prints a single score plus failures over train and held-out splits, with a contact-sheet PNG of results.

## Build order
1. Docker build + run once on the baseline (not yet done; confirms the offline path works). Commit.
2. Safety net, validated by the rule checker on the 3 samples. Commit.
3. Measuring stick (all `tools/` items above) and a baseline score. Commit.
4. Smart engine: understand, then text fit, then the templates in order of difficulty (taller, wider, ultra-wide, ultra-tall), checking PNGs after each change (per CLAUDE.md). Commit each milestone.
5. Calibrate scorer weights against the subagent judge's pairwise picks; tune margins, minimum fonts and shrink order; confirm on the held-out split.
6. Docker run with `--network none`, README for approach and how to run, final commit.

## Critical files
- Modify: `engine/resize.py` (thin wrapper: smart engine, fallback to safety net).
- New: `engine/{safety,understand,layout,textfit,score}.py`; `tools/*`; update `requirements.txt` only if a new dependency is truly needed (avoid; use skia/PIL/numpy already present).
- Reuse: `renderer/converter/wrap.py` (`char_widths`, `wrap_text`), `renderer/converter/brand_fonts.py` (font manager), `engine/main.py` self-check (as a baseline signal only).
- Do not edit: `engine/main.py`, `renderer/`, `brand_kit/` assets.

## Verification
- `source .venv/bin/activate && python -m engine.main`, then look at every PNG in `output/` after each engine change.
- `python tools/report.py` for rule failures (must be zero on both splits) and the score trend.
- Held-out split score must not regress against the training split by more than a small margin.
- `docker build --platform linux/amd64 -t my-chameleon-engine .` then the `--network none` run from CLAUDE.md; outputs must match local ones.
- Crash test: feed malformed or odd inputs (missing fields, zero-size elements, huge font, 1px canvas ratio) and confirm the fallback returns valid output.

## Risks and open items
- Unknowns from CLAUDE.md remain (which fields may change besides x/y/w/h/font_size; whether bleeding decoration or rotated corners count as off-canvas; hidden designs may not all use the Solstice kit). The engine stays conservative: everything inside the canvas, rotation footprint included.
- At 728x90, the readable-text floor and the "nothing hidden" rule conflict; the scorer decides the trade-off and we ask organisers if possible.
- Ink-centring and wrap accuracy depend on a pixel-measure probe; do that early.
