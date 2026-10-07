# CLAUDE.md

Guidance for Claude (and humans) working in this repository.

## Rules

1. **Provenance on every stored value.** Every stored value carries a
   `source_id`, `page`, `extraction_method`, and `confidence`. Use
   `model.provenance.StoredValue`; do not store bare values. Sources without
   pages (GIS datasets) give a `locator` (such as a feature ID) instead.
2. **Flag inferences.** Any value that was inferred rather than read directly
   from a source is stored with `inferred=True`.
3. **No full-text PDFs or internal data in this repo.** Never commit source
   PDFs, full-text extracts, or anything from `sc-geo-internal`. `.gitignore`
   blocks the common cases and `tests/test_repo_rules.py` fails CI if a PDF is
   tracked.
4. **Jobs are resumable and finish within 6 hours.** Harvest and extraction
   jobs checkpoint their progress, skip work already done on restart, and stay
   under the 6-hour GitHub Actions job limit.
5. **Tests first.** Write or update tests before changing a parser or a prompt.
6. **Every pull request includes tests and a summary.** In this public repo the
   summary is one neutral line (what area changed, "tests pass"): no project
   decisions, data counts, source or site names, legal/terms discussion, or
   anything about internal or client work. The same applies to commit
   messages, PR titles and PR comments here. Detailed notes go only in the
   private repo or the chat.
7. **Minimal traffic to every source.** Each site we query or download from
   gets as few requests as possible: layers that query other servers live
   start off (`web/live.js`), requests wait until the map stops, results are
   cached, and harvest jobs are throttled, resumable and never re-download
   what they have.
8. **Follow each source's terms; cite everything; no warranty.** Keep every
   attribution, citation and condition a source sets for reusing its data;
   every value links back to its source and page. The viewer, the data
   package and the README say the data is provided as is, without warranty.

## Project notes

- This is the public, open-source (Apache-2.0) core of a South Carolina
  geologic knowledge system.
- This repo and the GitHub Pages site present **public data only**. There is
  no way to enter or load internal data here.
- Internal features live only in the Windows desktop app in the private repo
  `sc-geo-internal` (Tauri, internal use): internal wells and borings, and CAD
  import. Their files are read on the user's PC and never pass through this
  repo, its workflows, or GitHub Pages. The app reuses `web/` at build time and
  adds its panels through `window.scGeo.popupItems` (see `web/app.js`).
- Each deploy publishes the public data package (`python -m merge.package`:
  merged geology, SGMC, catalog, lexicon, SC outline, with a SHA-256 manifest)
  as a GitHub Release tagged `data-YYYYMMDD-HHMM`; the desktop app bundles the
  newest one. Only `data-*` releases are published here.
- The pilot area is **Charleston County** (see `config/pilot_area.json`).
- The API contact email is stored in the Actions secret `CONTACT_EMAIL`. Read
  it from the environment when needed; **never print it in logs**.
- There is **no OpenRoads license**. CAD imports (desktop app only) come from
  consultants as LandXML, DWG, DXF, DGN v7, KML, and KMZ. Native DGN v8 files
  cannot be read and are listed by name only. DWG has no free browser reader, so DWG files
  are also listed by name only; ask consultants for DXF or LandXML instead.
- Every imported CAD file keeps its layers. In the desktop app's layer panel
  each layer can be toggled on and off or deleted.
- Geology base layer: USGS State Geologic Map Compilation (SGMC), SC units
  from two 1:500,000 source maps (Piedmont/Blue Ridge and Coastal Plain).
  `harvest/sgmc.py` downloads it during deploy into `web/data/geology/`
  (generated, not committed). Age and rock-type color classes are derived and
  flagged inferred.
- Source catalog: `data/catalog/sc_catalog.json` lists every SC geology map,
  report and paper (NGMDB, SCGS 1:24k index, SCDNR FTP), merged by
  publication number with provenance. Unit names: `data/lexicon/geolex_sc.json`
  (USGS Geolex). `model/units.py` turns age text into Ma ranges (ICS chart) and
  matches unit names across maps.
- Viewer (matches the plan's mock-ups): header, Layers and Map units panel,
  status bar in SC State Plane feet, click callout (elevation from USGS 3DEP
  EPQS) and a property card: confidence and its "why", cited properties, NRCS
  SSURGO soil estimates (Soil Data Access, live) and key references
  (`merge/references.py` → `web/data/geology/references.json`). Faults and
  shear zones come from the SGMC structure layer (`harvest/sgmc.py`).
- Roads: US Census Bureau TIGER/Line roads (TIGERweb Transportation
  MapServer, Primary/Secondary/Local Roads; public domain, live, attributed;
  nothing copied), with route shields and street names (bundled Noto Sans glyphs in
  `web/fonts/`). Parcels: county services listed in `config/parcel_registry.json`
  (all 46 counties; `python -m harvest.parcel_registry` checks them), queried
  live from zoom 15; only parcel ID (TMS/PIN), acreage, address and record
  link are requested. **Never request or show owner names.**
- Water monitoring layer: USGS Water Data OGC API (api.waterdata.usgs.gov,
  live from the browser, CORS ok) via `web/usgs-water.js`; stations load for
  the area on screen (no fetch above 150 square degrees); clicking a station
  opens an SVG chart (`web/water-chart.js`, `web/water-ui.js`).
- Document extraction (`extract/`, `harvest/pdfs.py`): Claude reads every
  catalog source with legal open full text; code does the rest. No-LLM
  plumbing downloads PDFs, pulls page text (OCR for scans), and builds packets
  in `.cache/` (never committed). A Claude Code session follows
  `extract/SESSION.md`: `python -m extract.next_batch`, read the packets with
  `extract/prompts/extract.md`, write results per `extract/schema.json`, then
  `python -m extract.ingest`, which checks every quote against the cited page
  and stores values as StoredValue (`extraction_method` "llm"). Outputs:
  `data/extracted/`, `data/review/queue.json` (unverified or conflicting
  values), `data/review/needs_access.json` (no open full text).
  Records that are one chapter of a multi-paper volume PDF are limited to
  their own pages by `config/catalog_scope.json` (`extract/scope.py`):
  packets hold only those pages and ingest refuses values citing others.
  Results may also hold subsurface data for cross sections (`surfaces`,
  `contours`, `sections`, observation `datum`/`depth_reference`); printed
  locations are converted by `model/coords.py` into a separate
  `derived_coordinates` value flagged inferred.
- Goal: merge all sources into one GeMS-aligned result. Where maps overlap,
  the most detailed and recent map wins; confidence comes from scale, the
  mapper's identity confidence, agreement among other maps and published
  research. Disagreeing sources are kept as alternatives with citations.
- In the desktop app, DXF, DGN v7 and LandXML coordinates are assumed to be
  SC State Plane (NAD83); units come from the file when it says, otherwise
  international feet. The panel's coordinate selector overrides this.

## Layout

| Path | Purpose |
| --- | --- |
| `config/` | Pilot area, `sources.json` (data sources and URLs), `catalog_scope.json` (chapter page ranges), other settings |
| `harvest/` | Resumable jobs that discover and download public sources |
| `extract/` | Parsers and prompts that pull values out of sources |
| `model/` | Data model: provenance (`StoredValue`), ages and unit names (`units.py`), shapefile/projection reader (`gisio.py`) |
| `data/` | Small public derived data only: `catalog/`, `lexicon/` (no PDFs, no internal data) |
| `merge/` | Merge all GIS sources into one surficial and one bedrock layer with confidence (`python -m merge.build`); pack the public data package (`python -m merge.package`) |
| `review/` | Tools for human review of extracted and inferred values |
| `web/` | Static MapLibre GL JS viewer, deployed to GitHub Pages |
| `scripts/` | Checks that need network access (`check_imagery.mjs`, `viewer_smoke.mjs`) |
| `tests/` | Python tests (`pytest`), web tests (`tests/web`, `node --test`), fixtures |

## Commands

```sh
python -m pytest            # Python tests
node --test "tests/web/*.test.mjs"  # web tests
python -m http.server -d web 8000   # serve the viewer locally
node scripts/check_imagery.mjs      # confirm NAIP imagery servers respond
python -m harvest.sgmc              # download SC geology into web/data/geology (needs network)
python -m harvest.catalog           # rebuild data/catalog (needs network; resumable)
python -m harvest.geolex            # rebuild data/lexicon (needs network; resumable)
python -m merge.build               # download, normalize and merge GIS sources into web/data/geology (needs shapely)
python -m merge.package             # pack the public data package (sc-geo-data.zip)
python -m harvest.pdfs --limit 5    # queue sources, download PDFs, page text (needs poppler; resumable)
python -m extract.next_batch --n 5  # next documents for a reading session (see extract/SESSION.md)
python -m extract.ingest RESULT.json  # verify quotes and store extracted values
```
