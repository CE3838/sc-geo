# sc-geo

Public, open-source core of a South Carolina geologic knowledge system.
The pilot area is Charleston County.

The viewer in `web/` is a MapLibre GL JS map of South Carolina over USDA NAIP
aerial imagery, with the merged geologic map (or the USGS SGMC layer) and
SGMC faults and shear zones. Two layers are read live from their owners for
the area on screen and never copied: roads with names and route shields
(SCDOT's public road inventory on ArcGIS Online), and, from zoom 15,
property lines with tax map parcel IDs from each county's own parcel service
(`config/parcel_registry.json`, checked by `python -m harvest.parcel_registry`;
counties without a public service get a note). The left panel lists the layers and the map-unit
legend; the status bar shows the cursor in SC State Plane (NAD83, feet) and
lat/lon, and the map scale. Click anywhere for a callout with coordinates,
ground elevation (USGS 3DEP, via the Elevation Point Query Service), the
road and parcel there (parcel ID, acreage, address and a link to the county
record; never owner names) and Google Street View. "Card" opens a property card for the map unit there: age and Ma
range, a confidence score with its reasons, cited properties, other maps'
interpretations, key references from the source catalog, and soil
properties from NRCS SSURGO (Soil Data Access). It is deployed to GitHub
Pages by `.github/workflows/ci-pages.yml`.

See [CLAUDE.md](CLAUDE.md) for project rules and layout.

Licensed under the Apache License 2.0.
