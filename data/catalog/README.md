# Catalog of South Carolina geology maps and reports

`sc_catalog.json` lists every geology map, report and paper found for South
Carolina, built by `python -m harvest.catalog`. `summary.json` has counts.

Each record merges what the source catalogs say about one publication:

| Source | `provenance.source_id` | What it adds |
| --- | --- | --- |
| USGS National Geologic Map Database (NGMDB) catalog | `ngmdb-catalog` | Title, authors, year, publisher, series, scale, bedrock/surficial themes; from the product page the citation, bounding box, keywords and PDF/GIS/GeMS download links |
| SC Geological Survey 1:24,000 map index (ArcGIS) | `scgs-24k-index` | Quadrangles covered; maps in progress (`status: draft`) |
| SCGS table of maps with GIS | `scgs-24k-gis-table` | Whether SCGS holds GIS for the map |
| SCDNR GIS FTP folder | `scdnr-ftp` | Quadrangle shapefile downloads |

Records found in several catalogs are merged by publication number
(`series_key`, for example `SCGS GQM-5`). `kind` is `map` (has a map title, a
geology theme or quadrangles) or `publication` (reports and research papers).
