# harvest

Jobs that discover and download public sources. Each job must be resumable
(checkpoint progress, skip completed work on restart) and finish within 6
hours. Downloaded PDFs stay out of git.

- `catalog.py`, `geolex.py`, `sgmc.py`: catalog, unit names, base geology.
- `pdfs.py`: legal open full text for every catalog record that is not merged
  GIS (`python -m harvest.pdfs --limit N --max-minutes M`). Page text and OCR go
  to `.cache/`, records without open text to `data/review/needs_access.json`.
- `parcel_registry.py`: checks each county's parcel service in
  `config/parcel_registry.json` (layer answers, ID field present, CORS for
  the public site, max record count) and records the status and date. It
  reads layer descriptions only; it never downloads parcels.
