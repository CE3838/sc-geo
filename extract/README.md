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
prompts/verify.md   a second pass re-reads table and subsurface values
                    + a 10% sample of the rest                                (MODEL)
extract/ingest.py   validate, check every quote on its page, normalize,
                    compute confidence, write data/extracted, review queue    (no model)
```

| File | Purpose |
| --- | --- |
| `pdftext.py` | Per-page text with `pdftotext -layout` (and reading order), `pdfinfo`; OCR (`ocrmypdf --skip-text`, or `pdftoppm` + `tesseract`) for pages with no text layer; each page marked `pdf_text`, `ocr` or `none` |
| `triage.py` | Page kinds (blank, title, toc, index, references, content) used only to skip or rank pages, never to decide values |
| `packets.py` | One or more Markdown packets per document with the catalog header and `=== PAGE n (method) ===` blocks |
| `schema.json`, `schema.py` | What one document's extraction contains; standard-library validator |
| `patterns.py` | Deterministic normalizers used after the model: Munsell, lengths to feet, signed elevations, vertical datums, USCS, SPT N, strike/dip, coordinates (decimal, DMS, SC State Plane NAD83), ages to Ma, unit names to Geolex |
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

## Where full text comes from

`harvest/pdfs.py` tries, in order: PDF links in the catalog; the USGS
Publications Warehouse; Unpaywall (`CONTACT_EMAIL`), OpenAlex and
open-licensed Crossref links for catalog DOIs; then, for records still
without text, a Crossref DOI lookup (`harvest/openaccess.py`), followed by
the same open-access sources for the DOI it finds (or the Publications
Warehouse for a USGS DOI); NGMDB PDF scans; NGMDB browse images
(`harvest/ngmdb_images.py`); SCDNR FTP zips. Records still without open text
go to `data/review/needs_access.json`, with the Crossref DOI and match score
when there is one, for library access.

**Crossref matching.** A Crossref hit counts only with title token-set ratio
>= 0.9 (and the shorter title covering at least 75% of the longer one's
words), year within 1, and the same first-author surname. Crossref records
with no authors (common for USGS series) need a title ratio >= 0.97 and the
same year (`author_check: "no authors in Crossref"`). Two different DOIs that
both pass are recorded as `ambiguous` and neither is used. Every lookup keeps
the score. Responses are cached in `.cache/api`, keyed by record or DOI and
never by URL, so the contact email never reaches the disk. Requests are
limited to 8 per second per service.

### NGMDB browse images: terms and limits (checked 2026-10-03)

Most SCGS 1:24,000 maps have no PDF on NGMDB but are shown as zoomable images
(Zoomify tiles under `/img2/`). `harvest/ngmdb_images.py` downloads one
image's full-resolution tiles (1,400-2,000 tiles, about 15 MB, roughly 12
minutes at the configured pace) and assembles them, undecoded, into a
one-page PDF that is OCRed like any scan. One image is one page; the image
URL is the locator of every value read from it. Images and OCR text stay in
`.cache`.

What the sources say:

- NGMDB has no terms-of-use page. Its `robots.txt` **disallows `/img1/`,
  `/img2/`, `/img4/` and `/ngm-bin/` for all crawlers**. Only Twitterbot is
  allowed `/img*`. `/ngm-bin/` also covers the PDF scan downloads
  (`download.pl`) and the search API that `harvest/catalog.py` uses.
- USGS's "Copyrights and Credits" page: USGS-authored material is public
  domain, but some non-USGS images and graphics are used with permission and
  are generally marked as copyrighted.
- The SCGS sheets are SCGS publications (the product pages name the South
  Carolina Geological Survey as provider, and SCGS sells printed copies). The
  sheets seen so far carry no copyright notice. Rockville, for example, is
  "produced in cooperation with the U.S. Geological Survey National
  Cooperative Geologic Mapping Program".

How the use is limited: images are a fallback only, used when a record has no
other full text. The image's provider must be SCGS or USGS, and the record's
publisher a South Carolina state agency or USGS (`config/extract.json`
`ngmdb_images.providers` and `.publishers`); a USGS-supplied scan of an AAPG
or journal map is not used. Downloads run with 2 tile workers and the
harvester's pause between requests. Only facts with short quotes are stored;
images and OCR text are never committed. `ngmdb_images.enabled` turns the
source off, and `tier_offset: 1` cuts the requests to about a quarter, at
half resolution. robots.txt is a crawler policy, not a license, but it is a
clear signal: asking NGMDB (ngmdb@usgs.gov) or SCGS for bulk access to the
SCGS map images would settle it. Decision (2026-10-03): the repository owner
chose to use the images anyway, throttled: `enabled: true`, `tier_offset: 1`
(half resolution), `tile_workers: 2`, with the harvester's pause between
requests.

### OCR text is not published from CI

The weekly workflow OCRs scans in CI, but the OCR text stays in its Actions
cache, which scheduled Claude Code sessions cannot reach. Publishing it would
put full-text extracts on the internet under this repository: a workflow
artifact of a public repository can be downloaded by anyone signed in to
GitHub, and a release or branch is worse. That conflicts with CLAUDE.md
rule 3. For the SCGS sheets it would also republish state-published maps as
text. So sessions OCR for themselves: `SESSION.md` installs `tesseract-ocr`
and `ocrmypdf` first, and `next_batch` downloads and OCRs on the fly. If the
repository were private, a short-lived artifact would be acceptable; that is
the owner's call.

## Long documents: packet by packet

Every document is read in full (only blank, contents, index and needs-OCR pages
are left out). A long document is split into packets of about 40k tokens and
may be read over several sessions:

- Each packet lists stable block ids: `"12"` for a whole page, `"13.2/3"` for
  part 2 of 3 of page 13. Block ids do not depend on packet numbering, so a
  fresh session that rebuilds the packets still lines up with earlier work.
- `next_batch` hands out packets within `--max-tokens`, documents already
  started first, and only their unread packets.
- A result names the packet(s) it covers. `ingest` merges it into
  `data/extracted/<id>.json`: earlier values are kept, except values on the
  pages being re-read (so re-ingesting a packet replaces it); values with the
  same field, page and quote as one already stored are dropped. It records
  `blocks_done` and sets `"complete": true` when every block is in; only then
  is the document marked done. A result without `packets` covers the whole
  document. Files written before this (no `complete` key) count as complete.

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
| S, source | Map-unit values (`units`) read from a map sheet (an NGMDB scan, or a file whose name contains plate, sheet or map) of a record with a scale: `merge.score.scale_weight` (1:24,000 or larger 0.95; 1:62,500 0.9; 1:100,000 0.85; 1:250,000 0.7; 1:500,000 0.55; 1:1,000,000 0.45; smaller 0.35), because map-unit descriptions are generalized to the map's scale. Everything else (report text, observations, structures, groundwater, references): 0.85 for agencies, state surveys and journals listed in `config/extract.json` `trusted_publishers`, else 0.7; a boring log is not less reliable because the report's index map is small-scale. Drafts at most 0.6 |
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

## Subsurface values

For cross sections, a result may also hold `surfaces` (the elevation or depth
of the top or base of a unit at one place, with `datum`, `observation` and
`method`: measured, contour, interpolated or stated), `contours`
(structure-contour and isopach maps, with the legible contour labels as
`values`) and `sections` (published cross sections: ends, vertical
exaggeration, datum, wells shown, and units along the line). Observations
gain `datum` and `depth_reference` (land surface or elevation). All are
optional, so earlier results still validate. They are quote-checked and
stored like every other value, and every one of them is in the verify plan.

Normalized forms: `elevation`, `top_elevation` and `base_elevation` keep
their sign (`patterns.elevation_ft`: "-62 ft" and "62 ft below sea level"
are both -62); `depth`, `interval`, `length` and distances are lengths;
`datum` maps to NGVD29, NAVD88, MSL, land surface or unknown
(`patterns.vertical_datum`; the value as printed is kept, and no datum is
converted to another); contour labels and vertical exaggeration are numbers.

## Derived coordinates

Every `location` or `coordinates` value that `model/coords.py` can read
(decimal degrees, degrees-minutes-seconds, USGS packed DDMMSS/DDDMMSS, SC
State Plane NAD83 in feet or metres, NAD27 North/South zone in feet) gets a
`derived_coordinates` entry: its own StoredValue with `extraction_method`
"inference", `inferred: true`, the same page, and confidence lowered by the
inference factor. It names the conversion, the horizontal datum, whether it
is approximate (NAD27 shifted with a 3-parameter shift, or datum not
stated) and every assumption made (such as a western longitude with no sign).
Ambiguous text (State Plane without a datum, NAD27 without its zone, two
places, two latitudes) gives no derived value. The value as printed is
unchanged.
