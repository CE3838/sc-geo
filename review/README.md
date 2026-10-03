# review

Tools for human review of extracted values, especially those flagged
`inferred=True` or with low confidence.

## Files to review

- `data/review/queue.json` -- values from document extraction (`extract/ingest.py`)
  that need a person. Each item gives `source_id`, `path` (where the value sits
  in the model's result, e.g. `observations[2].intervals[1].bottom`), the
  `value`, cited `page` and `quote`, and the `problem`:
  - `quote_not_found`: the quote is not on the cited page (value not stored);
  - `wrong_page`: the quote is on `found_page` instead (value not stored);
  - `inexact_quote`: the quote matched only loosely on a page with a real text
    layer (value stored);
  - `verify_disagree` / `verify_unclear`: the second reading pass disagreed or
    could not tell (value stored with lower confidence; `verify` holds the
    second pass's value and note).
  Re-ingesting a document replaces its items.
- `data/review/needs_access.json` -- catalog records with no legal open full
  text (metadata only), for library or interlibrary access. Written by
  `harvest/pdfs.py`.
