# Chameleon Engine (Adobe University Hackathon 2026)

## How to work with me
- I want an interactive, step-by-step process. Before doing anything, give a brief plain-English explanation of what's going on and what you're about to do, then direct instructions. Don't dump finished code without walking through it.
- Keep explanations simple and short. Ask before big decisions.
- After every engine change: run `python -m engine.main`, look at the PNGs in `output/`, and tell me what changed.
- Commit working milestones to git (remote: github.com/mahajanAarav/chameleonEngine, `upstream` = Adobe's starter repo).

## The challenge in one paragraph
We write one function, `resize(source, target_canvas)` in `engine/resize.py`. Input is a design as a list of elements (text, image, shape) with position, size and style, plus a new canvas size. Output is the same elements with new positions/sizes (and font sizes) so the design looks properly designed in the new shape. Adobe's renderer (cr-renderer) draws the result. Scoring runs offline (`--network none`) in Docker on hidden designs and hidden target sizes across 3 difficulty levels: (1) automatic structural checks on the JSON, (2) an AI judge grading the rendered PNG.

## Hard rules (breaking these fails or disqualifies)
- Same element ids in and out. Nothing added, removed or hidden.
- Nothing off-canvas (keep rotated elements' full rotated footprint inside too, to be safe).
- Images keep their aspect ratio. Never use `fit: fill` on content images.
- Text content and font family are fixed. Only font size and wrapping can change. No rewording in stage one.
- NEVER regenerate, redraw or alter image pixels. Disqualifying. The engine only outputs numbers.
- No semantic labels at test time: never rely on element id names like "headline". Infer roles from geometry and style.
- Engine must never crash (the missing asset `solstice_holiday_badge_2025.png` in the Level 3 sample is intentional).

## Judging criteria (what the AI judge rewards)
No unwanted collisions (and no text on busy images), everything readable (size and contrast, nothing cut off), on brand (colours, fonts, logo intact and in proportion), looks intentional (alignment, even spacing, hierarchy, images in proportion), holds up across many designs. Speed and reliability is a minor rubric row; there is no hard time limit.

## Samples (in input/)
- Level 1: 4 elements, 1080x1080 -> 1080x1350
- Level 2: 11 elements, 1080x1080 -> 1600x400 (groups, overlapping semi-transparent circles)
- Level 3: 17 elements, 1080x1350 -> 728x90 (run-on headline, 3 badges, rotated ribbon, missing asset, fine print)

## How to identify element roles (no labels)
- Background: image covering the whole canvas, lowest z_index, fit cover
- Main image: largest non-background image
- Logo: small wide image near the top, high z
- Headline: text with the largest font_size
- Supporting text: next-largest text, below the headline
- Fine print: smallest font, low opacity, at the bottom edge
- Pill unit (button or badge): rounded rectangle plus text sharing group_id and the same x/width. Button = largest pill, last in reading order. Badges = smaller, uppercase, often a row of siblings with the same y/height
- Not every CTA has a shape (the Level 1 CTA is plain text)
- Decoration: shape with no text, low opacity, low z, may bleed off canvas or be rotated
- Grouped elements (same group_id) move and scale as one unit

## Renderer facts (verified with a probe render)
- Text is drawn from the TOP of its box, not vertically centred. To centre a label in a button, compute the text height and position the box.
- Text that doesn't fit wraps to the box width and SPILLS OUT BELOW the box (not clipped, not shrunk). Box height is ignored. Always compute the real wrapped height.
- Line height is about 1.2 x font_size, so text height ~= lines x font_size x 1.2.
- fit contain = whole image with empty space around it (safe). cover = fills the box but crops (backgrounds only). fill = distorts (never use).
- Rotation is around the element centre; positive = clockwise. Parts past the canvas edge are clipped.
- The starter self-check ignores rotation and flags edge-bleeding decoration. Passing it means little (the Level 3 baseline passes with 1px text).
- style_runs can reference indexes past the end of the string; pass them through untouched.
- corner_radius must scale with its shape.

## What the stretch baseline gets wrong (our checks to beat)
Circles become ovals, pills become long bars, text shrinks to unreadable sizes (9px in L2, 1px in L3), the subhead collides with the button in L2, the rotated ribbon becomes a diagonal line, and everything stays centred in wide banners.

## Chosen approach
1. Safety net: uniform scale (no stretching), centred, background covers the canvas, edge-bleeding decoration pulled inside, rotated footprints kept inside. Wrapped in try/except falling back to the original baseline. Always returns valid output.
2. Measuring stick (build BEFORE the smart engine): synthetic test-design generator, catalogue of real platform target sizes, strict rule checker, code-based quality metrics, an AI judge used ONLY during development (pairwise "is A or B better"), and one command that reports a score. Keep a held-out test split we never tune on.
3. Engine pipeline:
   - Understand: infer roles, bundle groups, work out reading order and an importance ranking.
   - Arrange using the gentlest tool that works, in order: gap carving (shrink empty strips between blocks proportionally, with minimum gaps) -> folding (cut at empty strips that don't split groups, place blocks side by side or in a row for wide banners) -> shrink by importance (low-priority elements shrink first; protect headline, logo, product, CTA).
   - Fit text with the real fonts and a readable minimum size.
   - Generate many candidate layouts, score them, keep the best, fall back to the safety net if none pass the rules.
4. Calibrate the runtime scorer's weights against the AI judge's pairwise picks; tune engine parameters (margins, minimum font, shrink order) to maximise the calibrated score; verify on the held-out set.
- No AI model inside the submitted engine (model rules unresolved, Docker likely slow). Pixel seam carving is ruled out. Genre detection only if the measuring stick shows it helps.

## Open questions for the organizers
Which fields besides x/y/w/h/font_size may change; how to handle elements that can't fit at extreme sizes; whether edge-bleeding decoration and rotated corners count as off-canvas; whether the target size catalogue is published; whether hidden designs all use the Solstice brand kit; model list, hardware limits and code-freeze date.

## Current status
**Built and pushed.** Safety net (engine/safety.py), role detection (engine/understand.py, labels from geometry only), exact text measuring (engine/textmeasure.py, textfit.py), five layout templates with parameter grids and a grow-to-fit search (engine/layout.py: row for aspect >= 2.5, stack for <= 1.6 with story safe zones, split for 1.0-3.0, spread, grow variants), strict rule checker (engine/rules.py), quality score (engine/score.py), candidate selection with gates for collisions and a visible logo (engine/resize.py). Headline is capped at 1.6x its original relative size. Zero rule breaks on all generated and official cases. Docker offline run passed on the early baseline (needs Docker Desktop with Rosetta on Apple Silicon); NOT yet re-run on the final engine.

**Measuring stick (tools/):** sizes.py, gen_designs.py (held-out = seed % 5 == 0), report.py, judge.py (blind A/B for Claude subagents), fit_weights.py, refdist.py / ref_report.py / oracle.py (compare against designer references), make_ref_tasks.py, refcheck.py. Saved data in the repo: data/refs/ (24 designer reference layouts made by Claude subagents who could render and iterate) and data/judgments/ (blind picks). /tmp scratch folders get wiped by macOS, so keep anything valuable in data/.

**Honest results.** Our code score (about 95) is not trustworthy: it rated references and engine equal and agreed with blind judges only 10/24. Blind judges prefer the designer reference over our engine in about 20 of 24 cases (engine wins 4, 5, 3, 4 across four rounds, a plateau). Measured gaps: designers' product is ~44% bigger by area, button ~24% taller; circles must not sit behind text/logo; judges reward a fuller, balanced canvas. Judges are Claude models and designs are synthetic, so this is a proxy for Adobe's grader (coordinate closeness to a hidden "perfect" layout, then human judges on adaptability and model swappability; small and swappable models earn a bonus).

**Decisions made.** No model shipped inside the engine; build a swappable "proposer" slot instead (any model suggests a layout, our checker and scorer validate it). Claude subagents act as dev-only judges and designers.

**Next options.** (1) Finish deliverables: swappable proposer slot, Docker re-run, README. (2) More designer references (100+) to learn conventions and fit template parameters. (3) Tiny mobile banners are still unreadable.

## Commands
- Run engine: `source .venv/bin/activate && python -m engine.main`
- Docker: `docker build --platform linux/amd64 -t my-chameleon-engine .` then `docker run --rm --network none -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output my-chameleon-engine`
