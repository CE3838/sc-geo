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
| `patterns.py` | Deterministic normalizers used after the model: Munsell, lengths to feet, signed elevations, vertical datums, USCS, SPT N, strike/dip, ages to Ma, unit names to Geolex |
| `ingest.py` | `python -m extract.ingest result.json [--verify verify.json]` |
| `renormalize.py` | `python -m extract.renormalize [--write]`: recompute normalized fields of committed files (dry run by default) |
| `labtests.py` | Water-test parameter names and rock-test types (normalized only when unambiguous, flagged inferred), values with qualifiers, and the review checks for test values (missing units, a "\|" read as a digit, unread values) |
| `reread.py` | `python -m extract.reread <ID> --pages 1`: re-read chosen pages of a document already read, from `.cache` only; `--next` hands out the re-read queue, `--queue` rebuilds it |
| `next_batch.py` | `python -m extract.next_batch --n 5`: next pending documents, building text and packets on the fly |
| `images.py` | `python -m extract.images <ID> --pages 1 [--dpi 250] [--grid 3x3] [--crop x0,y0,x1,y1] [--reread]`: page overview and overlapping PNG tiles from the cached PDF into `.cache/images/<id>/` with a manifest of boxes; the image side of ingest (locators, confidence cap) |
| `reading_list.py` | `python -m extract.reading_list`: ranks online catalog records by South Carolina geologic relevance into `config/reading_list.json`, with scores and exclusion reasons in `config/reading_list_scores.json` |
| `prep.py` | `python -m extract.prep --todo`: reading-list documents not yet read; `--next N` builds their text and packets ahead of a session |
| `prompts/` | Instructions for the reading and verifying passes |
| `SESSION.md` | Steps for a scheduled Claude Code session (used as the Routine prompt) |

Where things live:

- `.cache/pdfs/`, `.cache/text/`, `.cache/packets/`, `.cache/results/`: PDFs, page
  text, packets and raw model results. Gitignored; never committed (CLAUDE.md rule 3).
- `.checkpoints/pdfs/`, `.checkpoints/extract/`: per-document progress.
- `data/extracted/<id>.json`: stored values (committed). Each value is short:
  the value, its page, a quote of at most 400 characters, and provenance.
- `data/review/queue.json`: values that need a person (committed).
- `data/review/reread_queue.json`: pages of documents already read that need a
  re-read, with the reason and status (committed; see Re-reads below).
- `data/review/needs_access.json`: records with no open full text, metadata
  only, for library access (committed).
- `data/review/not_applicable.json`: online records left off the reading list
  as low value for SC geology, marked "read: not applicable" with the reason
  (`already_read` for documents read before; their values stay). Written by
  `python -m extract.reading_list`; `next_batch` skips them unless asked by id.

## Where full text comes from

`harvest/pdfs.py` tries, in order: PDF links in the catalog; the USGS
Publications Warehouse; Unpaywall (`CONTACT_EMAIL`), OpenAlex and
open-licensed Crossref links for catalog DOIs; then, for records still
without text, a Crossref DOI lookup (`harvest/openaccess.py`), followed by
the same open-access sources for the DOI it finds (or the Publications
Warehouse for a USGS DOI); for records whose GIS is merged, the map-sheet
PDFs inside their GeMS package (from `merge.build`'s `.cache/sources/` copy,
downloaded there once if missing; the GIS files are never read as text);
NGMDB PDF scans; NGMDB browse images
(`harvest/ngmdb_images.py`); SCDNR FTP zips (never the GIS shapefile zips). Records still without open text
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
| S, source | Map-unit values (`units`) read from a map sheet (an NGMDB scan, or a file whose name contains plate, sheet or map) of a record with a scale: `merge.score.scale_weight` (1:24,000 or larger 0.95; 1:62,500 0.9; 1:100,000 0.85; 1:250,000 0.7; 1:500,000 0.55; 1:1,000,000 0.45; smaller 0.35), because map-unit descriptions are generalized to the map's scale. Everything else (report text, observations, structures, groundwater, references): 0.85 for agencies, state surveys and journals listed in `config/extract.json` `trusted_publishers`, else 0.7; a boring log is not less reliable because the report's index map is small-scale. Values read from contour maps (`contours`, and `surfaces` with method contour) of a record with a scale take its scale weight: more detailed maps weigh more (`contour_scale_weight`). Drafts at most 0.6 |
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
plasticity index and moisture as numbers; strike azimuth and dip; dates as ISO; ages as Ma ranges and unit
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
are both -62), and so does a groundwater `head`; a head given relative to land
surface stays as printed, marked `relative_to: "land surface"` and
`direction` (below, above, or null when the printed sign carries it); `depth`, `interval`, `length` and distances are lengths;
`datum` maps to NGVD29, NAVD88, MSL, land surface or unknown
(`patterns.vertical_datum`; the value as printed is kept, and no datum is
converted to another); contour labels and vertical exaggeration are numbers.

## Water tests and rock tests

`water_tests` and `rock_tests` (optional, so earlier results still
validate) hold one entry per test result, each a value with page and
quote like every other value:

- **water_tests**: water-sample results, field measurements and hydraulic
  tests. `kind` (well, boring, spring...; a plain string), `observation` (the
  site label), `location`, `sample_id`, `date`, `top`/`bottom` or `depth` with
  `depth_reference` and `datum`, `aquifer`, `unit`, `parameter` (as printed),
  `value`, `units`, `qualifier`, `fraction`, `method`, `lab`, `source_table`.
- **rock_tests**: specimen and core tests (UCS, point load, Brazilian
  tensile, triaxial, slake durability, RQD and core recovery, unit weight and
  density, absorption, elastic modulus, Poisson's ratio). The site and depth
  fields as above, plus `rock_type`, `test_type` (as printed), `parameter`,
  `value`, `units`, `qualifier`, `specimen_dimensions`, `specimen_condition`,
  `confining_pressure`, `failure_mode`, `standard` (as printed, e.g. "ASTM
  D7012, method C"), `lab`, `source_table`.

A test links to its site the way a surface does: `observation` is the
label of a well, boring, core or spring (an observation of the same
document when there is one; observations may now be `spring`s).

Ingest quote-checks, verifies and stores them like everything else, and
every test value is in the verify plan. `labtests.py` adds `normalized`
forms: a parameter name and category (field, major_ion, nutrient,
metal_trace, organic, pesticide, isotope_age, dissolved_gas, hydraulic) or a
rock-test type, both `inferred: true` and only when exactly one name fits
("Calcium and magnesium" gets none; "ASTM D7012" alone, which covers
unconfined and triaxial tests, gets none); `value` as `{number, qualifier}`
or `{min, max, qualifier}` ("<0.5", "ND", "1.2E-04", "2.0x10-9", "0.09 to
0.21"); `qualifier` as <, >, ND or E; depths as feet. The review queue gets:

| Problem | When |
| --- | --- |
| `missing_units` | no units in `units`, in the value object's `units` or in the value text; units are never guessed (pH, Poisson's ratio, specific gravity and not-detected values are exempt) |
| `ocr_digit` | the quote shows a "\|" where a digit belongs ("\| to 6 feet", "0.\|2") |
| `unclear_value` | the value is not a number, a range or a qualifier |

## Site tests export

`python -m merge.site_tests` writes `web/data/sites/site-tests.json` (not
committed; deploy builds it before `merge.package`, which ships it as
`data/sites/site-tests.json` in the data package). It holds the water and
rock tests of `data/extracted`, public catalog records only, grouped by
site, for the viewer's click callout and the cross-section tool:

```json
{
 "format": "sc-geo site tests", "version": 1, "generated": "...", "notes": "... without warranty ...",
 "counts": {"sites": 1, "water_tests": 1, "rock_tests": 0, "sources": 1},
 "sources": {"ngmdb:46513": {"citation": "...", "title": "...", "year": 1999, "publisher": "..."}},
 "sites": [{
  "id": "ngmdb:46513#BFT1234", "source_id": "ngmdb:46513", "label": "BFT-1234", "site_key": "BFT1234",
  "kind": "well", "observation_matches": 1,
  "location": {"lat": 32.4, "lon": -80.7, "as_printed": "...", "from": "observation", "page": 11,
               "inferred": true, "confidence": 0.6, "conversion": "...", "datum": "NAD83",
               "approximate": false, "assumptions": []},
  "elevation": {"as_printed": 12, "units": "ft", "ft": 12.0, "datum": "NGVD29", "datum_as_printed": "NGVD of 1929",
                "page": 11, "confidence": 0.8},
  "total_depth": "25 ft",
  "water_tests": [{
   "source_id": "ngmdb:46513", "pages": [13],
   "parameter": {"as_printed": "Chloride", "name": "chloride", "category": "major_ion", "inferred": true},
   "value": {"as_printed": "<0.5", "number": 0.5, "qualifier": "<", "units": "milligrams per liter"},
   "date": "1997-06-10", "depth": {"top_ft": 15.0, "bottom_ft": 25.0, "reference": "land surface"},
   "method": "...", "source_table": "Table 3",
   "fields": {"value": {"value": "<0.5", "page": 13, "quote": "...", "confidence": 0.81, "inferred": false,
                        "verification": "agree", "locator": null}}
  }],
  "rock_tests": []
 }]
}
```

- A site is one label in one document (labels compared without case,
  spaces or dashes: `site_key`); tests with no label are grouped by their
  printed location, and tests with neither are one `unplaced` site.
  Sites of different documents are not merged; the same `site_key` in two
  documents marks a possible match.
- `location` is the inferred `derived_coordinates` of the test's own
  location, or else of the first observation with that label
  (`observation_matches` says how many there were). Without one, `lat` and
  `lon` are null and the printed location is kept. `elevation` is the
  observation's (with `navd88` when the conversion has added one).
- `depth` is in feet: depths below land surface when `reference` is "land
  surface", signed elevations when it is "elevation" (then in the site's or
  the test's datum). No elevation is computed from a depth here.
- `fields` holds every stored field of the test with its page, quote,
  confidence, inferred flag, verification and locator, so each number can
  be cited; `sources` gives the citation of each document.
- `units` is null when the source prints none (the value is in the review
  queue).

## Derived coordinates

Every `location` or `coordinates` value that `model/coords.py` can read
(decimal degrees, degrees-minutes-seconds, USGS packed DDMMSS/DDDMMSS, SC
State Plane NAD83 in feet or metres, NAD27 North/South zone in feet) gets a
`derived_coordinates` entry: its own StoredValue with `extraction_method`
"inference", `inferred: true`, the same page, and confidence lowered by the
inference factor. It names the conversion, the horizontal datum, whether it
is approximate (NAD27 shifted with a 3-parameter shift, or datum not
stated) and every assumption made (such as a western longitude with no sign).
Ambiguous text (NAD27 without its zone, two places, two latitudes) gives no
derived value.

SC State Plane with no horizontal datum printed (NAD27 and NAD83 grid
values differ by hundreds of feet) is converted only for sources whose
catalog `year` is after 1990: NAD83 (FIPS 3900) is assumed, the value is
marked approximate with `datum_assumed: true` and the note "datum not
printed; NAD83 assumed (published after 1990)", and its confidence is the
printed-datum conversion's times 0.75, **capped at 0.5**
(`ingest.ASSUMED_DATUM_FACTOR`, `ingest.ASSUMED_DATUM_CAP`), so it is always
below a printed-datum conversion. It is kept only when the point falls
inside the document's catalog `bbox` widened by 0.05° (`BBOX_MARGIN_DEG`).
Otherwise (1990 or earlier, no year, no bbox, outside the bbox) there is no
derived value and `coordinates_not_derived` says why. Printed NAD83 and
NAD27 are unchanged by this rule. The value as printed is
unchanged. (Files written before this may still carry an older lenient
`normalized` parse on locations; it is ignored, and `extract.renormalize`
removes it.)

## Re-reads

A document marked complete can have chosen pages read again
(`extract/reread.py`): image pages that were never OCRed, log pages whose
text layer holds only a caption, misread digits, or pages read before the
subsurface fields existed.

- `python -m extract.reread <ID> --pages 1,3-5` (or `--packets packet-02`)
  builds re-read packets `reread-NN` of exactly those pages (triage is not
  asked) in `.cache/packets/<id>/reread/`, with their own `index.json`
  (pages, blocks, reason, queue ids). The normal packets are untouched.
  The packet header names the reason and says the pages replace what was
  stored. Re-read names are never reused; the same request is served the
  same packets until they are ingested.
- It uses `.cache/text` only and never downloads. `--ocr` OCRs the chosen
  pages from the cached PDF (`pdftext.ocr_page`) and adds the OCR text to the
  page (any caption text layer is kept), marking it `ocr`. Pages with no
  text are left out and listed. Scoped records (`config/catalog_scope.json`)
  refuse pages outside their scope.
- The result (`"packets": ["reread-01"]`) is validated, quote-checked,
  verified (`--plan-verify`, `--verify`) and normalized exactly like any
  other. Ingest replaces every earlier value on the re-read pages (all parts
  of a split page). `complete`, `blocks_done` and `packets` are unchanged;
  the ingest entry gets `reread` (packets, pages, reason, queue ids).
- Nothing is silently lost: each ingest that replaces earlier values (a
  re-read, or a packet ingested again) appends to the file's `history`:
  `{at, reason, packets, pages, replaced: [{section, record}]}`, where
  `record` is the earlier record holding only the replaced values. The
  review queue drops the items for those pages and adds the new ones. Notes
  lines are stored once.

The re-read queue, `data/review/reread_queue.json`, is rebuilt by
`python -m extract.reread --queue` from:

| Origin | Reason | What |
| --- | --- | --- |
| `notes` | `subsurface_fields` | each `SUBSURFACE:` notes line in `data/extracted` (not `SUBSURFACE: none`) on pages with no `surfaces`, `contours` or `sections` stored; pages from the line (`p. 1`, `pages 3-10`), else the pages read |
| `ROADMAP 1.9` | `image_pages`, `logs`, `map_face` | known re-reads (`reread.KNOWN`) |
| `manual` | from `--reason` | `python -m extract.reread --add <ID> --pages 4 --reason "..." [--detail "..."]`; `water_tests` and `rock_tests` mark documents read before those sections existed whose notes name water-quality tables, aquifer tests or rock tests |

Each item has `id`, `source_id`, `pages`, `reason`, `detail`, `origin`,
`ocr` and `status`; it is `done` (with `done_at`) once ingests carrying its
queue id cover all its pages. `python -m extract.reread --next` hands out the
pending items in order (known re-reads first) as `next_batch` does.

## Page images

Map faces, cross sections and logs drawn as figures often OCR as scattered
or garbled text: unit positions along a section, distances, elevations,
drill-hole depths, contour labels, "|" for a digit. A reading session can
view a rendered page image instead (`extract/images.py`).

- `python -m extract.images <ID> --pages 1` renders, from the cached PDF only
  (never downloads; with none cached it points to `python -m harvest.pdfs
  --id <ID>`), an overview of the page and overlapping tiles of at most
  `images.max_tile_px` (1,500) pixels a side, so the Read tool shows them
  unscaled. Default 250 dpi (`--dpi`), never above a scan's own resolution
  (NGMDB browse images are assembled at 144 ppi) or `max_dpi`. `--grid 3x3`
  sets columns x rows; `--crop x0,y0,x1,y1` tiles one region given in PDF
  points. Tiles go to `.cache/images/<id>/` (never committed) with
  `manifest.json`: per tile its id, page, file page, dpi, `px_box` (pixels
  of the whole page at that dpi), `pt_box` (PDF points from the page's
  top-left corner), size, estimated tokens, and the file's URL and sha256.
  Tiles already rendered are not rendered again.
- Re-reads: `python -m extract.reread <ID> --pages 1 --images` (or
  `extract.images ... --reread`) also renders tiles and lists them in the
  packet header; pages with no text are then kept. `--next` does this for
  queue items with reason `map_face`, `image_pages` or `subsurface_fields`,
  or whose detail names a cross section (each queue item has `images`); if
  the render fails, the text packet is still handed out.

**Provenance of image values.** A value read from a tile carries
`"image": {"tile", "box"}` (box in the tile's pixels) and, as its quote,
the text as transcribed from the image. Ingest first looks for the quote in
the page text: when found, the value is text-checked and stored as usual
(`extraction_method` "llm"), keeping the tile. Otherwise:

| Step | Rule |
| --- | --- |
| Locator | The tile must be in the manifest, on the page the value cites, and the box inside it; else `image_locator_invalid` (not stored) |
| Verify | Every image value is in the verify plan; one with no verdict is not stored (`image_not_verified`). The verify pass re-views the tile: agree, disagree or unclear |
| Stored | `extraction_method` "llm-image", `quote_match` "image", `text_method` "image", `image` {tile, box, dpi, page_px_box, pt_box, pdf_sha256, unclear}; `locator` `<file url>#page=N&viewrect=left,top,width,height` (PDF points of the cached PDF's page) |
| Confidence | `min(images.confidence.max, S x images.confidence.factor) x V x I`, times `unclear_factor` when the reader marked digits unclear (also queued `image_unclear`). With the defaults (max 0.6, factor 0.8, unclear 0.7) an image value never exceeds 0.6, below verified text values from the same source |
| Inferred | Section contact points, and a hole's distance read from a tile, are always stored `inferred: true` |

**Section geometry** (all optional, in `sections`): `horizontal_scale`,
`distance_units`, `elevation_units`, end-point `label`s, `contacts` (kind
contact, top, base or polygon; `unit`, `lower_unit`, `certainty`, and
`points` of `distance` and `elevation` in the section's own units against
its `datum`), and `holes` (label, observation, distance, land-surface
elevation, total depth, depth reference and intervals). Distances
normalize to feet like other lengths; elevations keep their sign.

## Re-normalizing committed files

When a normalizer changes, `python -m extract.renormalize` recomputes
`normalized` and `derived_coordinates` in `data/extracted/` from each stored
value's own value and units, with ingest's functions. It never changes a
value as read, its quote, page, provenance, confidence or verification, and
re-reads nothing. It is a dry run by default (a JSON report of every change);
`--write` writes the files.

## NAVD88 and agreement between sources

Every elevation with a usable datum gets a `navd88` value (extract/elevations.py,
model/vdatum.py): its own StoredValue, `extraction_method` "datum_conversion",
`inferred: true`, naming the conversion, the datum it came from and anything
assumed. NGVD29 is shifted with the NGS VERTCON grid that
`python -m harvest.vertcon` downloads once into `.cache/grids/`; "sea level"
counts as NGVD29 only in documents published before 1991; land surface stays
relative; no stated datum is kept as printed and marked approximate.

`python -m extract.agreement` (dry run; `--write` to record) pairs surface
points from different sources: same unit and boundary, within `distance_ft`,
at least one measured. Agreeing values are raised to
`1 - (1 - c)(1 - boost)^k` (at most `cap`) and list each other in
`agreement.agrees_with`; disagreeing values are kept and list each other as
alternatives. Run it after ingest and after `extract.renormalize`, which
rebuild confidences from ingest.

