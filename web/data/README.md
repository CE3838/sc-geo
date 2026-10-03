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
