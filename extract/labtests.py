"""Normalizers and review checks for water tests and rock tests (schema sections water_tests, rock_tests).

The reading model records every parameter name, test type, value, qualifier and unit as printed.
Code adds a `normalized` form only where it is unambiguous, and flags names and test types
`inferred` (CLAUDE.md rule 2). Units are never filled in: a value whose units are printed
nowhere goes to the review queue (`missing_units`).
"""

from __future__ import annotations

import re

TESTS = ("water_tests", "rock_tests")
FIELDS = {"parameter", "test_type", "value", "qualifier"}

# --- water-test parameters -------------------------------------------------------
# (normalized name, category, pattern). Ordered so that compound names come before their parts.
# Chemical symbols match only as whole, case-sensitive tokens ("Ca", not "CaCO3" or "ca").
_I = re.IGNORECASE


def _w(pattern: str) -> re.Pattern:
    return re.compile(pattern, _I)


def _sym(symbol: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9]){symbol}(?![A-Za-z0-9])")


WATER_PARAMETERS: list[tuple[str, str, re.Pattern]] = [
    # field measurements
    ("pH", "field", re.compile(r"(?<![A-Za-z])pH(?![A-Za-z])")),
    ("specific conductance", "field", _w(r"specific\s+conduct(?:ance|ivity)")),
    ("temperature", "field", _w(r"\btemperature\b|\bwater\s+temp\b")),
    ("dissolved oxygen", "field", _w(r"dissolved\s+oxygen")),
    ("water level", "field", _w(r"depth\s+to\s+water|water\s+level")),
    ("turbidity", "field", _w(r"\bturbidity\b")),
    ("alkalinity", "field", _w(r"\balkalinity\b")),
    ("oxidation-reduction potential", "field", _w(r"oxidation[- ]reduction|\bredox\b|\bORP\b|\bEh\b")),
    ("dissolved solids", "major_ion", _w(r"dissolved\s+solids|\bTDS\b")),
    ("hardness", "major_ion", _w(r"\bhardness\b")),
    # major ions
    ("calcium", "major_ion", _w(r"\bcalcium\b")),
    ("magnesium", "major_ion", _w(r"\bmagnesium\b")),
    ("sodium", "major_ion", _w(r"\bsodium\b")),
    ("potassium", "major_ion", _w(r"\bpotassium\b")),
    ("bicarbonate", "major_ion", _w(r"\bbicarbonate\b")),
    ("carbonate", "major_ion", _w(r"(?<!bi)\bcarbonate\b")),
    ("chloride", "major_ion", _w(r"\bchloride\b")),
    ("sulfate", "major_ion", _w(r"\bsulfate\b|\bsulphate\b")),
    ("fluoride", "major_ion", _w(r"\bfluoride\b")),
    ("bromide", "major_ion", _w(r"\bbromide\b")),
    ("silica", "major_ion", _w(r"\bsilica\b")),
    ("calcium", "major_ion", _sym("Ca")),
    ("magnesium", "major_ion", _sym("Mg")),
    ("sodium", "major_ion", _sym("Na")),
    ("potassium", "major_ion", _sym("K")),
    ("chloride", "major_ion", _sym("Cl")),
    # nutrients
    ("nitrate plus nitrite", "nutrient", _w(r"nitr[ai]te\s*(?:plus|\+|and)\s*nitr[ai]te")),
    ("nitrate", "nutrient", _w(r"\bnitrate\b")),
    ("nitrite", "nutrient", _w(r"\bnitrite\b")),
    ("ammonia", "nutrient", _w(r"\bammoni(?:a|um)\b")),
    ("kjeldahl nitrogen", "nutrient", _w(r"\bkjeldahl\b")),
    ("orthophosphate", "nutrient", _w(r"\bortho-?phosphate\b")),
    ("phosphorus", "nutrient", _w(r"\bphosphorus\b")),
    ("total nitrogen", "nutrient", _w(r"\btotal\s+nitrogen\b")),
    # metals and trace elements
    ("ferrous iron", "metal_trace", _w(r"\bferrous\s+iron\b|\bFe\s*\(?II\)?|\bFe2\+")),
    ("iron", "metal_trace", _w(r"\biron\b")),
    ("iron", "metal_trace", _sym("Fe")),
    ("manganese", "metal_trace", _w(r"\bmanganese\b")),
    ("arsenic", "metal_trace", _w(r"\barsenic\b")),
    ("thallium", "metal_trace", _w(r"\bthallium\b")),
    ("lead", "metal_trace", _w(r"^\s*lead\b|\blead,\s*(?:dissolved|total)")),
    ("zinc", "metal_trace", _w(r"\bzinc\b")),
    ("copper", "metal_trace", _w(r"\bcopper\b")),
    ("cadmium", "metal_trace", _w(r"\bcadmium\b")),
    ("chromium", "metal_trace", _w(r"\bchromium\b")),
    ("mercury", "metal_trace", _w(r"\bmercury\b")),
    ("aluminum", "metal_trace", _w(r"\balumin(?:i)?um\b")),
    ("barium", "metal_trace", _w(r"\bbarium\b")),
    ("boron", "metal_trace", _w(r"\bboron\b")),
    ("strontium", "metal_trace", _w(r"\bstrontium\b(?!\s*-?\s*8[67])")),
    ("uranium", "metal_trace", _w(r"\buranium\b")),
    ("selenium", "metal_trace", _w(r"\bselenium\b")),
    ("sulfide", "metal_trace", _w(r"\bsulfide\b")),
    # organics
    ("MTBE", "organic", _w(r"\bMTBE\b|methyl[- ]tert[- ]?butyl[- ]ether")),
    ("benzene", "organic", _w(r"^\s*benzene\b")),
    ("toluene", "organic", _w(r"\btoluene\b")),
    ("ethylbenzene", "organic", _w(r"\bethylbenzene\b")),
    ("xylenes", "organic", _w(r"\bxylenes?\b")),
    ("naphthalene", "organic", _w(r"\bnaphthalene\b")),
    ("trichloroethene", "organic", _w(r"\btrichloroeth(?:yl)?ene\b|\bTCE\b")),
    ("tetrachloroethene", "organic", _w(r"\btetrachloroeth(?:yl)?ene\b|\bPCE\b")),
    ("cis-1,2-dichloroethene", "organic", _w(r"\bcis-1,2-dichloroeth(?:yl)?ene\b|\bcis-?DCE\b")),
    ("vinyl chloride", "organic", _w(r"\bvinyl\s+chloride\b")),
    ("ethylene dibromide", "organic", _w(r"\bethylene\s+dibromide\b|\bEDB\b")),
    ("dibromochloropropane", "organic", _w(r"\bdibromochloropropane\b|\bDBCP\b")),
    ("dissolved organic carbon", "organic", _w(r"dissolved\s+organic\s+carbon|\bDOC\b")),
    ("total organic carbon", "organic", _w(r"total\s+organic\s+carbon|\bTOC\b")),
    ("dissolved inorganic carbon", "major_ion", _w(r"dissolved\s+inorganic\s+carbon|\bDIC\b")),
    # pesticides
    ("deethylatrazine", "pesticide", _w(r"\bdeethylatrazine\b|\bdesethylatrazine\b")),
    ("atrazine", "pesticide", _w(r"(?<![a-z])atrazine\b")),
    ("alachlor", "pesticide", _w(r"(?<![a-z])alachlor\b")),
    ("metolachlor", "pesticide", _w(r"\bmetolachlor\b")),
    ("simazine", "pesticide", _w(r"\bsimazine\b")),
    ("prometon", "pesticide", _w(r"\bprometon\b")),
    ("cyanazine", "pesticide", _w(r"\bcyanazine\b")),
    ("metribuzin", "pesticide", _w(r"\bmetribuzin\b")),
    ("aldicarb", "pesticide", _w(r"\baldicarb\b")),
    ("carbaryl", "pesticide", _w(r"\bcarbaryl\b")),
    ("2,4-D", "pesticide", _w(r"(?<![\w,])2,4-D(?![A-Za-z])")),
    # isotopes, radionuclides and ages
    ("tritium", "isotope_age", _w(r"\btritium\b|(?<![A-Za-z])3H(?![A-Za-z0-9])")),
    ("carbon-14", "isotope_age", _w(r"\bcarbon[- ]?14\b|\b14C\b|\bradiocarbon\b")),
    ("delta oxygen-18", "isotope_age", _w(r"oxygen[- ]?18|\b18O\b|δ\s*18\s*O")),
    ("delta deuterium", "isotope_age", _w(r"\bdeuterium\b|δ\s*D\b|δ\s*2\s*H")),
    ("CFC-11", "isotope_age", _w(r"\bCFC[- ]?11\b")),
    ("CFC-12", "isotope_age", _w(r"\bCFC[- ]?12\b")),
    ("CFC-113", "isotope_age", _w(r"\bCFC[- ]?113\b")),
    ("sulfur hexafluoride", "isotope_age", _w(r"sulfur\s+hexafluoride|\bSF6\b")),
    ("radium-226", "isotope_age", _w(r"\bradium[- ]?226\b|\bRa[- ]?226\b")),
    ("radium-228", "isotope_age", _w(r"\bradium[- ]?228\b|\bRa[- ]?228\b")),
    ("radon-222", "isotope_age", _w(r"\bradon\b")),
    ("strontium-87/86", "isotope_age", _w(r"strontium\s*-?\s*8[67]|87Sr")),
    ("apparent age", "isotope_age", _w(r"^\s*(?:apparent\s+(?:groundwater\s+|ground-water\s+)?age|recharge\s+(?:date|year))")),
    # dissolved gases
    ("methane", "dissolved_gas", _w(r"\bmethane\b")),
    ("carbon dioxide", "dissolved_gas", _w(r"\bcarbon\s+dioxide\b|\bCO2\b")),
    ("argon", "dissolved_gas", _w(r"\bargon\b")),
    ("nitrogen gas", "dissolved_gas", _w(r"\bnitrogen\s+gas\b|\bN2\b")),
    # hydraulic tests
    ("transmissivity", "hydraulic", _w(r"\btransmissivity\b")),
    ("hydraulic conductivity", "hydraulic", _w(r"hydraulic\s+conductivity|\bKsat\b")),
    ("storativity", "hydraulic", _w(r"\bstorativity\b|storage\s+coefficient")),
    ("specific storage", "hydraulic", _w(r"specific\s+storage")),
    ("specific capacity", "hydraulic", _w(r"specific\s+capacity")),
    ("specific yield", "hydraulic", _w(r"specific\s+yield")),
    ("leakance", "hydraulic", _w(r"\bleakance\b")),
    ("drawdown", "hydraulic", _w(r"\bdrawdown\b")),
    ("pumping rate", "hydraulic", _w(r"pumping\s+rate|discharge\s+rate")),
]


def _classify(text: str, table: list[tuple[str, str, re.Pattern]]) -> tuple[str, str] | None:
    """(name, category) when exactly one entry of the table names the text, else None.

    The first matching entry wins; the matched words are taken out and the rest is tried again,
    so "Calcium and magnesium" (two parameters) gives None, while "Iron, dissolved (Fe)" is iron."""
    rest = text
    found: list[tuple[str, str]] = []
    for _ in range(4):
        hit = next(((n, c, m) for n, c, p in table for m in [p.search(rest)] if m), None)
        if not hit:
            break
        found.append((hit[0], hit[1]))
        rest = rest[:hit[2].start()] + "\x00" + rest[hit[2].end():]
    names = {n for n, _ in found}
    return found[0] if len(names) == 1 else None


def water_parameter(text) -> dict | None:
    """{"name", "category", "inferred": True} for a printed parameter name, or None when unsure."""
    s = str(text or "")
    if len(s.strip()) < 2 or s.strip().upper() == "DO":
        return None
    hit = _classify(s, WATER_PARAMETERS)
    return {"name": hit[0], "category": hit[1], "inferred": True} if hit else None


# --- rock-test types -----------------------------------------------------------------

ROCK_TESTS: list[tuple[str, str, re.Pattern]] = [
    ("triaxial", "", _w(r"\btriaxial\b")),
    ("ucs", "", _w(r"unconfined\s+compressi|uniaxial\s+compressi|\bUCS\b|\bqu\b|D\s?2938|^\s*compressive\s+strength")),
    ("point_load", "", _w(r"point[- ]load|\bIs\s*\(?50\)?|D\s?5731")),
    ("brazilian_tensile", "", _w(r"brazilian|splitting\s+tensile|indirect\s+tensile|tensile\s+strength|D\s?3967")),
    ("slake_durability", "", _w(r"\bslake\b|D\s?4644|\bId\s*2\b")),
    ("rqd", "", _w(r"\bRQD\b|rock\s+quality\s+designation")),
    ("core_recovery", "", _w(r"\brecovery\b|\bREC\b")),
    ("unit_weight", "", _w(r"unit\s+weight")),
    ("density", "", _w(r"\bdensity\b")),
    ("specific_gravity", "", _w(r"specific\s+gravity")),
    ("absorption", "", _w(r"\babsorption\b")),
    ("elastic_modulus", "", _w(r"\bmodulus\b|young'?s")),
    ("poisson_ratio", "", _w(r"poisson")),
]


def rock_test_type(text) -> dict | None:
    """{"type", "inferred": True} for a printed test name or standard, or None when unsure.

    ASTM D7012 alone covers both triaxial and unconfined tests, so it decides nothing by itself."""
    s = str(text or "")
    hit = _classify(s, ROCK_TESTS)
    return {"type": hit[0], "inferred": True} if hit else None


# Values that have no units: never sent to review for missing units.
DIMENSIONLESS = {("water_tests", "pH"), ("rock_tests", "poisson_ratio"), ("rock_tests", "specific_gravity")}


# --- values and qualifiers -------------------------------------------------------------

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+"
_SCI = re.compile(rf"([-−]?(?:{_NUM}))\s*(?:[x×X*]\s*10\s*\^?\s*([-−–+]?\s*\d+)|[eE]([-+]?\d+))")
_RANGE = re.compile(rf"({_NUM})\s*(?:-|–|to)\s*({_NUM})")
_ND = re.compile(r"(?i)^\s*(?:nd|n\.d\.|not\s+detected|bdl|below\s+(?:the\s+)?detection(?:\s+limit)?|<\s*mdl)\s*$")


def qualifier(text) -> str | None:
    """'<', '>', 'ND' or 'E' (estimated) for a printed qualifier, else None (the value as printed is kept)."""
    s = str(text or "").strip()
    if not s:
        return None
    if _ND.match(s):
        return "ND"
    low = s.lower()
    if low in ("<", "less than", "lt"):
        return "<"
    if low in (">", "greater than", "gt", "more than"):
        return ">"
    if low in ("e", "est", "est.", "estimated"):
        return "E"
    return None


def _f(s: str) -> float:
    return float(s.replace(",", "").replace("−", "-").replace(" ", ""))


def parse_value(x) -> dict | None:
    """{"number", "qualifier"} (or {"min", "max", "qualifier"} for a range) from a printed value; None if unread."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return {"number": float(x), "qualifier": None}
    s = str(x or "").strip()
    if not s:
        return None
    if _ND.match(s):
        return {"number": None, "qualifier": "ND"}
    q = None
    m = re.match(r"(?i)^(<|>|less\s+than|greater\s+than|more\s+than|E(?=\s*[\d.]))\s*", s)
    if m:
        q = {"e": "E"}.get(m.group(1).lower(), "<" if m.group(1) in ("<",) or m.group(1).lower().startswith("less")
                           else ">")
        s = s[m.end():]
    sci = _SCI.match(s)
    if sci:
        exp = sci.group(2) or sci.group(3)
        return {"number": _f(sci.group(1)) * 10 ** int(exp.replace("−", "-").replace("–", "-").replace(" ", "")),
                "qualifier": q}
    r = _RANGE.match(s)
    if r and not re.match(rf"^-", s):
        return {"min": _f(r.group(1)), "max": _f(r.group(2)), "qualifier": q}
    n = re.match(rf"^([-−]?(?:{_NUM}))(?![\d])", s)
    if n:
        return {"number": _f(n.group(1)), "qualifier": q}
    return None


_UNIT_AFTER_NUMBER = re.compile(r"\d\s*(%|°|µ|μ|(?![eExX]\s*[-+−]?\s*\d)(?!x\s*10)[A-Za-z][A-Za-z0-9/.²³]*)")


def value_has_units(x) -> bool:
    """True when a printed value carries its own units ("0.5 mg/L", "95%"); bare numbers do not."""
    if not isinstance(x, str):
        return False
    return bool(_UNIT_AFTER_NUMBER.search(x))


# --- the "|" for a digit OCR misread --------------------------------------------------

_PIPE = re.compile(r"\|(?=[\d.])|(?<=[\d.])\||(?:^|(?<=\s))\|\s*(?:to|-|–)\s*\d")


def pipe_digit(quote) -> bool:
    """True when a quote has a '|' where a digit belongs ("| to 6 feet", "0.|2"), not a table rule."""
    return bool(_PIPE.search(str(quote or "")))


# --- hooks used by extract/ingest.py ------------------------------------------------------

def normalized(section: str, field: str, x):
    """The normalized form of one test field, or None."""
    if field == "parameter" and section == "water_tests":
        return water_parameter(x)
    if field == "test_type" and section == "rock_tests":
        return rock_test_type(x)
    if field == "value":
        return parse_value(x)
    if field == "qualifier":
        return qualifier(x)
    return None


def _record_kind(section: str, record: dict) -> str | None:
    if section == "water_tests":
        p = record.get("parameter")
        n = water_parameter(p.get("value")) if isinstance(p, dict) else None
        return n and n["name"]
    t = record.get("test_type")
    n = rock_test_type(t.get("value")) if isinstance(t, dict) else None
    return n and n["type"]


def review(path: str, val: dict, record: dict | None) -> list[tuple[str, dict]]:
    """Review problems [(problem, extra)] for one stored value of a test section.

    - ocr_digit: the quote shows a '|' where a digit belongs; the reading must be checked.
    - missing_units (on the `value`): no units in a `units` field, the value's own "units", or the value text.
      Units are never guessed. pH, Poisson's ratio and specific gravity have none; a value
      reported as not detected needs none.
    - unclear_value (on the `value`): the printed value is not a number, a range or a qualifier."""
    out: list[tuple[str, dict]] = []
    if pipe_digit(val.get("quote")):
        out.append(("ocr_digit", {}))
    if record is None or not path.endswith(".value") or path.count(".") != 1:
        return out
    section = path.split("[", 1)[0]
    parsed = parse_value(val.get("value"))
    if parsed is None:
        out.append(("unclear_value", {}))
    units = record.get("units")
    has_units = (isinstance(units, dict) and str(units.get("value") or "").strip()) or val.get("units") \
        or value_has_units(val.get("value"))
    not_detected = parsed is not None and parsed.get("qualifier") == "ND" and parsed.get("number") is None
    if not has_units and not not_detected and (section, _record_kind(section, record)) not in DIMENSIONLESS:
        out.append(("missing_units", {}))
    return out
