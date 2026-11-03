"""Unit-top surfaces kept in geologic-age order, so they never cross.

`stack(tops, lexicon)` takes surfaces of the tops of several units, each built
on its own by `model.surfaces.build()`, and returns a `Stack` whose
`estimate(x, y)` gives every unit's top at that place with the order enforced.

Order. Each unit's age is its Geolex entry (`data/lexicon/geolex_sc.json`)
read with `model.units.finest_age_range` (an inferred value citing the entry);
`ages={unit: age text}` overrides it. A unit is younger than another when its
whole age range is at or above the other's (the ranges do not overlap), and
then its top must lie at or above the other's top. Units whose ranges
overlap (two members of the same age) are ordered by superposition, the
logged holes (`superposition`, hole counts {(upper, lower): n} such as
`model.surface_methods.unit_order`): A above B only when `min_holes` or more
holes log A over B and none log B over A; otherwise the pair stays unordered
and is reported with the reason. Units with no known age are not reordered
at all and are reported. Each constraint keeps its basis ("age" or
"superposition, N holes"), and every adjusted value says which it was moved
by (`order_basis`). When `superposition` (hole counts {(upper, lower): n}, such as
`model.surface_methods.unit_order`) logs the older unit above the younger in
`min_holes` or more holes, more often than the other way, the age order is in
doubt: that pair is not enforced and is reported as a conflict.

Enforcement. Where the surfaces violate the order at a place, their values
there are moved the least possible, weighted by inverse variance, to satisfy
every constraint at once (a weighted least-squares projection onto the
ordering constraints, Dykstra's algorithm). For two units that cross, both
move to their inverse-variance weighted mean: zero thickness there, and the
less certain surface moves more. A reference surface plus non-negative
thickness surfaces (isochores) would be preferable, but it needs each unit's
thickness, and its absence, logged in the same holes; the logged tops do not
record where a unit is missing, so the projection is used.

Uncertainty. A reconciled value is not better known than the surfaces it was
reconciled with: its ± is the largest uncertainty among the units it was
pinned to (those it ends level with through active constraints), and never
less than its own. The values and uncertainties before stacking are kept.

Every estimate is an inference (CLAUDE.md rule 2); a moved one carries
`adjusted`, `moved_ft` and an `adjustment_reason`.
"""

from __future__ import annotations

from model import units

METHOD = ("tops ordered by geologic age (younger above older), units of overlapping age by superposition in "
          "the logged holes; where they cross, moved by the "
          "inverse-variance weighted least-squares projection onto the order (Dykstra's algorithm)")
UNCERTAINTY = ("an adjusted value takes the largest uncertainty of the units it was reconciled with, never less "
               "than its own; values and uncertainties before stacking are kept")
MIN_HOLES = 3   # logged holes needed to order same-age units, or to doubt an age order
_TOL = 1e-9


class Stack:
    def __init__(self, tops: dict, lexicon=None, ages: dict | None = None, superposition: dict | None = None,
                 min_holes: int = MIN_HOLES):
        self.tops = dict(tops)
        info = {}
        for unit in self.tops:
            given = (ages or {}).get(unit)
            if given is not None:
                rng = units.finest_age_range(given) if isinstance(given, str) else tuple(given)
                age = {"name": unit, "age": given if isinstance(given, str) else None, "range_ma": rng,
                       "source_id": "given", "locator": None, "extraction_method": "inference", "inferred": True}
                age = age if rng else None
            else:
                age = units.unit_age(unit, lexicon)
            info[unit] = age
        self.unknown_age = sorted(u for u, a in info.items() if a is None)
        known = sorted((u for u, a in info.items() if a is not None),
                       key=lambda u: (info[u]["range_ma"][0], info[u]["range_ma"][1], u))
        self.order = [{"unit": u, "age": info[u]} for u in known]
        self.constraints, self.unordered, self.conflicts = [], [], []
        self.basis, self.unordered_reasons = {}, []
        sup = superposition or {}
        for i, a in enumerate(known):
            for b in known[i + 1:]:
                ya, oa = info[a]["range_ma"]
                yb, ob = info[b]["range_ma"]
                if oa <= yb:
                    younger, older = a, b
                elif ob <= ya:
                    younger, older = b, a
                else:
                    ab, ba = sup.get((a, b), 0), sup.get((b, a), 0)
                    if ab >= min_holes and ba == 0 or ba >= min_holes and ab == 0:
                        upper, lower, k = (a, b, ab) if ab else (b, a, ba)
                        self.constraints.append((upper, lower))
                        self.basis[(upper, lower)] = f"superposition, {k} holes"
                        continue
                    self.unordered.append((a, b))
                    self.unordered_reasons.append({
                        "units": [a, b], "holes": {f"{a} over {b}": ab, f"{b} over {a}": ba},
                        "reason": (f"age ranges overlap, and the holes do not settle the order ({ab} log {a} over "
                                   f"{b}, {ba} the reverse; {min_holes}+ one way and none the other are needed)")})
                    continue
                rev, fwd = sup.get((older, younger), 0), sup.get((younger, older), 0)
                if rev >= min_holes and rev > fwd:
                    self.conflicts.append({"younger": younger, "older": older, "holes_reversed": rev,
                                           "holes_in_order": fwd})
                    continue
                self.constraints.append((younger, older))
                self.basis[(younger, older)] = "age"

    # --- one place -----------------------------------------------------------------

    def estimate(self, x: float, y: float) -> dict:
        """{unit: estimate} at (x, y): the surface's own estimate plus the stacked value."""
        raw = {u: s.estimate(x, y) for u, s in self.tops.items()}
        live = [u for u, e in raw.items() if e["value"] is not None]
        cons = [(a, b) for a, b in self.constraints if a in live and b in live]
        z0 = {u: raw[u]["value"] for u in live}
        z = _project(z0, cons, self._weights(raw, live))
        out = {}
        for u, e in raw.items():
            r = {**e, "inferred": True, "value_unstacked": e["value"], "std_unstacked": e["std"],
                 "adjusted": False, "moved_ft": 0.0 if e["value"] is not None else None, "adjustment_reason": None,
                 "order_basis": None}
            if u in z:
                moved = z[u] - z0[u]
                if moved != 0.0:
                    group = _pinned(u, z, cons)
                    stds = [raw[v]["std"] for v in group if raw[v]["std"] is not None]
                    r |= {"value": z[u], "moved_ft": moved, "adjusted": True,
                          "std": max(stds) if stds else e["std"],
                          "adjustment_reason": self._reason(u, moved, z, cons),
                          "order_basis": "; ".join(sorted({self.basis[c] for c in cons if u in c
                                                            and abs(z[c[0]] - z[c[1]]) <= 1e-6}))}
            out[u] = r
        return out

    @staticmethod
    def _weights(raw: dict, live: list) -> dict:
        stds = [raw[u]["std"] for u in live if raw[u]["std"]]
        worst = max(stds) if stds else 1.0
        return {u: 1.0 / (raw[u]["std"] or worst) ** 2 for u in live}

    def _why(self, pair, rel) -> str:
        b = self.basis[pair]
        return f"{rel} by geologic age" if b == "age" else f"above it by superposition, {b.split(', ', 1)[1]}" \
            if rel == "younger" else f"below it by superposition, {b.split(', ', 1)[1]}"

    def _reason(self, u, moved, z, cons) -> str:
        above = [(a, b) for a, b in cons if b == u and abs(z[a] - z[u]) <= 1e-6]
        below = [(a, b) for a, b in cons if a == u and abs(z[b] - z[u]) <= 1e-6]
        parts = [f"at or below the top of {a} ({self._why((a, b), 'younger')})" for a, b in above]
        parts += [f"at or above the top of {b} ({self._why((a, b), 'older')})" for a, b in below]
        amount = f"{abs(moved):.1f} ft" if abs(moved) >= 0.05 else "less than 0.1 ft"
        return f"moved {'down' if moved < 0 else 'up'} {amount} to lie " + " and ".join(parts)

    # --- checks and provenance ---------------------------------------------------------

    def crossings(self, step_ft: float = 2000.0, bounds: tuple | None = None) -> dict:
        """Grid nodes where an ordered pair (and, for information, an unordered one) crosses, before
        and after stacking. Pairs are (younger, older); unordered pairs in the order given."""
        if bounds is None:
            xs = [p.x for s in self.tops.values() for p in s.points]
            ys = [p.y for s in self.tops.values() for p in s.points]
            bounds = (min(xs), min(ys), max(xs), max(ys))
        pairs = {p: {"nodes": 0, "crossed_before": 0, "crossed_after": 0, "worst_before_ft": 0.0,
                     "worst_after_ft": 0.0, "ordered": True, "basis": self.basis[p]} for p in self.constraints}
        pairs |= {p: {"nodes": 0, "crossed_before": 0, "crossed_after": 0, "worst_before_ft": 0.0,
                      "worst_after_ft": 0.0, "ordered": False, "basis": None} for p in self.unordered}
        adjusted = nodes = 0
        x0, y0, x1, y1 = bounds
        x = x0
        while x <= x1 + 1e-9:
            y = y0
            while y <= y1 + 1e-9:
                e = self.estimate(x, y)
                nodes += 1
                adjusted += any(v["adjusted"] for v in e.values())
                for (a, b), c in pairs.items():
                    if e[a]["value"] is None or e[b]["value"] is None:
                        continue
                    c["nodes"] += 1
                    before = e[b]["value_unstacked"] - e[a]["value_unstacked"]
                    after = e[b]["value"] - e[a]["value"]
                    if before > 1e-6:
                        c["crossed_before"] += 1
                        c["worst_before_ft"] = round(max(c["worst_before_ft"], before), 2)
                    if after > 1e-6:
                        c["crossed_after"] += 1
                        c["worst_after_ft"] = round(max(c["worst_after_ft"], after), 2)
                y += step_ft
            x += step_ft
        return {"step_ft": step_ft, "nodes": nodes, "nodes_adjusted": adjusted, "pairs": pairs}

    def provenance(self) -> dict:
        return {"method": METHOD, "uncertainty": UNCERTAINTY, "inferred": True, "extraction_method": "inference",
                "order": self.order, "constraints": [[*c, self.basis[c]] for c in self.constraints],
                "unordered": [list(p) for p in self.unordered], "unordered_reasons": self.unordered_reasons,
                "unknown_age": self.unknown_age,
                "conflicts": self.conflicts,
                "surfaces": {u: {"method": s.method, "reason": s.reason} for u, s in self.tops.items()}}


def stack(tops: dict, lexicon=None, ages: dict | None = None, superposition: dict | None = None,
          min_holes: int = MIN_HOLES) -> Stack:
    return Stack(tops, lexicon, ages, superposition, min_holes)


def _project(z0: dict, cons: list, w: dict, sweeps: int = 2000) -> dict:
    """Weighted least-squares projection of z0 onto {z[a] >= z[b] for (a, b) in cons} (Dykstra)."""
    z = dict(z0)
    if not cons or all(z[a] >= z[b] for a, b in cons):
        return z
    inc = {k: (0.0, 0.0) for k in range(len(cons))}
    for _ in range(sweeps):
        change = 0.0
        for k, (a, b) in enumerate(cons):
            ua, ub = z[a] + inc[k][0], z[b] + inc[k][1]
            if ua >= ub:
                na, nb = ua, ub
            else:
                na = nb = (w[a] * ua + w[b] * ub) / (w[a] + w[b])
            inc[k] = (ua - na, ub - nb)
            change += abs(na - z[a]) + abs(nb - z[b])
            z[a], z[b] = na, nb
        if change < _TOL and all(z[a] >= z[b] - _TOL for a, b in cons):
            break
    # Remove the last round-off: keep each top at or below every top that must lie above it.
    changed = True
    while changed:
        changed = False
        for a, b in cons:
            if z[b] > z[a]:
                z[b] = z[a]
                changed = True
    return z


def _pinned(u, z, cons) -> set:
    """Units connected to u through constraints that are active (level with each other) at this place."""
    group, todo = {u}, [u]
    while todo:
        v = todo.pop()
        for a, b in cons:
            for p, q in ((a, b), (b, a)):
                if p == v and q not in group and abs(z[p] - z[q]) <= 1e-6:
                    group.add(q)
                    todo.append(q)
    return group
