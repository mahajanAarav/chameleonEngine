# Chameleon Engine

A deterministic, offline layout engine for `resize(source, target_canvas)`. It rebuilds each design for the new
shape instead of stretching it: the same elements, new positions, sizes and font sizes. No image is ever redrawn.
No model ships inside the engine, but any model can be plugged in (see **Swappable models**).

## Run it

```bash
source .venv/bin/activate
python -m engine.main            # every task in input/ -> output/<task>_output.json + .png
```

Docker, the same way scoring runs it (offline):

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .
docker run --rm --network none -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output my-chameleon-engine
```

On Apple Silicon, turn on **Docker Desktop > Settings > General > Use Rosetta for x86_64/amd64 emulation**,
otherwise the amd64 emulator crashes inside the renderer. Docker has a slightly newer skia than a local install, so
text widths can differ by fractions of a pixel and near-tied layouts can flip; both results are valid.

## How it works

1. **Understand** (`engine/understand.py`). Groups elements into units (a pill and its label move as one; a bar under a product, an aura behind it, or a cluster of touching images are bundled by geometry too) and
   labels each unit from geometry and style only, never from ids: background, logo, product, headline, supporting
   text, button, badges, ribbon, decoration, watermark, fine print. It also derives reading order and importance.
2. **Measure text exactly** (`engine/textmeasure.py`, `textfit.py`). Uses the renderer's own glyph widths and
   greedy wrapper with the brand fonts, so the wrapped height we compute is the height that gets drawn. Whole-number
   font sizes only (the renderer draws at `int(font_size)`).
3. **Generate candidate layouts** (`engine/layout.py`): a banner **row** (including text-first and full-height-product
   variants), a centred **stack** for tall and square targets (story safe zones kept clear), a **split** (media left,
   text right) for moderately wide ones, a **spread** that keeps the original composition, and **grow-to-fit**
   variants that search for the largest product, button and text that still fit. Each template has a parameter grid,
   so a typical case yields 100 to 300 candidates. Decorative shapes keep their shape and are placed where they clash
   least. Headline size is capped so sparse designs don't balloon.
4. **Reject, gate, pick** (the spotlight image must keep a good share of the canvas, and fine print can never be inflated into a headline) (`engine/resize.py`, `rules.py`, `score.py`, `picker.py`). Every candidate is checked against
   the hard rules (ids, nothing off-canvas including rotated footprints, image aspect, no `fill`, text and fonts
   unchanged, wrapped text inside the canvas). Rule-breakers are never eligible. Survivors must be collision-free and
   keep a clearly visible logo whenever any candidate can. Among those, a **learned picker** chooses the layout
   predicted to be closest to what a designer would make (a ridge regression, `engine/regressor.json`, trained on
   124 designer reference layouts in `data/refs/`). If numpy or the file is missing, a hand-set quality score is used.
5. **Never fail** (`engine/safety.py`, `engine/finalize.py`). A final repair pass fixes any text or shape that still breaks a rule (a long word wider than its box, text taller than the canvas, rotated text, zero-size shapes). The uniform-scale safety net is always one of the candidates, and any error
   anywhere falls back to it (and, as a last resort, to the starter's stretch), so output is always valid.

## Swappable models

`engine/proposer.py` is a socket for any model, small or large, local or hosted. A *proposer* is any function
`proposer(source, target_canvas) -> layout | list[layout] | None`. Plug one in with no code change:

```bash
CHAMELEON_PROPOSER="mypkg.mymodule:propose"    # returns layouts directly
CHAMELEON_MODEL="mypkg.mymodule:generate"      # any text model: generate(prompt: str) -> str
```

or in Python: `engine.proposer.register(fn)`. The adapter `llm_proposer(generate)` builds the prompt, parses the
reply (JSON inside prose or code fences is fine) and returns a proposal. Safeguards: only geometry
(x, y, width, height, font_size, corner_radius) is taken from a proposal and every other field is copied from the
source, so a model cannot reword text, change fonts or drop elements; each proposal (and a repaired copy pulled back
inside the canvas) must pass the same rule checker and gates as our own layouts to win; crashes, timeouts and
garbage are ignored. Tested in `tools/test_proposer.py` with hostile and mock models. Nothing needs a network.

## Measuring quality (`tools/`)

| Command | What it does |
|---|---|
| `python -m tools.report` | Scores the engine on the official samples plus generated designs (train and held-out) across 25 real platform sizes; counts rule breaks |
| `python -m tools.test_proposer` | Tests for the swappable model slot |
| `python -m tools.real_ads --sheet out.png` | Look-alikes of real brand ads (McDonald's, Heinz, IKEA, Pizza Hut, Starbucks, Ford): hero share kept, text growth, rule errors |
| `python -m tools.test_pixels` | Checks the engine reads the real picture pixels behind text (contrast, busyness) and picks readable positions |
| `python -m tools.fuzz -n 300` | Throws odd designs (no logo, empty or huge text, rotated and zero-size elements, tiny canvases) at the engine: 0 crashes, about 1% unavoidable rule errors |
| `python -m tools.test_anchor` | Checks that things that belong together (bar under products, aura behind, image clusters) stay together |
| `python -m tools.test_understand` | Role-detection accuracy against the answer key |
| `python -m tools.ref_report --refs data/refs --split heldout --pairs DIR` | Blind A/B images of the engine against designer reference layouts |
| `python -m tools.learn_regress --save` | Retrains the picker from `data/refs/` (do this after changing any layout) |
| `python -m tools.judge make-cands / tally` | Builds and tallies blind A/B pairs for judging |

Data kept in the repo: `data/refs/` (124 designer reference layouts, 96 train and 28 held-out, made by independent
Claude subagents that could render and iterate) and `data/judgments/` (blind picks).

## Honest status

- Zero rule breaks across all generated and official cases, in Docker offline too.
- Our own code score (about 90 to 95) overstates quality. Against the designer references, blind Claude judges prefer
  the designer in about 70% to 80% of held-out cases (the engine wins 6 to 9 of 28 across versions; the noise is about
  plus or minus 2.5). The designers' main advantages are logo clarity and placement, a larger product and fuller canvas.
- The learned picker moves the engine measurably closer to the designers' coordinates (held-out distance 36.5 to 41.4
  on our 0 to 100 scale; the best candidate we generate would reach about 47), without improving the judged result.
- The judges and designers are Claude models and the test designs are synthetic, so these are proxies for the hidden
  grader, not the grader.
- Very small banners (for example 320x50) with long headlines cannot be made fully readable, and the logo in 728x90
  banners is small.
- Open questions for the organisers are listed in `docs/ORGANISER_NOTES.md`.

The organisers' original starter README is kept as `STARTER_README.md`.
