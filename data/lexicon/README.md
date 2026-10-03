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
