"""Compact water-test tables (result section water_test_tables): columns once, rows as arrays, through ingest."""

import copy

from extract import compact, schema
from tests.test_extract_ingest_tests import RESULT, SID, env, v  # noqa: F401  (env is a fixture)

TABLE = {
    "compact": True,
    "kind": "well",
    "source_table": v("Table 3", 2, "Table 3. Concentrations of major ions"),
    "units": v("milligrams per liter", 2, "in milligrams per liter"),
    "columns": [
        {"field": "observation", "header": v("Well", 2, "Well      Calcium")},
        {"field": "value", "parameter": v("Calcium", 2, "Well      Calcium")},
        {"field": "value", "parameter": v("Chloride", 2, "Calcium   Chloride")},
        {"field": "value", "parameter": v("Nitrate", 2, "Chloride   Nitrate")},
    ],
    "rows": [
        {"page": 2, "quote": "DOR-120   12.5      <0.5       ND", "cells": ["DOR-120", "12.5", "<0.5", "ND"]},
        {"page": 2, "quote": "DOR-999   1.0", "cells": ["DOR-999", "1.0", None, None]},          # not on the page
        {"page": 2, "quote": "DOR-120   12.5", "cells": ["DOR-120", "13.5", None, None]},       # cell not in row
    ],
}


def result_with_table():
    res = {k: (copy.deepcopy(x) if k not in ("water_tests", "rock_tests") else []) for k, x in RESULT.items()}
    res["water_test_tables"] = [copy.deepcopy(TABLE)]
    return res


def test_compact_table_validates_and_bad_ones_do_not():
    assert schema.validate(result_with_table()) == []
    bad = result_with_table()
    bad["water_test_tables"][0]["columns"][1] = {"field": "value"}           # a value column needs its parameter
    assert any("parameter" in e for e in schema.validate(bad))
    bad = result_with_table()
    bad["water_test_tables"][0]["rows"][0]["page"] = 0
    assert schema.validate(bad)
    bad = result_with_table()
    bad["water_test_tables"][0]["columns"][0] = {"field": "colour"}
    assert schema.validate(bad)


def test_ingest_stores_columns_once_and_rows_as_arrays(env):
    summary, out, queue = env(result_with_table())
    [t] = out["water_test_tables"]
    assert t["compact"] is True and t["source_id"] == SID and t["extraction_method"] == "llm"
    assert t["row_fields"] == list(compact.ROW_FIELDS)
    # headers are ordinary stored values with page, quote and confidence
    p = t["columns"][2]["parameter"]
    assert p["value"] == "Chloride" and p["page"] == 2 and p["quote_match"] == "exact" and 0 < p["confidence"] <= 1
    assert p["normalized"]["name"] == "chloride" and p["normalized"]["inferred"] is True
    assert t["units"]["value"] == "milligrams per liter"
    # the row whose quote is not on the page is dropped and queued; the row with a cell not in its quote keeps
    # only the cells that are
    assert len(t["rows"]) == 2
    page, quote, match, method, conf, cells = t["rows"][0]
    assert (page, quote, match, method) == (2, "DOR-120   12.5      <0.5       ND", "exact", "pdf_text")
    assert cells == ["DOR-120", "12.5", "<0.5", "ND"] and 0 < conf <= 1
    assert t["rows"][1][5] == ["DOR-120", None, None, None]
    probs = {(i["path"], i["problem"]) for i in queue}
    assert ("water_test_tables[0].rows[1]", "quote_not_found") in probs
    assert ("water_test_tables[0].rows[2].cells[1]", "cell_not_in_row") in probs
    assert summary["compact_rows"] == 2


def test_expand_gives_one_cited_test_per_cell(env):
    _, out, _ = env(result_with_table())
    tests = compact.expand_doc(out)
    assert len(tests) == 3                                         # Calcium, Chloride, Nitrate of DOR-120
    ca, cl, no3 = tests
    assert ca["observation"]["value"] == "DOR-120" and ca["kind"] == "well"
    assert ca["parameter"]["value"] == "Calcium" and ca["units"]["value"] == "milligrams per liter"
    val = cl["value"]
    assert val["value"] == "<0.5" and val["page"] == 2 and val["quote"] == "DOR-120   12.5      <0.5       ND"
    assert val["source_id"] == SID and val["extraction_method"] == "llm" and val["inferred"] is False
    assert val["locator"] == "water_test_tables[0] row 1 column 3"
    assert val["normalized"] == {"number": 0.5, "qualifier": "<"}
    assert no3["value"]["normalized"]["qualifier"] == "ND"
    assert cl["source_table"]["value"] == "Table 3"


def test_reingest_replaces_the_table_without_duplicates(env):
    env(result_with_table())
    _, out, _ = env(result_with_table())
    assert len(out["water_test_tables"]) == 1


def test_documents_without_compact_tables_expand_to_nothing():
    assert compact.expand_doc({"source_id": SID, "water_tests": []}) == []
