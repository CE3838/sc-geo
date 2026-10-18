"""Unlabelled SC State Plane locations: NAD83 assumed only for sources published after 1990,
kept only inside the document's catalog bbox, with a capped confidence and a note."""

from extract import ingest, renormalize
from model import coords
from model.units import Lexicon

SP = "Northing 405146.969, Easting 2325576.500"  # about 32.9423, -79.9387 (North Charleston)
INSIDE = [-79.9414, 32.9408, -79.9361, 32.9439]
FAR = [-82.5, 34.5, -82.3, 34.7]


def stored(value, confidence=0.85):
    return {"value": value, "source_id": "ngmdb:1", "page": 4, "extraction_method": "llm",
            "confidence": confidence, "inferred": False, "locator": None, "quote": value}


def derive(value, year, bbox, confidence=0.85):
    return ingest.derive_coordinates("observations[0].location", {"value": value}, stored(value, confidence),
                                     context={"year": year, "bbox": bbox})


def test_post_1990_inside_bbox_converted_inferred_capped_with_note():
    d, why = derive(SP, 2009, INSIDE)
    assert why is None
    assert d["inferred"] is True and d["extraction_method"] == "inference"
    assert d["datum"] == "NAD83" and d["datum_assumed"] is True and d["approximate"] is True
    assert d["note"] == coords.ASSUMED_NAD83_NOTE
    assert coords.ASSUMED_NAD83_NOTE in d["assumptions"]
    printed, _ = derive(SP + " NAD83", 2009, INSIDE)
    assert d["confidence"] < printed["confidence"]
    assert d["confidence"] <= ingest.ASSUMED_DATUM_CAP
    hi, _ = derive(SP, 2009, INSIDE, confidence=1.0)
    assert hi["confidence"] == ingest.ASSUMED_DATUM_CAP
    assert abs(d["value"]["lat"] - printed["value"]["lat"]) < 1e-9
    assert d["source_id"] == "ngmdb:1" and d["page"] == 4


def test_margin_allows_points_just_outside_bbox():
    lat, lon = coords.parse(SP + " NAD83")["lat"], coords.parse(SP + " NAD83")["lon"]
    near = [lon + 0.01, lat + 0.01, lon + 0.2, lat + 0.2]  # point is 0.01 deg outside
    d, why = derive(SP, 2009, near)
    assert d is not None and why is None


def test_post_1990_outside_bbox_blank_with_reason():
    d, why = derive(SP, 2009, FAR)
    assert d is None and "outside" in why and "bbox" in why


def test_post_1990_without_bbox_blank_with_reason():
    d, why = derive(SP, 2009, None)
    assert d is None and "bbox" in why


def test_1990_or_earlier_or_no_year_blank():
    for year in (1990, 1985, None):
        d, why = derive(SP, year, INSIDE)
        assert d is None and "datum not printed" in why


def test_printed_datum_behaviour_unchanged():
    for year in (1960, 2009, None):
        d, why = derive(SP + " NAD83", year, FAR)
        assert why is None and d["datum"] == "NAD83" and "datum_assumed" not in d
        assert d["confidence"] == round(0.85 * ingest.CONFIG["confidence"]["inferred_factor"], 3)
        assert "note" not in d
    old = ingest.derived_coordinates("observations[0].location", {"value": SP + " NAD83"}, stored(SP))
    new, _ = derive(SP + " NAD83", 2009, INSIDE)
    assert old == new
    # without context (old callers) the unlabelled case stays blank
    assert ingest.derived_coordinates("observations[0].location", {"value": SP}, stored(SP)) is None


def test_renormalize_uses_catalog_year_and_bbox():
    doc = {"source_id": "ngmdb:1", "year": 2009, "observations": [{"location": stored(SP)}]}
    new, changes = renormalize.renormalize_doc(doc, Lexicon([]), catalog_rec={"year": 2009, "bbox": INSIDE})
    loc = new["observations"][0]["location"]
    assert loc["derived_coordinates"]["note"] == coords.ASSUMED_NAD83_NOTE
    assert loc["value"] == SP and loc["confidence"] == 0.85  # the reading is untouched
    new, _ = renormalize.renormalize_doc(doc, Lexicon([]), catalog_rec={"year": 2009, "bbox": FAR})
    loc = new["observations"][0]["location"]
    assert "derived_coordinates" not in loc and "outside" in loc["coordinates_not_derived"]
    doc_old = dict(doc, year=1985)
    new, _ = renormalize.renormalize_doc(doc_old, Lexicon([]), catalog_rec={"year": 1985, "bbox": INSIDE})
    assert "derived_coordinates" not in new["observations"][0]["location"]
    again, changes = renormalize.renormalize_doc(new, Lexicon([]), catalog_rec={"year": 1985, "bbox": INSIDE})
    assert changes == []  # idempotent
