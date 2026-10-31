"""Compact water-test tables: columns once, rows as arrays (see extract/README.md, "Compact water-test tables").

A very large water-test table (hundreds of samples by dozens of constituents) would need one full water_tests
entry, with a page and quote in every field, per cell. A result may instead give it as `water_test_tables`:
its column headers once (each an ordinary value with page and quote) and one row per printed table line, with
that line's page and verbatim quote and one cell per column. Ingest checks the header values like any other,
finds every row quote on its page and every cell inside its row quote, and stores

    {"compact": true, "source_id", "extraction_method": "llm", "kind", "source_table", "units",
     "columns": [{"field": "observation", "header": <stored value>},
                 {"field": "value", "parameter": <stored value, normalized>, "units": <stored value>}, ...],
     "row_fields": ["page", "quote", "quote_match", "text_method", "confidence", "cells"],
     "rows": [[page, quote, quote_match, text_method, confidence, [cell, ...]], ...]}

`expand(table, index)` turns it back into ordinary stored water tests, one per non-empty value cell, each field a
StoredValue dict citing the row's page and quote with locator "water_test_tables[i] row r column c", so every cell
stays traceable. Normalized forms are computed on expansion by the same code as for water_tests.
"""
from __future__ import annotations

from extract import labtests, patterns

SECTION = "water_test_tables"
ROW_FIELDS = ("page", "quote", "quote_match", "text_method", "confidence", "cells")
_LENGTHS = ("top", "bottom", "depth")


def _norm(field: str, x):
    if x is None:
        return None
    if field == "value":
        return labtests.parse_value(x)
    if field == "qualifier":
        return labtests.qualifier(x)
    if field == "date":
        return patterns.date(x)
    if field in _LENGTHS:
        return patterns.length_ft(x)
    return None


def store_tables(tables: list[dict], values: dict[str, dict], check_row, contains, queue, source_id: str
                 ) -> tuple[list[dict], int]:
    """Stored compact tables from a result's water_test_tables.

    values: stored header values by result path (from ingest's main loop); check_row(page, quote) ->
    (quote_match, text_method, confidence) or None after queueing why; contains(quote, cell) -> bool;
    queue(path, val, problem). Returns (tables, rows stored)."""
    out, n_rows = [], 0
    for i, t in enumerate(tables):
        base = f"{SECTION}[{i}]"
        cols = []
        for j, c in enumerate(t["columns"]):
            col = {"field": c["field"]}
            for k in ("header", "parameter", "units", "fraction", "method"):
                sv = values.get(f"{base}.columns[{j}].{k}")
                if sv is not None:
                    if k == "parameter":
                        norm = labtests.water_parameter(sv.get("value"))
                        sv = sv | ({"normalized": norm} if norm else {})
                    col[k] = sv
            cols.append(col)
        rows = []
        for r, row in enumerate(t["rows"]):
            path = f"{base}.rows[{r}]"
            got = check_row(path, row["page"], row["quote"])
            if got is None:
                continue
            match, method, conf = got
            cells = []
            for j, cell in enumerate(row["cells"]):
                if cell is not None and not contains(row["quote"], str(cell)):
                    queue(f"{path}.cells[{j}]", {"value": cell, "page": row["page"], "quote": row["quote"]},
                          "cell_not_in_row")
                    cell = None
                cells.append(cell)
            if labtests.pipe_digit(row["quote"]):
                queue(path, {"value": None, "page": row["page"], "quote": row["quote"]}, "ocr_digit")
            rows.append([row["page"], row["quote"], match, method, conf, cells])
        if not rows:
            continue
        stored = {"compact": True, "source_id": source_id, "extraction_method": "llm"}
        if t.get("kind"):
            stored["kind"] = t["kind"]
        for k in ("source_table", "units"):
            if values.get(f"{base}.{k}") is not None:
                stored[k] = values[f"{base}.{k}"]
        stored |= {"columns": cols, "row_fields": list(ROW_FIELDS), "rows": rows}
        for test, (r, j) in zip(*_expand_with_index(stored, i)):
            for problem, extra in labtests.review("water_tests[0].value", test["value"] | {"quote": ""}, test):
                if problem != "ocr_digit":
                    queue(f"{base}.rows[{r}].cells[{j}]", test["value"], problem, **extra)
        out.append(stored)
        n_rows += len(rows)
    return out, n_rows


def _cell_value(table: dict, index: int, r: int, j: int, field: str, row: list, cell) -> dict:
    page, quote, match, method, conf, _ = row
    sv = {"value": cell, "source_id": table["source_id"], "page": page, "extraction_method": table["extraction_method"],
          "confidence": conf, "inferred": False, "locator": f"{SECTION}[{index}] row {r + 1} column {j + 1}",
          "quote": quote, "quote_match": match, "text_method": method, "verification": None, "table": True}
    norm = _norm(field, cell)
    if norm not in (None, {}, []):
        sv["normalized"] = norm
    return sv


def _expand_with_index(table: dict, index: int) -> tuple[list[dict], list[tuple[int, int]]]:
    cols = table["columns"]
    tests, where = [], []
    for r, row in enumerate(table["rows"]):
        cells = row[5]
        common = {}
        for j, (c, cell) in enumerate(zip(cols, cells)):
            if c["field"] != "value" and cell is not None:
                common[c["field"]] = _cell_value(table, index, r, j, c["field"], row, cell)
        for j, (c, cell) in enumerate(zip(cols, cells)):
            if c["field"] != "value" or cell is None:
                continue
            test = {"kind": table.get("kind")} if table.get("kind") else {}
            test |= common
            test["parameter"] = c["parameter"]
            test["value"] = _cell_value(table, index, r, j, "value", row, cell)
            units = c.get("units") or table.get("units")
            if units:
                test["units"] = units
            for k in ("fraction", "method"):
                if c.get(k):
                    test[k] = c[k]
            if table.get("source_table"):
                test["source_table"] = table["source_table"]
            test["compact_row"] = {"table": index, "row": r + 1, "column": j + 1}
            tests.append(test)
            where.append((r, j))
    return tests, where


def expand(table: dict, index: int) -> list[dict]:
    """Ordinary stored water tests (one per non-empty value cell) from one stored compact table."""
    return _expand_with_index(table, index)[0]


def expand_doc(doc: dict) -> list[dict]:
    """Every water test held in a stored document's compact tables."""
    return [t for i, table in enumerate(doc.get(SECTION) or []) for t in expand(table, i)]
