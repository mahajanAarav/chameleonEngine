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
otherwise the amd64 emulator crashes inside the renderer.

## How it works

1. **Understand** (`engine/understand.py`). Groups elements into units (a pill and its label move as one) and
   labels each unit from geometry and style only, never from ids: background, logo, product, headline, supporting
   text, button, badges, ribbon, decoration, watermark, fine print. It also derives reading order and importance.
2. **Measure text exactly** (`engine/textmeasure.py`, `textfit.py`). Uses the renderer's own glyph widths and
   greedy wrapper with the brand fonts, so the wrapped height we compute is the height that gets drawn. Whole-number
   font sizes only (the renderer draws at `int(font_size)`).
3. **Generate candidate layouts** (`engine/layout.py`): a banner **row** for wide targets, a centred **stack** for
   tall and square ones (story safe zones kept clear), a **split** (media left, text right) for moderately wide
   ones, a **spread** that keeps the original composition, plus **grow-to-fit** variants that search for the largest
   product, button and text that still fit. Each template has a parameter grid, so a typical case yields 50 to
   200 candidates. Decorative shapes keep their shape and are placed where they clash least.
4. **Reject, gate, score** (`engine/resize.py`, `rules.py`, `score.py`). Every candidate is checked against the
   hard rules (ids, nothing off-canvas including rotated footprints, image aspect, no `fill`, text and fonts
   unchanged, wrapped text inside the canvas). Rule-breakers are never eligible. The rest are ranked by: no
   collisions, then a clearly visible logo, then a quality score fitted to blind judge picks.
5. **Never fail** (`engine/safety.py`). The uniform-scale safety net is always one of the candidates, and any error
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
| `python -m tools.test_understand` | Role-detection accuracy against the answer key |
| `python -m tools.test_proposer` | Tests for the swappable model slot |
| `python -m tools.ref_report --refs data/refs --pairs DIR` | Blind A/B images of the engine against designer reference layouts |
| `python -m tools.judge make-cands / tally` | Builds and tallies blind A/B pairs for judging |
| `python -m tools.fit_weights data/judgments/r` | Fits scorer weights to judge picks |

Data kept in the repo: `data/refs/` (24 designer reference layouts) and `data/judgments/` (blind picks).

## Honest status

- Zero rule breaks across all generated and official cases.
- Our own code score (about 95) overstates quality: blind Claude judges preferred the designer reference over our
  engine in about 20 of 24 cases. Measured gaps: the product is about 44% smaller than a designer would make it, the
  button about 24% shorter, and decorations sometimes clash. The judges are Claude models and the test designs are
  synthetic, so this is a proxy for the hidden grader, not the grader.
- Very small banners (for example 320x50) with long headlines cannot be made fully readable.
- Open questions for the organisers are listed in `CLAUDE.md`.

The organisers' original starter README is kept as `STARTER_README.md`.
