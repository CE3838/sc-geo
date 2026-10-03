# extract

Parsers and prompts that pull values from sources into `model.provenance.StoredValue`.
Write tests before changing any parser or prompt.

## Reading documents with a model (engine-agnostic)

The ~1,600 catalog records that are not merged GIS (maps without GIS, reports
and papers) are read by a language model, not by rules. No paid API is used:
the reading happens in scheduled Claude Code sessions (see `SESSION.md`). Any
other model could do it from the same packets and prompts.

```
harvest/pdfs.py     find legal open full text, download, page text, OCR       (no model; CI or session)
extract/triage.py   mark blank / contents / index pages to skip               (no model)
extract/packets.py  page text -> packets under ~40k tokens in .cache/packets  (no model)
prompts/extract.md  the reading model writes result JSON per schema.json      (MODEL)
prompts/verify.md   a second pass re-reads table values + a 10% sample        (MODEL)
extract/ingest.py   validate, check every quote on its page, normalize,
                    compute confidence, write data/extracted, review queue    (no model)
```

| File | Purpose |
| --- | --- |
| `pdftext.py` | Per-page text with `pdftotext -layout` (and reading order), `pdfinfo`; OCR (`ocrmypdf --skip-text`, or `pdftoppm` + `tesseract`) for pages with no text layer; each page marked `pdf_text`, `ocr` or `none` |
| `triage.py` | Page kinds (blank, title, toc, index, references, content) used only to skip or rank pages, never to decide values |
| `packets.py` | One or more Markdown packets per document with the catalog header and `=== PAGE n (method) ===` blocks |
| `schema.json`, `schema.py` | What one document's extraction contains; standard-library validator |
| `patterns.py` | Deterministic normalizers used after the model: Munsell, lengths to feet, USCS, SPT N, strike/dip, coordinates (decimal, DMS, SC State Plane NAD83), ages to Ma, unit names to Geolex |
| `ingest.py` | `python -m extract.ingest result.json [--verify verify.json]` |
| `next_batch.py` | `python -m extract.next_batch --n 5`: next pending documents, building text and packets on the fly |
| `prompts/` | Instructions for the reading and verifying passes |
| `SESSION.md` | Steps for a scheduled Claude Code session (used as the Routine prompt) |

Where things live:

- `.cache/pdfs/`, `.cache/text/`, `.cache/packets/`, `.cache/results/`: PDFs, page
  text, packets and raw model results. Gitignored; never committed (CLAUDE.md rule 3).
- `.checkpoints/pdfs/`, `.checkpoints/extract/`: per-document progress.
- `data/extracted/<id>.json`: stored values (committed). Each value is short:
  the value, its page, a quote of at most 400 characters, and provenance.
- `data/review/queue.json`: values that need a person (committed).
- `data/review/needs_access.json`: records with no open full text, metadata
  only, for library access (committed).

## Quote verification

Every value must quote the page it cites. `ingest.find_quote` normalizes both
the quote and the page (Unicode NFKC, so ligatures like "ﬁ" become "fi"; curly
quotes and dashes; soft hyphens; words hyphenated across a line break, both
joined and with the hyphen kept; whitespace; case) and checks the layout text
and the reading-order text of the page:

| Match | Meaning |
| --- | --- |
| `exact` | The normalized quote is on the page (or, for quotes of 12+ letters, the same letters and digits in order) |
| `ocr` | Equal after folding common OCR confusions (rn/m, 0/o, 1/l/i, cl/d, 5/s, 8/b) |
| `fuzzy` | At least 90% of a 20+ character quote matches one place on the page |
| none | Not on the cited page: the value is NOT stored. If the quote is on the next or previous page it is queued as `wrong_page` (with `found_page`), otherwise as `quote_not_found` |

An `ocr` or `fuzzy` match on a page that has a real text layer is stored but also
queued (`inexact_quote`), because the model should have copied the text exactly.

## Confidence

The model never assigns confidence. `ingest.confidence` computes it as

    confidence = S x M x Q x V x I        (rounded to 3 decimals, clamped to 0..1)

| Factor | Value |
| --- | --- |
| S, source | Maps with a scale: `merge.score.scale_weight` (1:24,000 or larger 0.95; 1:62,500 0.9; 1:100,000 0.85; 1:250,000 0.7; 1:500,000 0.55; 1:1,000,000 0.45; smaller 0.35). Other documents: 0.85 for agencies, state surveys and journals listed in `config/extract.json` `trusted_publishers`, else 0.7. Drafts at most 0.6 |
| M, text method | 1.0 for the PDF text layer; 0.9 for OCR text |
| Q, quote match | `exact` 1.0; `ocr` 0.95; `fuzzy` 0.85 |
| V, second pass | `agree` 1.0; not checked 0.85; `unclear` 0.7; `disagree` 0.4 (and queued for review) |
| I, inference | 0.8 when the model flagged the value `inferred`, else 1.0 |

So a quoted, verified value from a 1:24,000 map's text layer gets 0.95; the same
value unverified 0.81; from an OCR page, unverified, 0.73. All factors are in
`config/extract.json` `confidence`.

## Normalized values

`ingest` adds a `normalized` object where a normalizer applies: lengths
(`top`, `bottom`, `thickness`, `total_depth`, `water_level`, `elevation`,
`head`) as `min_ft`/`max_ft`; Munsell parts; USCS symbols; SPT N; liquid limit,
plasticity index and moisture as numbers; strike azimuth and dip; coordinates
as latitude/longitude (SC State Plane assumed NAD83 international feet unless
stated, flagged `datum_inferred`); dates as ISO; ages as Ma ranges and unit
names as Geolex names, both flagged `inferred: true` (CLAUDE.md rule 2). The
value as stated is always kept.
