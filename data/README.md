# data

Small, public, derived data only. No source PDFs, full-text extracts, or
internal wells and borings (those live in `sc-geo-internal` and load only in
the user's browser).

- `catalog/`: every SC geology map, report and paper (`harvest/catalog.py`).
- `lexicon/`: Geolex unit names (`harvest/geolex.py`).
- `extracted/`: values read from documents by a model, one file per document,
  each with provenance, a short verbatim quote, and confidence
  (`extract/ingest.py`; see `extract/README.md`).
- `review/`: values awaiting a person, and records needing library access
  (see `review/README.md`).
