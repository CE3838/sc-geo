"""Provenance for stored values.

Every stored value carries a source ID, page, extraction method, and
confidence, and is flagged when it was inferred (see CLAUDE.md). Values from
sources without pages (GIS datasets) use a `locator` such as a feature ID
instead of a page.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ExtractionMethod(str, Enum):
    MANUAL = "manual"
    PDF_TEXT = "pdf_text"
    OCR = "ocr"
    TABLE_PARSER = "table_parser"
    LLM = "llm"
    CAD_IMPORT = "cad_import"
    GIS_IMPORT = "gis_import"
    INFERENCE = "inference"


@dataclass(frozen=True)
class StoredValue:
    value: Any
    source_id: str
    page: int | None
    extraction_method: ExtractionMethod
    confidence: float
    inferred: bool = False
    locator: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("source_id is required")
        if self.page is None:
            if not isinstance(self.locator, str) or not self.locator.strip():
                raise ValueError("a value without a page needs a locator")
        elif isinstance(self.page, bool) or not isinstance(self.page, int) or self.page < 1:
            raise ValueError("page must be a positive integer")
        if not isinstance(self.extraction_method, ExtractionMethod):
            raise ValueError("extraction_method must be an ExtractionMethod")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("confidence must be between 0 and 1")
        if self.extraction_method is ExtractionMethod.INFERENCE and not self.inferred:
            raise ValueError("values from inference must be flagged inferred=True")

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "source_id": self.source_id,
            "page": self.page,
            "extraction_method": self.extraction_method.value,
            "confidence": self.confidence,
            "inferred": self.inferred,
            "locator": self.locator,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StoredValue:
        return cls(
            value=d["value"],
            source_id=d["source_id"],
            page=d["page"],
            extraction_method=ExtractionMethod(d["extraction_method"]),
            confidence=d["confidence"],
            inferred=d.get("inferred", False),
            locator=d.get("locator"),
        )
