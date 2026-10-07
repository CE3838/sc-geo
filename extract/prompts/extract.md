# Extraction instructions for the reading model

You are reading one South Carolina geology document (a geologic map, report,
or paper) and recording what it says as JSON. Our code checks every quote you
give against the page text, normalizes units, and computes confidence. Your job
is only to read carefully and report faithfully.

## Input

One or more packet files from `.cache/packets/<id>/packet-NN.md`. Each starts
with the catalog record (catalog id, citation, year, scale, publisher) and then
the document's pages, each headed:

    === PAGE 12 (pdf_text) ===
    === PAGE 3 (ocr) ===
    === PAGE 7 (pdf_text, part 2 of 3) ===

`pdf_text` pages come from the PDF's text layer; `ocr` pages were read by OCR
and may contain character errors (rn/m, 0/O, 1/l). Text was extracted with
layout preserved, so tables keep their columns, but two-column prose can appear
side by side on the same line; read each column in turn.

## Output

Write ONE JSON file per packet, at the `write:` path `next_batch` printed for
it (`.cache/results/<id>.<packet>.json`), listing that packet in `packets`.
Long documents are read packet by packet, possibly over several sessions;
our code merges the packet results into one record for the document and
marks it done when every packet has been ingested. So:

- Record what the pages of YOUR packet say. Do not try to recall or repeat
  values from other packets (a value that appears again in your packet, such
  as a unit described on both sides of a packet boundary, may be recorded;
  exact duplicates are dropped automatically).
- A unit, boring or table that continues from the previous packet: record the
  part on your pages and say in `notes` that it continues.
- A page split into parts (`part 2 of 3`) is still cited by its page number.

Each file matches `extract/schema.json`:

```json
{
  "schema_version": 1,
  "source_id": "<catalog id from the packet header>",
  "packets": ["packet-01"],
  "reader": "Claude, scheduled Claude Code session <date>",
  "notes": "optional remarks for a reviewer",
  "units": [], "observations": [], "structures": [], "groundwater": [], "references": [],
  "surfaces": [], "contours": [], "sections": []
}
```

`surfaces`, `contours` and `sections` are optional; leave them out when the
packet has none.

Every value is an object:

```json
{"value": "as much as 30 ft", "page": 12, "quote": "as much as 30 ft thick", "inferred": false}
```

- `value`: what the source says, in its own words and units. Keep numbers as
  written ("10-15 ft", "N45E, 30SE", "2.5Y 4/3", "N=23"). Do not convert units.
  Use a JSON number only when the source gives a bare number (then put the units
  in `"units"` if a table header states them).
- `page`: the number from the `=== PAGE n ===` line where the quote appears.
- `quote`: a SHORT verbatim excerpt from that page (ideally 3-25 words, at most
  400 characters) that contains or directly supports the value. Copy it exactly,
  including odd spelling or OCR errors; do not fix, abbreviate, or paraphrase.
  Never splice text from two places with "..." -- give the single closest
  excerpt. A quote that cannot be found on the cited page is thrown out.
- `inferred`: `true` when you reasoned the value out instead of reading it
  directly (for example: the rank "Formation" taken from a unit name, an age
  assigned from the unit's position in a correlation chart, a well's kind
  guessed from context). Otherwise `false`.
- Optional: `"table": true` when read from a table, log, column or legend
  box; `"units"` when the measurement units are given separately;
  `"note"` for a brief remark.

If the source does not give a field, leave it out or write `"not stated"`.
Never guess to fill a field.

## What to extract

**units** -- every named or map unit described: `map_symbol`, `name` (exactly
as the source writes it, e.g. "Wando Formation", "Ten Mile Hill beds", "Qhs";
do not substitute a modern or Geolex name), `rank` (Formation, Member, Group,
beds, informal unit...), `group`, `age` (as stated, e.g. "late Pleistocene"),
`description`, `lithology` (the main rock/sediment types), `thickness`,
`contacts` (upper/lower contact relations), `depositional_environment`,
`fossils`.

**observations** -- borings, wells, outcrops, auger holes, cores, test pits,
CPT soundings. `kind` (one of boring, well, outcrop, auger_hole, core,
test_pit, cpt, other -- this is a plain string, not a value object), `label`
(the source's identifier), `location` EXACTLY as stated (coordinates, State
Plane values, a road intersection, "0.5 mi N of Ladson" -- never compute or
look up coordinates; if no location is given, leave it out), `elevation`,
`datum` (the vertical datum of that elevation exactly as printed: "NGVD 29",
"mean sea level"...), `depth_reference` ("land surface" when interval tops and
bottoms are depths below land surface, "elevation" when they are elevations;
quote the log header that says so, or flag it `inferred`), `total_depth`,
`date`, `water_level`, `water_level_date`, and `intervals`:
each with `top` and `bottom` depth (with units as stated), `unit` (stratigraphic
unit named for that interval), `description`, `uscs`, `munsell`, `spt_n`,
`liquid_limit`, `plasticity_index`, `moisture_content`. One interval per
row/layer in the log; do not merge layers.

**structures** -- faults, folds, joints, bedding and foliation measurements,
lineaments. `kind`, `name`, `fault_type` (normal, reverse, thrust,
strike-slip...), `sense` (of movement), `certainty` (as the source says:
"inferred", "concealed", "approximately located", "queried"), `strike_dip`
(as written), `location`, `age`, `description`.

**groundwater** -- aquifers and confining units: `aquifer` (name), `role`
("aquifer", "confining unit", "aquitard"...), `unit` (stratigraphic unit it is
in), `head` (water level/potentiometric head with units and datum as stated),
`location`, `date`, `transmissivity`, `hydraulic_conductivity`, `description`.

**surfaces** -- one entry per elevation or depth of a geologic surface at one
place, for later cross sections: the top or base of a unit in a well table, a
"top of the Cooper Marl is at -62 ft" sentence, a point read off a
structure-contour map. `surface` (as printed, e.g. "top of Cooper Marl"),
`unit`, `boundary` ("top" or "base"), `elevation` (relative to a datum; keep
the sign as printed, e.g. -62 with `"units": "ft"`, or "120 ft below sea
level") or `depth` (below land surface), `datum` exactly as printed (our code
maps it to NGVD29, NAVD88, MSL, land surface or unknown; never convert
between datums), `location` as printed, `observation` (the `label` of a
boring or well in this result when the value belongs to one), and `method`:
"measured" (in a boring, well or outcrop), "contour" (read from a contour
map), "interpolated" (between points, by the source) or "stated" (given in
text without saying how). A unit's thickness is NOT a surface: "the Ashley
is 40 ft thick" goes in the unit's `thickness`; "the base of the Ashley is
at -110 ft in CHN-14" is a surface. A depth to a unit in a log row is an
interval `top`; record a surface as well only when the source names it as
the top or base of a unit.

**contours** -- each structure-contour or isopach map: `kind` ("structure"
for elevations of a surface, "isopach" for thickness; a plain string like an
observation's kind), `surface`, `unit`, `interval` (contour interval as
printed), `datum`, `units`, `area` (as printed), `values` (a list of
contour labels you can read, each its own value with its page and quote --
only labels that are legible in the text; skip the rest), and `figure`
(figure or plate id).

**sections** -- each published cross section: `name` (e.g. "A-A'"),
`figure`, `start` and `end` (each with `location` as printed and, only if
the source prints them, `coordinates`), `vertical_exaggeration`, `datum`,
`length`, `observations` (a list of the labels of borings and wells shown on
it, each its own value), and `units_along`: one entry per unit where the
section's text or labels are legible, with `unit`, `from_distance`,
`to_distance` (along the section, as printed), `top_elevation` and
`base_elevation`.

Map and section faces are OCRed as scattered text. A value that depends on
reading the layout (which label belongs to which contour line, which unit
lies between two distances, which well a number sits beside) is `inferred`.
Record contour labels and section units only where they are legible; never
estimate an elevation between contours, and never compute coordinates from a
map's grid or a place name.

**references** -- each reference cited, one `citation` value per entry with
the page of the reference list. For long reference lists, include references
relevant to South Carolina geology; you may skip general references. Say in
`notes` if you skipped any.

## Rules

1. Only report what this document says. Do not add knowledge from elsewhere.
2. Quote every value; flag every inference.
3. Never invent coordinates, depths, elevations or names. Never convert units
   or datums; record each datum exactly as printed.
4. Keep the source's own unit names and spelling.
5. A value repeated on several pages: record it once, from the most specific
   place (description of map units, a log, a table), unless the pages disagree --
   then record each with its own page and say so in `notes`.
6. Skip what you cannot read (garbled OCR); say so in `notes`.
7. Do not assign confidence; our code does.
8. Prefer fewer, correct values over many doubtful ones.

When done, check that the file parses as JSON and that every `page` is a
page you saw in the packet.
