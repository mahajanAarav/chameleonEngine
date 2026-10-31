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

## Rules compliance (brief, RULES.md and the Oct 22 recap)

| Rule | How the engine meets it |
|---|---|
| Same elements in and out, every element visible | Ids checked on every candidate. Text is never left below 6px when any layout (or a safe lift afterwards) can avoid it; shapes never go below 1px. Nothing is hidden, made transparent or dropped. |
| Nothing off-canvas | Strict checker measures wrapped text (letter spacing included) and rotated footprints; a final repair pass pulls anything left over back in. |
| Images keep their proportions | Uniform scaling only; `fit` is never changed, never `fill`. |
| Text content and font family fixed | Copied from the source; only font size, wrapping and (proportionally) letter spacing change. |
| No regenerated or redrawn pixels (disqualifying) | The engine only outputs numbers. It reads image pixels (contrast, cut-outs) but never writes them. |
| No labels | Roles come from geometry and style only; ids are never read. |
| Never crash, offline | Safety net + try/except fallbacks; no network calls; Docker `--network none` verified. |
| Consistency across sizes | Selection gates (collision-free, all text visible, visible logo, spotlight kept, headline kept) apply the same way to every size, so no size is sacrificed for another. |

## Models and weights

No large model ships inside the engine, so **there is nothing to download** and nothing to host: the default engine
is deterministic and runs offline on CPU. Its only learned part is the layout **picker** (`engine/regressor.json`,
about 3 KB): a ridge regression with 78 weights that ranks candidate layouts, trained in seconds on the designer
references in `data/refs/` (`python -m tools.learn_regress --save`). It is small, transparent and swappable: delete
the file and the engine falls back to a hand-set score; retrain it on new references and it updates. The recap asks for solutions that work with different models and favours
small, interchangeable ones over large-model training; the slot below is built for exactly that. A small model plugged
in this way would have its weights hosted publicly (e.g. a Hugging Face repo) and pulled by its own loader.

Dependencies: `Pillow`, `numpy`, and the organisers' `cr-renderer` (see `requirements.txt`). Python 3.11+.

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
- Latest stage (real-ad robustness): the engine now reads image pixels (never changes them) to find cut-out subjects,
  glows and busy or dark areas behind text; picks the spotlight image and keeps it big (hero gate); bundles touching
  images, halos, bars and word-art text into single units; keeps collages in their original composition; tries
  mirrored layouts when text sits on a poor background; and runs a final repair pass so no text leaves the canvas.
  Fuzz test: 1800+ odd designs, 0 crashes, 0 rule errors. Picker retrained on 178 designer references (including
  look-alikes of real ads). Final blind round on 46 held-out tasks: engine won 13 (about 28%), flat within noise.
  Docker offline re-verified on the final engine: 3/3 samples, 0 rule errors.
- Real-ad inputs (Purva's 70 JSON files, data/purva_inputs; images not received, so no pixel checks): 0 crashes, 0 rule
  errors. Found and fixed: overlaps the source design makes on purpose (word-art behind a product) were counted as
  collisions and shrank the hero (McDonald's "mmm" landscape hero share 0.09 -> 1.0). Also a size-readability gate now
  runs before the hero gate so tiny banners keep readable headlines (worst case 55.9 -> 69.9). tools/report.py prints
  consistency stats (worst case, 10th percentile, weakest sizes). Docker offline re-verified: 3/3, 0 rule errors.
- The learned picker moves the engine measurably closer to the designers' coordinates (held-out distance 36.5 to 41.4
  on our 0 to 100 scale; the best candidate we generate would reach about 47), without improving the judged result.
- The judges and designers are Claude models and the test designs are synthetic, so these are proxies for the hidden
  grader, not the grader.
- Very small banners (for example 320x50) with long headlines cannot be made fully readable, and the logo in 728x90
  banners is small.
- Real-ad round (Oct 29-30): importance detection from geometry (corner logos, logo lockups, headline lockups, URL/handle
  fine print, word-art heroes, ordered picture sets), a headline gate so a big hero can't cost the headline its size,
  hero-full-height split layouts, letter spacing measured and scaled with font size, and an "every element visible"
  gate + safe lift for tiny text (audit on 70 real ads + 3 samples: 6 cases with sub-6px text -> 2, both physically
  too small to fit). 0 rule errors, fuzz 900 designs 0 errors.
- Round 4 (Oct 30, 7 more real ads: Dunkin', Tim Hortons, Jersey Mike's, a movie poster): text panels follow their
  text (white copy no longer lands on a white page), no other text is placed on a panel, artwork that wraps a word
  (an arc slogan around a price) moves with it, round buttons stay round, overlapping product shots move as one, and
  the hero vs headline choice is now *balanced* (neither may be sacrificed for the other) instead of hero-first.
  Picker retrained. 105 real-ad designs + 3 samples: 0 rule errors; fuzz 900 designs, 0 errors.
- Unusual sizes (Oct 30): every real ad + the 3 samples resized to 14 non-standard targets (160x600, 120x600,
  300x600, 970x250, 320x50, 728x90, 1037x613, 613x1037, 200x200, 4000x1000, 1000x3000, 2560x1440, 1500x1000,
  1200x1500): 336 designs, 0 rule errors; 15 still have some text under 6px (mostly 320x50 strips, where 10+
  elements share a 50px-tall canvas and nothing may be dropped).
- Round 5 (Oct 30): products that hide part of each other (measured on the real pixels) stay together; products
  that only touch, or that carry their own captions, are re-arranged as a row, column or grid to suit the canvas
  (an ordered set like before / after / right after keeps its order). Full checks: 105 real-ad designs + 3 samples
  and 336 designs at 14 unusual sizes, 0 rule errors; fuzz 900, 0 errors.
- Round 6 (Oct 30): connector words ("from", "by", "presented by") stay attached to the logo they introduce; sets of
  products/steps stack on tall canvases and line up on wide ones (captions kept with their pictures, order kept),
  unless the products hide part of each other.
- Round 7 (Oct 30, 7 info-heavy retail fliers: Target x3, Walmart, ShopRite, Costco x2): a product card with a
  price tag or "Only at" sticker is a product, not a badge; a price is never read as a logo slogan; words printed ON
  artwork (a ribbon) with the biggest type make that artwork the headline lockup; a title lockup nearly as big as
  the headline is ranked as a title; an underline/rule joins the phrase it underlines (the phrase moves as one
  block); type hierarchy is protected (a sub-line may not end up bigger than the headline; selection gate + repair);
  text scaled with its box keeps its line breaks; tiny-text lift never spills a label out of its tag/disc; when no
  layout is collision-free the cleanest one wins. Checks: 143 designs (105 earlier + 35 new + 3 samples) 0 rule
  errors; 336 unusual sizes 0 rule errors; fuzz 300, 0 errors; reference score unchanged.
- Bitten pictures (Oct 30, late): a picture whose outline follows a picture in front of it (a logo cut out from
  behind a person's head: its hidden part is not in its file) travels with that picture, whatever unit either sits
  in; measured on the real pixels (`pixels.bite_fraction` >= 0.2, or the existing hidden_fraction). Two products
  that only touch share little outline (< 0.14 on every test ad) and can still be re-arranged. Inside a product set,
  bitten pieces become one piece.
- Banner strips (Oct 30, late): in a banner (width >= 2.5x height) a product set flows along the strip at a common
  visual height (tall and wide cards end up the same height, scales within 1.6x of each other), in 1 to 3 rows, each
  card only as wide as itself; any set may take up to 68% of the strip. A catalogue page (4+ cards that each pair a
  picture with its own price/caption, scattered, similar in size) is offered as such a set, for banners only, and
  only when it shows at least 5% more product than the best clean layout. Other canvas shapes are unaffected.
- Extreme canvases (1x5000, 0x5000, 5000x0, 5000x2, 1x1, 0x0, 20000x300, 300x20000, 10x10000, -100x500, fractional):
  never crash, every id returned, no NaN, at most 2.5 s. Canvases 1 to 3 px wide/tall cannot hold text legally (the
  rules forbid fonts under 1 px, and one word at 1 px is still wider than the canvas), so those report text overflow
  by necessity; 5000x2, 10x10000 and the large sizes are rule-clean.
- Extreme canvases, final (Oct 30, night): on canvases 15x or more longer than wide (20000x300, 300x20000) blocks
  are pulled together into one centred group (gaps capped at half the short side; text boxes first tightened to their
  words) instead of being spread thousands of pixels apart. Tiny pictures keep full size precision, so a 0.3 px icon
  keeps its exact proportions (5000x2 is now rule-clean for everything except one rotated label that is taller
  than a 2 px canvas). Normal sizes are untouched.
- Round 8 (Oct 30, night; Target same-day, Chipotle x2, Taco Bell x2, Starbucks x2): a headline that sat above the
  pictures stays above them in tall/square stacks when that keeps 80% of the hero/headline balance (`text_first`
  stack variants + an order key); when the winning layout's text sits on a poor background, its mirror image is
  tried too (Starbucks banner headline was green on green). 178 designs 0 rule errors; 336 unusual sizes 0 rule
  errors; fuzz 300 0 errors; reference score 32.6 / 31.8 (unchanged).
- Known limits: in very small formats (300x250, 728x90) the longest fine print or a rotated ribbon label can still end
  up around 4px; the rules forbid dropping it, so it stays, small.
- Open questions for the organisers are listed in `docs/ORGANISER_NOTES.md`.

The organisers' original starter README is kept as `STARTER_README.md`.
