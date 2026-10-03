# Scheduled reading session

These are the exact steps a scheduled Claude Code session follows to read the
next documents. This file is the prompt for the recurring Routine. The
session starts from a fresh clone with an empty `.cache`.

Follow CLAUDE.md. In particular: never commit PDFs, page text, packets or
raw results (everything under `.cache/` stays local); never print the
`CONTACT_EMAIL` secret; commit only `data/extracted/` and `data/review/`.

## 0. Set up

```sh
git checkout -b extract/$(date -u +%Y-%m-%d)
python -m pytest -q tests/test_extract_*.py      # tools work before you start
which pdftotext pdfinfo                          # poppler-utils is required
which ocrmypdf tesseract || true                 # OCR is optional; scanned pages are skipped without it
```

If `pdftotext` is missing, install poppler-utils (`sudo apt-get install -y
poppler-utils`); if apt is not available, stop and report it.

## 1. Pick the documents

```sh
python -m extract.next_batch --n 5 --max-tokens 250000
```

This prints, in priority order (Charleston County first), up to 5 pending
documents: the packet files to read and where to write each result. It
downloads PDFs and builds text and packets as needed, which can take a few
minutes. Documents with no open full text or only unreadable scans are
skipped and listed in the output.

## 2. Read each document

For each document, in order:

1. Read `extract/prompts/extract.md` (once per session) and `extract/schema.json`.
2. Read every packet file listed for the document, completely.
3. Write the result JSON to the `write:` path shown
   (`.cache/results/<id>.json`). For a document with several packets you may
   write one file per packet (`<id>.p1.json`, `<id>.p2.json`, ...), all with
   the same `source_id`.
4. Check it:

   ```sh
   python -c "import json,sys; from extract import schema; \
     errs = schema.validate(json.load(open(sys.argv[1]))); print('\n'.join(errs) or 'ok')" .cache/results/<id>.json
   ```

   Fix any schema errors.

## 3. Second pass (verify)

For each document:

```sh
python -m extract.ingest .cache/results/<id>.json --plan-verify > .cache/results/<id>.plan.json
```

Then follow `extract/prompts/verify.md`: re-read the cited pages for every
value in the plan, independently of your first reading, and write
`.cache/results/<id>.verify.json`.

## 4. Ingest

```sh
python -m extract.ingest .cache/results/<id>.json --verify .cache/results/<id>.verify.json
```

(List every part file if you wrote several.) Ingest refuses results that do
not match the schema; fix and rerun. It prints a summary: values, stored,
quote matches, values not found, review items. If more than a quarter of the
values were not found on their pages, re-read the packet: you probably
paraphrased instead of quoting, or cited the wrong page. Fix the result and
ingest again (re-ingesting replaces the earlier output for that document).

## 5. Test and commit

```sh
python -m pytest -q
git status --short          # only data/extracted/ and data/review/ may change
git add data/extracted data/review
git commit -m "Extract <n> documents: <ids>"
```

Never `git add` anything under `.cache/` or any `.pdf`, `.txt` or packet file.

## 6. Open a pull request

Push the branch and open a PR titled `Extracted values: <ids>`. In the body,
for each document give: the citation, pages read, values stored, values
verified (agree/disagree/unclear), values sent to review, and anything odd
(garbled OCR, skipped references). End the body with the attribution lines
your session instructions give.

## Budget

A packet is at most ~40k tokens. Stop starting new documents when the session
is close to its limits; an unfinished document simply stays pending and is
picked up next time (nothing is written to `data/` until ingest).
