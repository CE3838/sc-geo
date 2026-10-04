# config

Settings shared by jobs and the viewer. `pilot_area.json` defines the pilot
area (Charleston County). Secrets such as `CONTACT_EMAIL` come from the
environment, never from files here.

`parcel_registry.json` lists every South Carolina county's public parcel
service (ArcGIS REST layer URL, the tax map / parcel ID field, optional
acreage and address fields, a link to the county's public record, terms,
CORS and a status: ok, no public service, blocked or needs check). The
viewer queries these services live for the area on screen; parcel data is
never copied into this repo. `python -m harvest.parcel_registry` re-checks
each entry and writes the viewer's copy, `web/data/parcel_registry.json`
(do not edit that copy by hand).

`catalog_scope.json` limits catalog records that are one chapter or note of a
multi-paper volume (whose PDF is the whole volume) to their own PDF pages;
see `extract/scope.py`.
