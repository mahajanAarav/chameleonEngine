# Engine changes (team log, Oct 29-30, 2026)

Problem (Purva's critique): the engine kept picking the wrong things to make big. Corner logos got blown up
(Starbucks), web addresses and names became headline-sized (e.l.f.), heroes shrank on big canvases (IKEA story,
Heinz square), grouped titles were treated as clutter, the before/after/right-after row got shuffled, and the
Sephora wordmark ran off the canvas.

Tested on all 70 real-ad designs in `data/purva_inputs/designs` plus the 3 Solstice samples: 0 crashes, 0 rule
errors. `test_understand` (100%), `test_anchor`, `test_pixels` and `test_proposer` all pass. Designer-closeness on
`data/refs` (`tools.ref_report`): train 32.8 -> 31.9, held-out 32.3 -> 32.0 (small cost, see #6).

**Caveat:** these numbers come from a sandbox where skia couldn't install, so text was measured with a Pillow
stand-in. Please re-run `python -m engine.main` and the tests on your machine with real skia before committing.

## What changed (5 files)

**engine/understand.py: roles**
1. **Corner logo.** If there's no wide logo near the top, a small picture (≤4% of the canvas, not the biggest
   image, near an edge) becomes the logo. Skipped for collages (4+ pictures). Fixes Starbucks, Heinz, IKEA and
   Pizza Hut, which were "image" or "watermark" before.
2. **Fine print** now also catches web addresses and handles (`elfcosmetics.uk`, `IKEA.pt`, `@brand`) when the
   text is small.
3. **Groups get real roles** (`_classify_groups`). A picture + caption becomes product/image. A small picture +
   short small text near an edge becomes a logo lockup. The group holding the biggest text becomes the headline
   lockup: it scales as one block (role "image", importance 1.0), and single texts that called themselves
   "headline" step down to supporting. A rotated group only counts as a ribbon if it contains a shape.
4. **Sibling pills** (same fill colour, similar height, no "shop/buy..." verb) are all badges, not one button plus
   badges. This fixes the e.l.f. tags being sized differently.
5. **Word-art hero.** One or two huge words (font ≥20% of the short side, box ≥20% of the canvas, like "mmm")
   scale like a picture.
6. **Picture sets.** 3+ similar pictures on one line (before / after / right after) are merged into one block that
   keeps its order and spacing.
7. `Design.ref_font` = the biggest non-fine-print font, so texts are sized against the headline even when it sits
   inside a lockup.

**engine/layout.py**
- Logos are placed with `_media` (so a logo + slogan lockup works) and capped at 2× their original share of the
  canvas area (`_logo_hmax`).
- Media are placed in reading order.
- With no single headline, texts are sized against `ref_font` (`_ratios_without_head`) instead of all at ratio 1.
- `_media` scales a single text element (word-art) with `_xform`.

**engine/resize.py**
- **`HERO_FRAC` 0.5 -> 0.8.** This is the judgment call. It keeps heroes big (real-ad mean hero share kept
  0.80 -> 0.88, and the IKEA story pillow 0.49 -> 0.95). The cost is about 0.3–0.9 points of Solstice
  designer-closeness, and on some designs the text gets smaller (IKEA story, Heinz landscape). One line to revert.
- `scale_letter_spacing`: letter spacing keeps its source ratio to font size, applied to every candidate and
  around `finalize` (`_finalized`).

**engine/textmeasure.py**
- `measure_text` counts letter spacing in line widths. Wrapping still ignores it, like the renderer does.
  `letter_spacing_at()` scales spacing with font size.

**engine/finalize.py**
- `_fit_spaced`: when wide letter spacing pushes text off the canvas, the steps are: move the ink inside, then
  narrow the box, then shrink the type, then tighten the spacing (last resort, only for absurd inputs).

## Round 2 (same day, after Purva reviewed round 1)

Purva: Heinz text should stay big on the side (that's what people read). The bottle and the logo at the bottom were
better. IKEA popsicle much better. Fries box blended into the background (that was a test-data bug, see below).

- **resize.py: headline gate (`HEAD_FRAC = 0.85`).** After the hero gate, the headline must keep ≥85% of the
  biggest headline size (`head_raw`) any hero-safe layout can give it. So a big hero can't come at the cost of a
  tiny headline.
- **layout.py: new split variants (`logo_text=True`, appended to `SPLIT_WIDE_PARAMS`).** The picture takes the full
  media column at full height, and the logo moves into the text column. If the logo came after the headline in the
  source reading order, it goes last (`logo_last`), so HEINZ stays under the headline. Heinz landscape: headline
  50 -> 124px with the bottle at full height. Pizza Hut landscape hero 0.49 -> 0.77.
- **Test data, not the engine:** in Purva's fries ad, the red fry boxes on the red background weren't cut out
  (colour-based cutting can't separate red from red), so they melted into the background. The outlines are traced
  by hand in the converter now. Replace the 5 `mcd_fries__*.json` designs and 3 `mcd_fries_*.png` assets with the
  ones in this zip.

After round 2: 70 real ads + 3 samples, 0 rule errors; all 4 tests pass; fuzz seed 0, 0 errors. Solstice
designer-closeness vs the original engine: train 32.8 -> 33.0, held-out 32.3 -> 31.0 (held-out dipped; worth
watching after the picker retrain).

## Round 3 (Oct 30): rules audit against the organisers' recap

The recap says **every input element must remain visible**, so we can't drop elements. Changes:
- `resize.py`: a `_visible_text` gate (no text under 6px if any candidate avoids it), placed right after the
  collision gate; `_raise_tiny_text` lifts any leftover tiny text to 6px when it stays on the canvas and doesn't land
  on anything new.
- `finalize.py`: shapes never go below 1px (the McDonald's divider was vanishing). Images are untouched (proportion).
- `README.md`: rules-compliance table and a models/weights/dependencies section (the recap asks for both).
- Audit across 70 real ads + 3 samples: tiny/hidden-element cases 6 -> 2; 0 rule errors; tests pass; fuzz 900, 0
  errors; Solstice closeness train 32.8, held-out 30.9.

## Round 4 (Oct 30): 7 more real ads, see `round4_results.png`

New test data: `data_batch3/` (35 designs + images). Copy the designs into `data/batch3/` and the images into
`brand_kit/assets/`.

- **Panels follow their text** (`resize._backdrops`, `fit_backdrops`). An opaque, non-grouped rectangle that has
  text ≥80% inside it (and drawn above it) is moved/resized behind that text after layout. Full-width bands stay full
  width. `_panel_intruders` keeps any other text off a panel (it's counted in the visibility gate). In
  `understand._attach`, panels are no longer bundled into product units. Fixes Jersey Mike's 15% (white text was
  landing on the white page).
- **Word on artwork stays together** (`understand._framed_text`). A small image with a word ≥70% inside it (drawn
  on top) becomes one unit. If that word was the headline, the next biggest text becomes the headline. Fixes the Tims
  arc slogan + 25¢.
- **Round pills stay round** (`layout._pill`), and uppercase pills with a CTA verb ("ORDER NOW") count as buttons.
- **Overlapping pictures bundle** (`_attach`, "stacked"), so three overlapping donuts or cups move as one.
- **Selection: balanced hero vs headline** (`resize._smart`). This replaces the HERO_FRAC and HEAD_FRAC gates.
  First a hero floor: 0.5 of the best hero share (0.6 when the hero dominates), capped at the hero's original share.
  Then among the remaining layouts, keep those within 0.9 of the best `min(hero kept, headline kept)`. Pumpkin square
  headline: 0.43 -> 1.24 of the designer-typical size. Heinz keeps its big side headline.
- **Picker retrained** (`engine/regressor.json`, `learn_regress --save`): held-out pick 35.6 vs 27.5.

Checks: 105 real-ad designs + 3 samples, 0 rule errors; audit 2 sub-6px cases (unchanged); fuzz 900, 0 errors; all
4 tests pass. Solstice `ref_report`: train 32.0 / held-out 31.7 (the original engine was 32.8 / 32.3). So we're
slightly further from the synthetic references, and much better on real ads.

## Round 4.1 (Oct 30): Purva's donut-row feedback + unusual sizes

- `understand._attach`: overlapping pictures only bundle when they overlap ≥25% (drawn as one, like the cups).
  Pictures that just touch, like the three donuts, can be re-flowed, so the banner puts them in a row again.
- `resize.candidates`: `_raise_tiny_text` runs on every candidate. Before, one 5px footer word could disqualify an
  otherwise good layout, so 970x250 billboards fell back to a shrunken copy of the original.
- New stress set `custom_sizes_test/`: 24 ads × 14 unusual sizes = 336 designs. 0 rule errors; tiny-text cases
  24 -> 15. Still weak: Jersey Mike's 15% billboard, and collages (≥4 pictures) in ultra-wide strips.
- Final checks: tests pass, fuzz 600, 0 errors; 105 real ads 0 rule errors; ref_report train 32.3 / held-out 31.7.

## Round 4.2 (Oct 30)

- `resize.candidates`: only loose, uncaptioned pictures count toward the collage rule (≥4 means spread only). A
  picture + caption group is a product a designer would re-flow, so the row and stack templates are allowed. The
  Season's Eatings leaderboard is now a product row. The e.l.f. collage is unchanged.
- Note: the "put products in a row" behaviour comes from rules (templates + bundling thresholds). The picker didn't
  learn it, because its references are Solstice-only. To teach it, add designer references for real multi-product
  ads to `data/refs/` and retrain.
- Checks: tests pass; fuzz 0 errors; 105 real ads, 0 rule errors; 336 custom-size designs, 0 rule errors (14 with
  some sub-6px text); ref_report train 32.3 / held-out 31.7.

## Round 5 (Oct 30): products that can be taken apart vs ones that can't

- `pixels.hidden_fraction` + `understand._occluded`: two overlapping pictures stay glued only if one hides at least
  5% of the other's visible pixels, because that hidden part isn't in its file. Pumpkin: the muffin covers part of
  the cups, so it stays glued. Donuts: they only touch (0%), so they can be re-flowed. Falls back to box overlap if
  an asset is missing. **pixels.py changed, so copy it too.**
- Ordered sets (3+ similar pictures or picture + caption groups lined up in a row or a column) keep their pieces in
  order (`Unit.parts`). `layout._arrange_set` lays them out as a row, column or grid, whichever makes the pieces
  biggest; it has to beat the original arrangement by 10%. Fries become a grid/column in half-page, skyscraper and
  1:3. In a 9:16 story a row still wins, because each step (label + picture) is tall.
- `ROW_TIGHT_PARAMS` gets narrower text columns (tfrac 0.22, 0.32). The Season's Eatings banner is now a product row.
- `fit_backdrops`: a full-width band only stays full width if it covers nothing new, and padding is trimmed away
  from neighbours. Kicker text stays before the headline. Jersey Mike's billboard / leaderboard / banner are now
  logo | products | offer panel.
- `_raise_tiny_text` handles rotated text.
- Checks: 105 real ads + 3 samples, 0 rule errors, audit clean; 336 unusual-size designs, 0 rule errors (8 with
  sub-6px text); fuzz 900, 0 errors; ref_report 32.7 / 31.7. A retrained picker scored worse (31.2 held-out),
  so the round-4 picker is kept.

## Round 6 (Oct 30): "from" stays with the logo, sets follow the canvas, whole cut-outs

- `understand._attach_connectors`: a connector word ("from", "by", "presented by", "only at", ...) that touches or
  sits right beside a picture/logo unit joins it, so it can't float on its own.
- `layout.TARGET` + `_arrange_set`: sets stack on tall canvases (fewest columns) and line up on wide ones (most
  columns), as long as pieces keep ≥75% of the biggest possible size. `_tight_piece` pulls each caption close to
  its picture. A short last row is centred. `resize._smart` has a `follows()` key (after the hero floor, spotlight
  ≥45% of its best) so these layouts actually get picked. Fries: story, half-page and skyscraper now stack.
- Test data: the converter's cut-outs were clipped (it, not the engine, cut off the Tims sub/donut/sleeve, the
  e.l.f. CC cream, lip wand and logo, and the Heinz logo). Converter fixed, all ads rebuilt: `test_ads/` (105
  designs + images) replaces `data_batch3/` and the earlier packs.
- Checks: 105 real ads + 3 samples, 0 rule errors, audit clean; 336 unusual sizes, 0 rule errors (9 with sub-6px
  text); fuzz 900, 0 errors; ref_report 32.7 / 31.7.

## Round 7 (Oct 30 evening): info-heavy retail fliers (Target x3, Walmart, ShopRite, Costco x2)

Files changed: `engine/understand.py`, `engine/resize.py` only (layout, finalize, textmeasure, pixels untouched).

- `understand._picture_led`: a group whose biggest member is a picture (product + price tag / "Only at" sticker)
  is a product card, not a pill/badge. Before, every Target toy and every Costco product was a 0.5-importance badge
  and the Costco story collapsed into a tiny column.
- `understand._PRICE`: text with a price/percent is never a logo slogan (the Vital Proteins tub was a "logo").
- `understand._on_picture`: when a group's biggest text (the biggest in the design) is printed ON its artwork (the
  Costco ribbon), the group is the headline lockup, not a product. A title lockup with ≥70% of the headline size
  (Target "circle week" icon + title, beaten by a giant "30") is kept as a block with logo-level importance.
- `understand._attach_underlines`: a thin wide stroke right under a text (hand-drawn underline, rule) joins it, plus
  the lines stacked above it, as one type lockup. ShopRite's swoosh no longer drifts under the logo.
- `resize._inversions` (selection gate after the hero floor) + `_fix_inversions` (repair): a text clearly smaller
  than the headline in the source (< `INVERSION_GAP` 0.75) may not end up bigger than it (Costco banner had
  "& EVERYDAY VALUES" shouting over the ribbon headline).
- `resize._keep_line_breaks`: text scaled together with its box keeps its line count (a 0.5% font rounding pushed
  "JUST FOR YOU:" onto two lines inside the phone mock-up). Also runs in `_finalized`.
- `resize._raise_tiny_text`: three tiers. Strict, then "may outgrow its own pill but never land on another text",
  then "may graze a sibling text but stays inside its tag". Stops the 300x250 Target badge pile-up while button
  labels and "OR ONLINE" stay visible.
- `resize._smart`: the collision gate is graded when NO layout is collision-free (cleanest wins; Target toys
  300x250 had picked an anchor layout with everything piled up).
- `pixels.bite_fraction` + `understand._attach_bitten` (Deep's catch on the Target toys page): the bullseye sits
  behind the kid's head, so its file has a kid-shaped bite and can't be shown apart from the kid. Any picture whose
  outline follows a picture in front of it (≥ `BITE_MIN` 0.2 of its outline) or is covered by it (hidden_fraction)
  now travels with it, across units (a product card with tags included). Inside a set, the two pieces merge into one
  piece (Costco: vacuum + P&G block; the Vital Proteins tub also joins the vacuum). Touching products score < 0.14.
- Banners (Deep: "why are the assets so small and so much open space?"): `layout._flow_rows` lays a product set
  along a banner at a common visual height (1-3 rows, cards only as wide as themselves, scales within 1.6x); any set
  may take 68% of the strip (McDonald's fries banners: steps about 1.5x bigger, logo readable). `understand.catalogue_variant`: a catalogue page (4+ picture+caption cards,
  scattered) is offered as a set for banners only (`catalogue_row#` candidates), kept only if it shows >= 5% more
  product than the best clean layout. Target toys banner: cards in two tidy rows instead of scattered; Costco banner:
  bigger products; Tims banners essentially unchanged. A 400 px strip with 7 products caps them near
  165 px tall (2 rows); that's the physical limit, not a bug.
- Extreme canvases: `resize._close_gaps` (only when one side is >= 15x the other) pulls blocks into one centred
  group on 20000x300 / 300x20000 instead of scattering them across the strip; images under 50 px keep unrounded
  sizes in `resize._round`, `finalize.finalize` and `safety.safety_resize` (a 0.3 x 0.07 px icon was failing the
  aspect rule at 5000x2). Run on 15 designs x 14 extreme sizes: 0 crashes, every id, no NaN, ~4 s worst alone;
  5000x2, 5000x5000, 20000x300, 300x20000, 10x10000, fractional all rule-clean except 1 rotated label at 5000x2.
- Test data (`test_ads/`): 7 new ads x 5 sizes added (140 designs). Copy `test_ads/assets/*` into
  `brand_kit/assets/`. Converter improvements (outside the repo): text auto-fit so sources render like the
  screenshot; background-difference matting for flat-colour pages; per-row wall fill for photos.
- Extreme canvases: 1x5000, 0x5000, 5000x0, 5000x2, 2x5000, 1x1, 0x0, 3x3, 5000x5000, 20000x300, 300x20000,
  10x10000, -100x500, 500.5x300.7 on 6 designs: 0 crashes, all ids, no NaN, ≤2.5 s. Canvases 1-3 px across can't
  hold text legally (font ≥1 px is a rule, one word at 1 px is wider than the canvas): they report overflow by
  necessity. 5000x2, 10x10000 and all large sizes are rule-clean.
- Checks: 143 designs (105 earlier + 35 new + 3 samples) 0 rule errors, 2 with sub-6px fine print (Target badge
  discs and toy captions at 300x250); 336 unusual sizes 0 rule errors, 9 tiny-text (same as round 6);
  ref_report 32.8 / 31.7 (unchanged); unit tests pass; fuzz 600 (seeds 0 and 300), 0 crashes; 2 rule
  errors at 50x50 from extreme letter spacing, identical on the previous engine (known leftover below).

## Round 8 (Oct 30, night): 7 more ads (Target same-day, Chipotle x2, Taco Bell x2, Starbucks x2)

Files changed: `engine/resize.py`, `engine/layout.py`.

- Title stays on top: `layout.head_on_top` (headline above every picture in the source) adds `text_first` variants to
  the stack and grow-stack templates; `_column` puts the text before the pictures for them. Selection prefers keeping
  the order when hero/headline balance keeps >= 80% of the best (`ORDER_BAL`). Chipotle "Never Forget" story / square
  / 300x250 and Fiery square now read title -> burritos -> punchline as designed.
- Mirror of the winner: when the chosen layout's text sits on a poor background, its left-right mirror is tried as
  well (before, only the top-10 by score got a mirror). Starbucks banner: "SO MUCH YES" was green on the green band,
  now on the pale side.
- Checks: 178 designs (143 + 35 new) 0 rule errors; 336 unusual sizes 0 rule errors (same 9 tiny-text); fuzz 300,
  0 errors; tests pass; ref_report 32.6 / 31.8.
- Known: Fiery story still puts the headline under the product (its product-name lockup with rules is read as a
  button). Taco Bell and Matcha backgrounds show soft blobs where the converter lifted the hero off a busy photo:
  test-data artifact, not the engine.

## Round 9 (Oct 30-31, night): heroes grow into free space

File changed: `engine/resize.py` only.

- `_grow_hero`, the last step before closing gaps: the spotlight picture grows into empty space around it, up to
  1.6x (linear) and at most 45% of the canvas. Uniform scale, stays on the canvas, keeps a clear gap to everything it
  didn't already touch and never covers more of what it did. Pictures only (not captions), never rotated ones.
  Changes 10 of the 35 newest designs (Never Forget landscape and banner, Fiery banner, matcha cups).
- Not fixed: the Taco Bell cricket taco in landscape can't grow (text right above and below it). It needs a
  side-by-side layout, which currently can't fit that ad's 19 text pieces.
- Checks: 178 designs 0 rule errors; 336 unusual sizes 0 rule errors (same 9 tiny-text); fuzz 600 (seeds 0 and
  300), 0 new errors; tests pass; ref_report 32.8 / 32.4 (held-out up from 31.8).

## Rounds 10-12 (Oct 31)

- Rounds 10-12 (Oct 31): the spotlight picture slides into free space to grow (up to 1.6x, 2x when it is under 8% of the canvas); a smaller picture that sat in a corner of the original may move to that corner to make room; a text line left partly under another (or overlapped because it wrapped onto more lines) is pushed clear with only what is in its way. 193 designs 0 rule errors; 336 unusual sizes 0 rule errors; fuzz 0 errors.

## Known leftovers
- **Fuzz:** 3 of 1,200 random designs (seeds 0–3) still fail with text off the canvas. All are extreme spacing on
  tiny type in 50×50 canvases. The old engine passed these only because it didn't measure spacing, so the real
  render overflowed anyway.
- Hero vs text: mostly handled by the round 2 headline gate. Check IKEA story / square text sizes on your machine.
- Picker retrained in round 4 (rounds 5-7 left the reference score unchanged, so no retrain needed).
- Weakest new outputs: Costco member banner/landscape (sparse, small), Target toys banner (7 products in 1600x400).
- The fries steps stay in a row in Story (small). Stacking them vertically might be better there.
