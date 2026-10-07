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
which ocrmypdf tesseract || true                 # OCR: needed for scanned maps and reports
```

If `pdftotext` is missing, install poppler-utils (`sudo apt-get install -y
poppler-utils`); if apt is not available, stop and report it. Also install OCR
when you can (`sudo apt-get install -y tesseract-ocr ocrmypdf`): a document
with a scanned file (an NGMDB map sheet, a plate without a text layer) is held
back until it can be OCRed, because reading only its text part would mark it
done with the map missing. `next_batch` reports such documents as
`skip ... needs OCR`. SCGS quadrangle maps come as NGMDB browse images: each
sheet is about 1,400-2,000 tile downloads (roughly 12 minutes) plus a few
minutes of OCR, so `next_batch` can take a while on them. Values read from
them carry the image URL as their locator.

To pick specific documents, take them from `config/reading_list.json`
(online records ranked by South Carolina geologic relevance, Charleston County
first; `python -m extract.reading_list` rebuilds it, and
`config/reading_list_scores.json` gives each record's score and, for records
left out, the reason): `python -m extract.prep --todo` lists the
ones not yet read, and `python -m extract.next_batch --id <ID> --n 1` hands
out one of them. OCR can run ahead as a background job with no reading
(`python -m extract.prep --next 10`, one document at a time, resumable); it
prints `READY <id>` when a document's packets are built.

## 1. Pick the packets

```sh
python -m extract.next_batch --n 5 --max-tokens 250000
```

This hands out packets, not just whole documents. Documents an earlier
session started but did not finish come FIRST (marked `continue`), with only
their unread packets; then new documents in priority order (Charleston County
first). Packets are added until about 250k tokens. A long document may be
handed out only in part (`N left after this`); the rest comes next session.
It downloads, OCRs and builds packets as needed, which can take a few
minutes. Documents with no open full text, or scans that still need OCR, are
skipped and listed in the output.

Finish documents you start: work through the packets in the order printed,
and do not run `next_batch` again for new documents until every packet it gave
you is ingested.

Some catalog records are one chapter or note of a multi-paper volume whose
only PDF is the whole volume. `config/catalog_scope.json` lists their PDF
pages (plus any extra pages, such as their references), and their packets
hold only those pages; the packet header says `Scope: PDF pages ... only`.
Read and cite only those pages: other authors' papers in the same PDF are not
this record. `extract.ingest` refuses a result that cites a page outside the
scope. When a scope changes, `next_batch` rebuilds that record's packets.

## 2. Read each packet

For each packet, in order:

1. Read `extract/prompts/extract.md` (once per session) and `extract/schema.json`.
2. Read the packet file completely. Besides units, observations, structures,
   groundwater and references, record subsurface data where the packet has
   it: tops and bases of units (`surfaces`), structure-contour and isopach
   maps (`contours`) and cross sections (`sections`), with each datum as
   printed.
3. Write the result JSON to its `write:` path
   (`.cache/results/<id>.<packet>.json`), with `"packets": ["<packet>"]`.
4. Check it:

   ```sh
   python -c "import json,sys; from extract import schema; \
     errs = schema.validate(json.load(open(sys.argv[1]))); print('\n'.join(errs) or 'ok')" .cache/results/<id>.<packet>.json
   ```

   Fix any schema errors.

## 3. Second pass (verify)

For each packet result:

```sh
python -m extract.ingest .cache/results/<id>.<packet>.json --plan-verify > .cache/results/<id>.<packet>.plan.json
```

The plan holds every table value and every subsurface value, plus a sample
of the rest. Then follow `extract/prompts/verify.md`: re-read the cited pages
for every value in the plan, independently of your first reading, and write
`.cache/results/<id>.<packet>.verify.json`.

## 4. Ingest

```sh
python -m extract.ingest .cache/results/<id>.<packet>.json --verify .cache/results/<id>.<packet>.verify.json
```

Ingest each packet as soon as it is verified, so the work is saved even if
the session ends early. It merges the packet into `data/extracted/<id>.json`
(values from earlier packets are kept; exact duplicates are dropped), records
which packets are done (`blocks_done`), and sets `"complete": true` once every
packet of the document is in. It refuses results that do not match the
schema; fix and rerun. It prints a summary: values, stored, quote matches,
values not found, review items, and `complete`. If more than a quarter of the
values were not found on their pages, re-read the packet: you probably
paraphrased instead of quoting, or cited the wrong page. Fix the result and
ingest it again (re-ingesting a packet replaces that packet's values).

## 5. Test and commit

```sh
python -m pytest -q
git status --short          # only data/extracted/ and data/review/ may change
git add data/extracted data/review
git commit -m "Extract <ids> (<n> packets; <ids still in progress>)"
```

Never `git add` anything under `.cache/` or any `.pdf`, `.txt` or packet file.

## 6. Open a pull request

Push the branch and open a PR titled `Extracted values: <ids>`. In the body,
for each document give: the citation, packets read (and whether the document
is now complete or still in progress), values stored, values
verified (agree/disagree/unclear), values sent to review, and anything odd
(garbled OCR, skipped references). End the body with the attribution lines
your session instructions give.

## Budget

A packet is at most ~40k tokens. Stop taking new packets when the session is
close to its limits. Packets already ingested are saved in
`data/extracted/<id>.json` (with `"complete": false`) and the next session
continues the document from the first unread packet; a packet read but not
ingested is simply read again next time.
