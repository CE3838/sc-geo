# web/data

`sc-region.geojson`: South Carolina's outline (`role: state`) and the
neighboring states used to mask imagery outside South Carolina (`role: mask`:
Georgia, North Carolina, Tennessee).

Source: U.S. Census Bureau cartographic boundary files (1:20,000,000,
public domain), as packaged by https://github.com/glynnbird/usstatesgeojson
(from http://eric.clst.org/Stuff/USGeoJSON). Coordinates are rounded to 5
decimal places; nothing else is changed. Shared state borders use identical
vertices, so the mask meets the outline exactly. At this scale small barrier
islands are not in the outline, which is why the mask covers only the
neighboring states and never the ocean.

`sc-counties.geojson`: the 46 South Carolina counties (`name`, `fips`), used
to pick which county parcel services to query for the view. Source: U.S.
Census Bureau 2010 cartographic boundary file, 1:20,000,000 (public domain),
as packaged by https://github.com/plotly/datasets
(`geojson-counties-fips.json`); South Carolina only, coordinates rounded to
4 decimals. It is generalized (small islands are left out), so the viewer
grows the view by a small margin before testing it against a county.

`parcel_registry.json`: generated from `config/parcel_registry.json` by
`python -m harvest.parcel_registry`; do not edit.

`../fonts/`: Noto Sans glyphs (Latin range) for map labels, from
https://github.com/protomaps/basemaps-assets, under the SIL Open Font
License (`web/fonts/OFL.txt`).
