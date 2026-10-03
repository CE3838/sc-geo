# Web test fixtures

- `sda-*-mapunit.json`, `sda-*-horizon.json`: real NRCS Soil Data Access
  responses (captured 2026-10-03) to the queries built by `web/ssurgo.js`
  for three points: Berkeley County (-80.0, 33.0, Bethera loam), North
  Charleston (-79.96, 32.86, urban land) and the ocean off Charleston
  (-79.5, 32.5, no soil map unit). Public domain (USDA).
- `epqs-point.json`: a USGS Elevation Point Query Service v1 response in the
  documented format (`value` in feet as a string). The value is
  illustrative: the service could not be reached from the environment
  where the fixture was written.
