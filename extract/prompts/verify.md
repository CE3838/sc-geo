# Verification instructions (second pass)

You are checking values that another reading pass extracted from one
packet of a document. Work independently: do not look at the rest of the first pass's
result, only at the values listed for you, and re-read the cited pages
yourself.

## Input

1. The verify plan, printed by

       python -m extract.ingest .cache/results/<id>.<packet>.json --plan-verify > .cache/results/<id>.<packet>.plan.json

   It lists every value read from a table, every subsurface value, plus a
   random 10% of the others:
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
