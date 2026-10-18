# Verification instructions (second pass)

You are checking values that another reading pass extracted from one
packet of a document. Work independently: do not look at the rest of the first pass's
result, only at the values listed for you, and re-read the cited pages
yourself.

## Input

1. The verify plan, printed by

       python -m extract.ingest .cache/results/<id>.<packet>.json --plan-verify > .cache/results/<id>.<packet>.plan.json

   It lists every value read from a table, every subsurface value, every
   water and rock test value, plus a random 10% of the others:
   `path`, `value`, `page`, `quote`.
2. The packet file the values were read from (`.cache/packets/<id>/packet-NN.md`).

## What to do

For each listed value, open the cited page in the packet and decide:

- `agree` -- the page says this, the value is faithful to the source (same
  words and units, nothing added), and it belongs to the right thing (the
  right unit, the right boring and interval, the right fault).
- `disagree` -- the page says something different, or the value is attached
  to the wrong thing (for example, a depth from the next row of a log). Give
  the value the page actually supports in `value`, and explain in `note`.
- `unclear` -- the page is garbled or ambiguous and you cannot tell.

Subsurface values (`surfaces`, `contours`, `sections`, and an observation's
`datum` and `depth_reference`) are always in the plan. For these, also check:
the sign of an elevation and whether it is an elevation or a depth below land
surface; that the `datum` is the one printed for that value (not one from
another table or figure); that `boundary` (top or base) and `method` match
the page; that a contour label or a section's unit belongs to the line or
interval it is attached to. A reading that depends on the layout of a map
face and is not flagged `inferred` is `disagree`, with a note.

Water and rock tests (`water_tests`, `rock_tests`) are always in the plan.
For these, also check: that the value belongs to the right well or
specimen and the right parameter or test (the right row and column of the
table); that the `units` are the ones printed for that column, and that
no units were filled in where none are printed; that a `qualifier` ("<",
">", "ND", "E") is printed for that value; that the sample date, interval
and `depth_reference` are those of that sample; and that a digit read from
a "|" (or another OCR misread) is flagged `inferred`. A value with a digit
the page does not clearly show is `unclear`.

Judge the value against the page, not against your own knowledge of the
geology. A value flagged `inferred` is `agree` if the inference is sound and
clearly supported by the page.

## Output

Write `.cache/results/<id>.<packet>.verify.json`:

```json
{
  "source_id": "<catalog id>",
  "reader": "Claude, verify pass <date>",
  "checks": [
    {"path": "units[0].thickness", "verdict": "agree"},
    {"path": "observations[2].intervals[1].bottom", "verdict": "disagree",
     "value": "12 ft", "note": "the 10 ft value is the top of the next layer"},
    {"path": "units[3].age", "verdict": "unclear", "note": "OCR garbled"},
    {"path": "surfaces[0].datum", "verdict": "agree"}
  ]
}
```

Include every path from the plan, in the same order. Then run

    python -m extract.ingest .cache/results/<id>.<packet>.json --verify .cache/results/<id>.<packet>.verify.json

Disagreements lower the value's confidence and go to `data/review/queue.json`
for a person to settle; they are not silently corrected.

## Image values

A value with an `image` object was read from a page image tile
(`.cache/images/<id>/`, listed in `manifest.json` and in the packet
header). Its quote is a transcription, not text of the page, so it is
stored (as `extraction_method` "llm-image") only when this pass checks it.
Every such value is in the plan. For each one, re-view the tile named in
`image.tile` with the Read tool, look at the `box` (pixels from the tile's
top-left corner), and decide:

- `agree` -- the box shows this label or feature, drawn and labelled, and
  the value matches it (same digits, sign and units; a point on a section
  agrees with the drawing at the scale's precision).
- `disagree` -- the box shows something else, the value comes from a
  legend-only symbol, or it belongs to another line, hole or unit. Give the
  reading you see in `value` and explain in `note`.
- `unclear` -- the image does not settle it (faint, overprinted, cut by the
  tile edge: then look at the neighbouring tile too).

A value marked `unclear` by the first pass is `agree` when its range or
reading is faithful to what the image shows. Note in `note` which tile you
viewed when it was not the one cited.
