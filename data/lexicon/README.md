# Geologic unit lexicon

`geolex_sc.json` holds the 184 geologic unit names that the USGS Geolex
lexicon records for South Carolina, built by `python -m harvest.geolex`:
usage, status (`current` or `abandoned`), replacement name, geologic age,
subunits, type locality and the literature it cites.

`age_range_ma` converts the age text to millions of years using the
International Chronostratigraphic Chart (v2023/09); it is derived, so it is
flagged `age_range_inferred: true`. `model.units.Lexicon` uses this file to
recognize the same unit on different maps (for example an abandoned name and
its replacement).

`scgs_aiken_key.json` is the South Carolina Geological Survey's informal
attribute key for its Aiken-area 1:24,000 GIS data (map label to unit name),
read from `Sum_Output.xlsx` on the SCGS digital-data page. The merge
(`merge/scgs.py`) uses it to name units in the SCGS FTP shapefiles whose
attribute tables carry only a label. Each row keeps its spreadsheet row as
its locator.
