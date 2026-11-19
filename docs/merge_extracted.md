# Merging extracted units and observations

The merged map (`python -m merge.build`) is built from GIS polygons only:
for every piece of ground the most detailed, then most recent, map wins, and
the other maps covering it are kept as alternatives (`merge/overlay.py`,
`merge/score.py`). Documents read by `extract/` add what GIS layers rarely
hold: unit descriptions in words (name, age, lithology, thickness, contacts,
environment, fossils) and point observations, each stored as a StoredValue
with its source, page, verbatim quote and confidence. This note describes how
those values join the merged layers, step by step.

## Step 1: link unit descriptions to polygons (`merge/extracted_units.py`)

Every extracted unit with a name becomes an entry carrying its document's
citation, scale, year and footprint (the catalog bounding box). Its fields are
copied as stored, so each keeps its own page, quote, confidence and `inferred`
flag; nothing is re-scored. A merged polygon is linked to an entry when the
entry's footprint touches the polygon and either

- the entry comes from the polygon's own map and its printed map symbol equals
  the polygon's map unit (the map's own explanation; the link is not an
  inference), or
- both unit names resolve to the same named unit through `model/units.py`
  (Geolex lexicon, abandoned names followed to their replacement). Such a link
  is an inference and is flagged `inferred: true`.

Informal units (names without a geographic name, such as "tidal marsh
deposits") match by symbol only, because the same words mean different things
on different maps. Links are ordered most detailed map first, then newest,
the same rule the overlay uses. Each polygon lists its links in `extracted`
(entry id, how it matched, inferred or not); the entries themselves are
written once to `merged-extracted.json`, so polygons of one unit do not repeat
the text. Linking changes no geometry, winning unit or confidence value.

## Later steps

- Show linked descriptions on the property card with their citations and
  pages, and include `merged-extracted.json` in the data package.
- Use agreement between a polygon's unit and the linked descriptions (age
  ranges, lithology) in the confidence score, and keep disagreeing
  descriptions as alternatives with citations.
- Place point observations (outcrops, borings, measured sections) on the
  merged layers and compare them with the unit mapped at that point.
- Units described in documents but not mapped in any GIS layer stay as
  entries without polygons until a map is digitized.

Open questions for review are listed with each step's pull request.
