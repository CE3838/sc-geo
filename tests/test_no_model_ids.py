"""Reader fields and prompts name no model identifiers."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_ID = re.compile(r"claude-(opus|sonnet|haiku|fable)-\d|\b(opus|sonnet|haiku|fable) \d", re.I)


def test_prompts_and_extracted_data_name_no_model_ids():
    files = [*(ROOT / "extract" / "prompts").glob("*.md"), *(ROOT / "data" / "extracted").glob("*.json")]
    hits = [p.name for p in files if MODEL_ID.search(p.read_text(encoding="utf-8"))]
    assert not hits
