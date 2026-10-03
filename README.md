# sc-geo

Public, open-source core of a South Carolina geologic knowledge system.
The pilot area is Charleston County.

The viewer in `web/` is a MapLibre GL JS map of South Carolina over USDA NAIP
aerial imagery, with the merged geologic map (or the USGS SGMC layer) and
SGMC faults and shear zones. The left panel lists the layers and the map-unit
legend; the status bar shows the cursor in SC State Plane (NAD83, feet) and
lat/lon, and the map scale. Click anywhere for a callout with coordinates,
ground elevation (USGS 3DEP, via the Elevation Point Query Service) and Google
Street View. "Card" opens a property card for the map unit there: age and Ma
range, a confidence score with its reasons, cited properties, other maps'
interpretations, key references from the source catalog, and soil
properties from NRCS SSURGO (Soil Data Access). It is deployed to GitHub
Pages by `.github/workflows/ci-pages.yml`.

See [CLAUDE.md](CLAUDE.md) for project rules and layout.

Licensed under the Apache License 2.0.
