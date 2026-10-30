"""web/about.html states the numbers the code uses; this keeps them from drifting.

Every number the page explains is wrapped in <span data-sync="key">value</span>.
The expected text for each key is computed here from the code and config, and the
page must hold exactly these keys, so a change in the code (or a typo on the
page) fails until the page is updated.
"""

import json
import re
from pathlib import Path

from extract import ingest
from merge import build, score
from model import stack, surfaces
from model.units import Lexicon

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "web" / "about.html"
SYNC = re.compile(r'<(\w+)[^>]*\bdata-sync="([^"]+)"[^>]*>(.*?)</\1>', re.S)

LEX = Lexicon([{"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"}])


def f2(v):
    return f"{v:.2f}"


def f3(v):
    return f"{v:.3f}"


def pct(v):
    return f"{round(v * 100)}%"


def scale(n):
    return f"1:{n:,}"


def page_values() -> dict[str, str]:
    html = PAGE.read_text(encoding="utf-8")
    out = {}
    for _, key, text in SYNC.findall(html):
        assert key not in out, f"data-sync key {key} appears twice"
        out[key] = re.sub(r"<[^>]+>", "", text).strip()
    return out


def worked_examples() -> dict[str, str]:
    """Example 1: a 1:24,000 map (mapper certain) of the Wando Formation; a second
    detailed map also calls it Wando over 60% of the polygon; SGMC (unnamed Pleistocene
    sediment) covers all of it. Example 2: SGMC alone, no Geolex match."""
    winner = {"source": "a", "scale": 24000, "year": 2015, "name": "Wando Formation", "age": "late Pleistocene",
              "identity_confidence": "certain"}
    other = {"source": "b", "scale": 24000, "year": 1990, "name": "Wando Formation", "age": "late Pleistocene"}
    sgmc = {"source": "usgs-sgmc", "scale": 500000, "year": 2017, "name": "Coastal plain sediments",
            "age": "Pleistocene"}
    c = score.confidence(winner, [(other, 0.6), (sgmc, 1.0)], LEX)
    a1, a2 = LEX.agreement(score._cmp(winner), score._cmp(other)), LEX.agreement(score._cmp(winner), score._cmp(sgmc))
    factor = 0.8 + 0.25 * c["agreement"]
    lone = {"source": "usgs-sgmc", "scale": 500000, "name": "Coastal plain sediments", "age": "Pleistocene",
            "identity_confidence": None}
    c2 = score.confidence(lone, [], LEX)
    assert c["research_support"] and not c2["research_support"]
    return {
        "ex1.base": f2(c["base"]), "ex1.a_other": f2(a1), "ex1.a_sgmc": f2(a2),
        "ex1.agreement": f3(c["agreement"]), "ex1.agree_pct": pct(c["agreement"]),
        "ex1.factor": f3(factor), "ex1.factor_card": f2(0.8 + 0.25 * c["agreement"]),
        "ex1.before": f3(c["base"] * factor), "ex1.value": f3(c["value"]), "ex1.card": f2(c["value"]),
        "ex1.sources": str(c["sources"]),
        "ex2.base": f3(c2["base"]), "ex2.value": f3(c2["value"]), "ex2.card": f2(c2["value"]),
    }


def expected() -> dict[str, str]:
    exp = {f"scale.{limit}": f2(w) for limit, w in score._SCALE_STEPS}
    exp |= {f"scale.{limit}.label": scale(limit) for limit, _ in score._SCALE_STEPS}
    exp["scale.unknown"] = f2(score.scale_weight(None))
    exp["scale.coarser"] = f2(score.scale_weight(score._SCALE_STEPS[-1][0] + 1))
    exp["scale.max_used"] = scale(build.MAX_SCALE)
    exp["scale.scgs_assumed"] = scale(build.SCGS_SCALE)
    exp |= {"identity.certain": f2(score.identity_weight("certain")),
            "identity.questionable": f2(score.identity_weight("questionable")),
            "identity.other": f2(score.identity_weight(None))}
    # The agreement factor 0.8 + 0.25 a, the lone-map factor and the Geolex bonus, read back from confidence().
    def lexicon(wando_age):
        return Lexicon([{"name": "Wando", "status": "current", "replaced_by": None, "age": wando_age},
                        {"name": "Penholoway", "status": "current", "replaced_by": None, "age": "Pleistocene"}])
    w = {"source": "a", "scale": 24000, "name": "Wando Formation", "age": "late Pleistocene",
         "identity_confidence": "certain"}
    other = lambda name: {"source": "b", "name": name, "age": "Pleistocene"}
    lex0 = lexicon("Eocene")  # the age conflicts with Geolex: no bonus
    v0 = score.confidence(w, [(other("Penholoway Formation"), 1.0)], lex0)["value"] / 0.95
    v1 = score.confidence(w, [(other("Wando Formation"), 1.0)], lex0)["value"] / 0.95
    lone = score.confidence(w, [], lex0)["value"] / 0.95
    exp |= {"agree.floor": f2(v0), "agree.slope": f2(v1 - v0), "agree.top": f2(v1), "agree.lone": f2(lone)}
    lex1 = lexicon("late Pleistocene")
    exp["geolex.bonus"] = f2(score.confidence(w, [], lex1)["value"] - score.confidence(w, [], lex0)["value"])
    named = lambda n: {"name": n, "age": "Pleistocene"}
    exp |= {"name.same": f2(lex1.agreement(named("Wando Formation"), named("Wando Formation"))),
            "name.different": f2(lex1.agreement(named("Wando Formation"), named("Penholoway Formation"))),
            "name.age_both_unnamed": f2(lex1.agreement(named("Unnamed deposits"), named("Undifferentiated sediments"))),
            "name.age_one_named": f2(lex1.agreement(named("Wando Formation"), named("Undifferentiated sediments"))),
            "name.min_share": pct(0.01)}
    exp |= worked_examples()

    c = ingest.CONFIG["confidence"]
    exp |= {"doc.agency": f2(c["agency_or_journal"]), "doc.other": f2(c["other_publisher"]), "doc.draft": f2(c["draft"]),
            "doc.ocr": f2(c["ocr_factor"]), "doc.fuzzy": f2(c["fuzzy_quote_factor"]),
            "doc.verify_agree": f2(c["verify_agree"]), "doc.verify_unchecked": f2(c["verify_unchecked"]),
            "doc.verify_unclear": f2(c["verify_unclear"]), "doc.verify_disagree": f2(c["verify_disagree"]),
            "doc.inferred": f2(c["inferred_factor"])}
    rec = {"publisher": ingest.CONFIG["trusted_publishers"][0]}
    exp["doc.ocr_quote"] = f2(ingest.confidence(rec, "pdf_text", "ocr", "agree", False) / c["agency_or_journal"])
    img = ingest.CONFIG["images"]["confidence"]
    exp |= {"image.max": f2(img["max"]), "image.factor": f2(img["factor"]), "image.unclear": f2(img["unclear_factor"])}
    ag = ingest.CONFIG["agreement"]
    exp |= {"agreement.distance": f"{ag['distance_ft']:,.0f} ft", "agreement.tolerance": f"{ag['tolerance_ft']:g} ft",
            "agreement.approx": f"{ag['approximate_extra_ft']:g} ft", "agreement.boost": f2(ag["boost"]),
            "agreement.cap": f2(ag["cap"])}

    d = surfaces.DEFAULTS
    exp |= {"surf.min_points": str(d["min_points_kriging"]), "surf.cv_margin": pct(d["cv_margin"]),
            "surf.min_std": f"{d['min_std_ft']:g} ft", "surf.max_distance_factor": f"{d['max_distance_factor']:g}",
            "surf.msse_low": f2(d["msse_bounds"][0]), "surf.msse_high": f"{d['msse_bounds'][1]:g}",
            "surf.idw_power": f"{d['idw_power']:g}", "surf.bins": str(d["bins"]),
            "stack.min_holes": str(stack.MIN_HOLES)}
    return exp


def test_about_page_numbers_match_the_code():
    got, want = page_values(), expected()
    missing = sorted(set(want) - set(got))
    unknown = sorted(set(got) - set(want) - WEB_KEYS)
    assert not missing, f"about.html lacks data-sync keys: {missing}"
    assert not unknown, f"about.html has data-sync keys no test checks: {unknown}"
    wrong = {k: (got[k], v) for k, v in want.items() if got[k] != v}
    assert not wrong, f"about.html (page, code): {wrong}"


# Keys checked by tests/web/about.test.mjs against web/card.js and web/merged.js.
WEB_KEYS = {"level.high", "level.medium", "color.low", "color.mid", "color.high"}


def test_web_keys_are_on_the_page():
    assert WEB_KEYS <= set(page_values())


def test_about_page_is_static_and_cites_no_warranty():
    html = PAGE.read_text(encoding="utf-8")
    assert "without warranty" in html
    assert not re.search(r"<script[^>]+src=", html), "the About page loads no scripts"
    assert not re.search(r'(?:src|href)="(?!https://|#|index\.html|about\.html|style\.css|about\.css)', html)
    assert "docs/interpolation.md" in html


def test_interpolation_notes_exist():
    assert (ROOT / "docs" / "interpolation.md").is_file()


def test_about_page_describes_the_current_surface_method():
    html = PAGE.read_text(encoding="utf-8")
    sec = html[html.index('<section id="surfaces">'):html.index('<section id="sources">')]
    assert "Trend kriging" in sec and "geologic age" in sec
    assert "r²" not in sec, "there is no variogram-fit (r²) rule any more"
    assert "min_r2" not in surfaces.DEFAULTS and "min_structure" not in surfaces.DEFAULTS
