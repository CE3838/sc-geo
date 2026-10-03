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
- `usgs-*.json`: real USGS Water Data OGC API responses
  (https://api.waterdata.usgs.gov/ogcapi/v1, captured 2026-10-03 with curl;
  public domain, U.S. Geological Survey), trimmed to stay small:
  - `usgs-latest-page.json`: `latest-continuous` for a Charleston harbor
    bbox with `limit=3`, untrimmed, so it carries a real `next` paging link.
  - `usgs-latest-continuous.json`: the `latest-continuous` query built by
    `web/usgs-water.js` for South Carolina's bbox, keeping the features of
    seven stations (Congaree River at Columbia, Cooper River at Mobay,
    Lake Murray, wells CTF-324 and BRK-431 (null value, `EQUIP`), Cooper
    River at Filbin Creek (`MAINT`)) plus one Alaska gage with `ICE` from
    the national query.
  - `usgs-monitoring-locations.json`: `monitoring-locations` for those ids.
  - `usgs-continuous-02169500.json`, `usgs-continuous-well-72019.json`:
    7 days of gage height (Congaree at Columbia) and depth to water
    (well CTF-324), every 24th point, geometry removed.
  - `usgs-daily-02169500.json`: the first 12 daily means of a 1-year
    `daily` query, in the (unsorted) order served, geometry removed.
