import pytest

from model.provenance import ExtractionMethod, StoredValue


def make(**overrides):
    fields = dict(
        value=42.0,
        source_id="scdnr-ofr-123",
        page=7,
        extraction_method=ExtractionMethod.PDF_TEXT,
        confidence=0.9,
    )
    fields.update(overrides)
    return StoredValue(**fields)


def test_valid_value_defaults_to_not_inferred():
    v = make()
    assert v.inferred is False
    assert v.to_dict() == {
        "value": 42.0,
        "source_id": "scdnr-ofr-123",
        "page": 7,
        "extraction_method": "pdf_text",
        "confidence": 0.9,
        "inferred": False,
        "locator": None,
    }


@pytest.mark.parametrize("source_id", ["", "   ", None])
def test_source_id_required(source_id):
    with pytest.raises(ValueError):
        make(source_id=source_id)


@pytest.mark.parametrize("page", [0, -1, 1.5, None, "3", True])
def test_page_must_be_positive_int(page):
    with pytest.raises(ValueError):
        make(page=page)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, None, "0.5"])
def test_confidence_between_zero_and_one(confidence):
    with pytest.raises(ValueError):
        make(confidence=confidence)


def test_extraction_method_must_be_enum():
    with pytest.raises(ValueError):
        make(extraction_method="guess")


def test_inference_method_requires_inferred_flag():
    with pytest.raises(ValueError):
        make(extraction_method=ExtractionMethod.INFERENCE)
    v = make(extraction_method=ExtractionMethod.INFERENCE, inferred=True)
    assert v.inferred is True


def test_round_trip():
    v = make(inferred=True, extraction_method=ExtractionMethod.LLM)
    assert StoredValue.from_dict(v.to_dict()) == v


def test_gis_values_use_a_locator_instead_of_a_page():
    v = make(page=None, locator="OBJECTID=12", extraction_method=ExtractionMethod.GIS_IMPORT)
    assert v.to_dict()["page"] is None
    assert v.to_dict()["locator"] == "OBJECTID=12"
    assert StoredValue.from_dict(v.to_dict()) == v


@pytest.mark.parametrize("locator", [None, "", "  "])
def test_missing_page_needs_a_locator(locator):
    with pytest.raises(ValueError):
        make(page=None, locator=locator)
