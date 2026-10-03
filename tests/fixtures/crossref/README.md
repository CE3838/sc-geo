# Crossref / Unpaywall / OpenAlex fixtures

Captured from the live APIs on 2026-10-03 (selected fields only):

- `crossref_match.json`: query for Weems and Lewis (2002), GSA Bulletin (ngmdb:58683).
- `crossref_nomatch.json`: query for the SCGS Rockville quadrangle map (ngmdb:100343); SCGS maps are not in
  Crossref, and the nearest hits are other quadrangles.
- `crossref_geology1989.json`: query for Rhea (1989), Geology (ngmdb:63397).
- `openalex_closed.json`, `openalex_usgs.json`: OpenAlex works for a closed GSA article and an open USGS report.

Constructed from the captured ones (the live APIs could not produce these cases here):

- `crossref_ambiguous.json`: the 2002 match plus a second record with the same title, authors and year but
  another DOI.
- `crossref_cc_by.json`: a record with a CC-BY license and a PDF link.
- `unpaywall_oa.json`, `unpaywall_closed.json`: Unpaywall v2 responses (Unpaywall needs a real contact email,
  which is not set in this environment).
