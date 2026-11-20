# Quadrangle maps: GIS or PDF only

`python -m harvest.quad_gis` lists every 1:24,000 quadrangle map in the
source catalog by what is published for it, and writes
`data/catalog/quad_gis.json`. It reads only files already on disk (the
catalog, built from the product pages, the 1:24,000 index and GIS table, and
the FTP folder listing, plus the extra GIS sources named in `merge/build.py`),
so it makes no requests and a rebuild with the same catalog writes the same
file. Each record gives the map's id, quadrangles, year, format, download
URLs, record link and terms where a rule states them (flagged inferred, since
the record itself does not say).

## How these enter the merged map

- `gems`, `shapefile`, `gis_download`: `merge.build` already picks these up
  through `source_list`, from the same catalog fields: it downloads each
  package once into `.cache/sources`, normalizes it and overlays it, with the
  most detailed and most recent map winning. `quad_gis.json` is a checklist of
  what a full build should contain; a later step can compare it with
  `merged-sources.json` (used or skipped, and why).
- `gis_not_readable`: GIS exists but in a form the build cannot read without
  extra tools (for example a file geodatabase only). It needs a reader or an
  exported copy.
- `gis_listed_no_download`: a catalog says GIS exists, but no public download
  is linked. It needs a public copy from the publisher before it can be used.
- `pdf_only` and `not_online`: no GIS. These maps enter through their unit
  descriptions, read by `extract/` and linked to the merged polygons, not as
  new polygons. Digitizing their outlines would be a separate decision.

Before any of these datasets is redistributed (for example in the data
package), its publisher's terms need to be confirmed; `terms` is null where
nothing on disk states them.
