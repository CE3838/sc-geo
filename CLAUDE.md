# CLAUDE.md

Guidance for Claude (and humans) working in this repository.

## Rules

1. **Provenance on every stored value.** Every stored value carries a
   `source_id`, `page`, `extraction_method`, and `confidence`. Use
   `model.provenance.StoredValue`; do not store bare values.
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
6. **Every pull request includes tests and a summary.**

## Project notes

- This is the public, open-source (Apache-2.0) core of a South Carolina
  geologic knowledge system.
- Internal wells and borings live in the private repo `sc-geo-internal`. They
  are loaded only in the user's browser and never pass through this repo, its
  workflows, or GitHub Pages.
- The pilot area is **Charleston County** (see `config/pilot_area.json`).
- The API contact email is stored in the Actions secret `CONTACT_EMAIL`. Read
  it from the environment when needed; **never print it in logs**.
- There is **no OpenRoads license**. CAD imports come from consultants as
  LandXML, DWG, DXF, DGN v7, KML, and KMZ. Native DGN v8 files cannot be read
  and are listed by name only. DWG has no free browser reader, so DWG files
  are also listed by name only; ask consultants for DXF or LandXML instead.
- Every imported CAD file keeps its layers. In the viewer's layer panel each
  layer can be toggled on and off or deleted.
- The CAD layer panel is hidden for now; add `?cad` to the viewer URL to
  show it.
- CAD files are parsed in the browser (`web/cad/`) and never uploaded. DXF,
  DGN v7 and LandXML coordinates are assumed to be SC State Plane (NAD83);
  units come from the file when it says, otherwise international feet. The
  panel's coordinate selector overrides this.

## Layout

| Path | Purpose |
| --- | --- |
| `config/` | Pilot area, source lists, and other settings |
| `harvest/` | Resumable jobs that discover and download public sources |
| `extract/` | Parsers and prompts that pull values out of sources |
| `model/` | Data model, including provenance (`StoredValue`) |
| `data/` | Small public derived data only (no PDFs, no internal data) |
| `review/` | Tools for human review of extracted and inferred values |
| `web/` | Static MapLibre GL JS viewer, deployed to GitHub Pages |
| `web/cad/` | In-browser CAD readers (LandXML, DXF, DGN v7, KML, KMZ) and layer state |
| `scripts/` | Checks that need network access (`check_imagery.mjs`, `viewer_smoke.mjs`) |
| `tests/` | Python tests (`pytest`), web tests (`tests/web`, `node --test`), fixtures |

## Commands

```sh
python -m pytest            # Python tests
node --test "tests/web/*.test.mjs"  # web tests
python -m http.server -d web 8000   # serve the viewer locally
node scripts/check_imagery.mjs      # confirm NAIP imagery servers respond
```
