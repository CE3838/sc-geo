# Interpolating subsurface surfaces

Notes for the cross-section and plane viewer: how `model/surfaces.py` builds a
surface, how it does on the points already extracted, what the literature
suggests for Coastal Plain surfaces, and what to change, in order. Sections
2–5 are the study that led to the current method (approved 2026-10-30: planar
trend kriging as a candidate, no variogram-fit gate, tops stacked by geologic
age); section 1 describes the method now in `build()` and section 7 measures
it against the one it replaced.

Reproduce the numbers (pure Python; about 15 minutes with the method table,
seconds without it):

```sh
python -m model.surface_methods --json cv.json     # data/extracted -> leave-one-out table per surface + stacking check
python -m model.surface_methods --no-compare        # stacking check only (crossings before/after model/stack.py)
```

The experimental methods live in `model/surface_methods.py` (tests in
`tests/test_surface_methods.py`) and are not used by the viewer or the build;
`surfaces.UniversalKriging` is shared, so the study measures what `build()` runs.

## 1. The current method

`surfaces.build(points)` takes elevations in feet NAVD88 at SC State Plane
coordinates (feet) and tries three candidates on the same points:

* **Ordinary kriging (OK)** with 10 or more points. Empirical semivariogram in
  12 lag bins up to half the largest distance; spherical, exponential and
  gaussian models fitted by weighted least squares; the model with the lowest
  leave-one-out (LOO) RMSE is kept. LOO errors come exactly from one inverse
  of the kriging matrix (Dubrule, 1983).
* **Trend kriging** (universal kriging with a planar drift), same minimum. The
  variogram is fitted to the residuals of a least-squares plane (regression
  kriging); the kriging estimates the drift itself (generalized least
  squares), and that drift's dip is reported in `provenance()["trend"]`:
  `dip_ft_per_mile`, `dip_azimuth_deg` (down-dip, clockwise from north),
  `dip_direction` (quadrant bearing), `variance_explained` by a
  least-squares plane, and `used`. A quadratic drift is not a candidate
  (finding 3).
* **Fallback**: natural neighbour (Sibson) inside the convex hull, IDW
  (power 2) outside it.

**Selection.** The kriging candidate with the lower LOO RMSE is kept unless its
LOO RMSE is more than 10% above the fallback's (`cv_margin`; the margin is
about LOO error only and favours kriging, whose uncertainty grows away from
the data). There is no variogram-fit gate any more: neither r² nor the share
of nugget rejects kriging (finding 2). The fallback is used with fewer than
10 points or when no variogram model with a positive partial sill can be
fitted. `provenance()["candidates"]` lists every candidate's LOO RMSE and
which one was chosen; `reason` says why in words.

* **Uncertainty**: kriging standard deviation scaled by √MSSE of the chosen
  method's LOO (bounded 0.25–20) so it matches the errors LOO saw; the
  fallback reports its LOO RMSE. Never below 0.3 ft.
* **Limits**: no estimate beyond 3 × the median nearest-neighbour spacing;
  estimates outside the hull are flagged `extrapolated`. Every estimate is an
  inference citing the points it used.

**Stacking** (`model/stack.py`). `stack.stack(tops, lexicon)` takes unit-top
surfaces built separately and returns estimates with the order enforced:

* *Order by geologic age.* Each unit's age is its Geolex entry
  (`data/lexicon/geolex_sc.json`) read by `units.finest_age_range`, which
  keeps the most specific intervals the entry names (Geolex writes
  "Tertiary / Miocene, early", which `age_range` would read as the whole
  Tertiary). A unit is younger than another when its age range lies wholly
  at or above the other's; then its top must lie at or above the other's
  top. Units whose ranges overlap are ordered by superposition in the
  logged holes (`surface_methods.unit_order`): A above B only when 3 or more
  holes log A over B and none log B over A; otherwise the pair stays
  unordered and is reported with the hole counts (`unordered_reasons`).
  Units with no known age are not moved (`unknown_age`). Every constraint
  keeps its basis, "age" or "superposition, N holes", and every adjusted
  value carries it as `order_basis`.
  If 3 or more logged holes (`surface_methods.unit_order`) show the older
  unit above the younger, more often than the other way, the pair is not
  enforced and is reported in `conflicts`.
* *Enforcement.* At each place, the units' values are moved the least
  possible, weighted by inverse variance, to satisfy every age constraint at
  once (weighted least-squares projection, Dykstra's algorithm). Two units
  that cross both move to their inverse-variance weighted mean (zero
  thickness there; the less certain one moves more). The preferred design,
  a reference surface plus non-negative interpolated thicknesses
  (isochores), was not used: it needs each unit's thickness, and where it is
  absent, in the same holes, and the logged tops do not record absence.
* *Uncertainty after stacking.* A moved value takes the largest ± among the
  units it ends level with (connected through active constraints), never
  less than its own: reconciling two estimates that disagree does not make
  either better known. `value_unstacked`, `std_unstacked`, `moved_ft`,
  `adjusted` and `adjustment_reason` are kept on every estimate, which is
  inferred.

## 2. The data used for the test

`data/extracted` has no `surfaces[]` points with derived coordinates yet, so
the comparison uses logged holes (`observations` with derived coordinates,
a NAVD88 land-surface elevation and intervals logged as depths). The top of a
unit is taken where a hole passes from a different unit into it:
**top = land-surface elevation − logged depth**, an inference
(`surface_methods.contact_points`; every point keeps the source, page and
path it came from). A unit at the land surface has no top in that hole.
Identical point sets filed under several catalog records are measured once.

Subsurface tops with 10 or more points all come from one source: Weems, R.E.,
and Lewis, W.C., 2019, Detailed lithologic logs from auger holes in southern
Charleston County, southwestern Dorchester County, and eastern Colleton
County, South Carolina: USGS Open-File Report 2019-1119. The holes are about
2.2–2.7 miles apart (median nearest neighbour), over an area about 35 by 45
miles. Its land-surface elevations have no stated datum (kept as printed,
marked approximate; NGVD29 and NAVD88 differ by about a foot here), and the
locations are printed to the nearest few seconds. So errors of a few feet are
in the data itself, before any interpolation.

A planar trend fitted to each top dips 1.2–2.8 ft per mile toward between S28°W and
S27°E (mostly south to south-southeast), explaining 17% (Parkers Ferry) to 97% (Goose Creek) of the variance:
the regional seaward dip is the largest signal in most of these surfaces. The
OK variograms fitted to the raw tops never level off (fitted ranges of
310,000–475,000 ft, far beyond the 35–50 mile extent of the data), the usual sign of an unremoved
trend.

## 3. Leave-one-out comparison

Error = observed − estimate, in feet. **RMSE** is the main score; **bias** is
the mean error; **MSSE** (mean squared error ÷ kriging variance, ideally 1)
shows whether the raw kriging variance is honest before build() calibrates
it. Methods:

* **Current**: exactly what `build()` returned before the change (ordinary kriging or its fallback, with the r² gate).
* **OK**: ordinary kriging, best of three variogram models by LOO, with no
  fit-quality gate.
* **UK planar / quadratic**: universal kriging with a linear or quadratic
  drift in x and y (kriging with a trend; the variogram is fitted to the
  least-squares residuals, i.e. regression kriging, Hengl and others, 2007).
* **+ anisotropy**: geometric anisotropy found by searching the azimuth of
  the long axis (every 15°) and the range ratio (1–4). The plain rows choose
  it on the same errors they report, so they are optimistic; the **nested**
  rows choose it without the held-out point and are the fair comparison.

Best fair RMSE per surface in bold (the non-nested anisotropy rows are
excluded from "best").

| Surface (top of) | n | Current | OK | UK planar | UK quadratic | OK + aniso, nested | UK planar + aniso, nested |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Runnymede | 60 | 9.79 (kriging) | 9.79 | 9.64 | 10.18 | 9.74 | **9.55** |
| Harleyville | 35 | 21.70 (kriging) | 21.70 | **18.71** | 21.52 | 25.19 | 24.32 |
| Marks Head | 32 | 11.30 (kriging) | 11.30 | 9.22 | **9.02** | 11.14 | 10.19 |
| Parkers Ferry | 26 | 18.55 (natural neighbour: r² 0.26) | 16.36 | 15.24 | **14.79** | 19.69 | 16.42 |
| Givhans Ferry | 25 | 9.36 (kriging) | 9.36 | **8.63** | 8.89 | 9.02 | 8.78 |
| Wando | 19 | 13.59 (kriging) | 13.59 | **12.68** | – (n < 20) | 15.48 | 13.94 |

Bias and MSSE for the same runs:

| Surface (top of) | Current bias | UK planar bias | Current MSSE | UK planar MSSE |
| --- | ---: | ---: | ---: | ---: |
| Runnymede | +0.05 | −0.09 | 0.75 | 1.03 |
| Harleyville | −0.07 | −1.36 | 1.69 | 1.44 |
| Marks Head | +0.61 | +0.03 | 1.66 | 1.23 |
| Parkers Ferry | +0.98 | −1.39 | – | 0.79 |
| Givhans Ferry | +0.16 | −0.11 | 0.72 | 1.10 |
| Wando | −0.20 | −0.72 | 1.05 | 1.22 |

Goose Creek (n = 10) falls back to natural neighbour (RMSE 21.0 ft, bias
+8.3 ft); no isotropic variogram could be fitted, and the nested anisotropic
UK reaches 9.3 ft, but ten points are too few to trust either.

Land-surface elevations at the same holes and at well sets in other reports
were run as a control (they are not the target: the viewer takes ground
elevation from USGS 3DEP). Results were mixed: OK was best for the largest
well set (178 points), and planar drift did not help on rolling topography,
as expected.

**Findings**

1. **A planar drift helps every subsurface top.** UK with a linear drift beat
   the current method on all six tops with 19+ points: RMSE down 2% (Runnymede),
   7% (Wando), 8% (Givhans Ferry), 14% (Harleyville), 18% (Marks Head, Parkers Ferry).
   Bias stays within about ±1.4 ft and MSSE moves toward 1 on four of the five surfaces that have it for both methods.
2. **The r² gate threw away a better kriging.** Parkers Ferry fell back to
   natural neighbour (variogram r² 0.26) although OK and UK both
   cross-validate 12–18% better. LOO is the better judge than the fit of a
   noisy empirical variogram.
3. **A quadratic drift is not a safe default.** It beat the planar drift on two
   surfaces and lost on three.
4. **Searching for anisotropy overfits at these sizes.** In-sample it always
   looks better (by construction), but chosen honestly (nested) it was worse
   than plain UK on five of six tops, by up to 30% (Harleyville).
5. **Independently built surfaces cross.** Building every top on its own with
   the current method, for unit pairs that the holes log one above the other
   (3+ holes, never reversed), the lower surface came out above the upper one
   at 0% to 26% of 2,000-ft grid nodes where both have estimates, by up to
   35 ft (14 of 18 pairs cross somewhere; the four pairs of the Wando over
   Runnymede, Marks Head, Harleyville and Parkers Ferry do not). A cross section drawn from these surfaces would show units crossing.

## 4. Methods from the literature

* **Trend + residual kriging** (universal kriging, kriging with a trend,
  regression kriging): the trend carries the regional dip and the variogram
  only the local structure, which makes the variogram bounded and the
  variances meaningful (Matheron, 1963; Chilès and Delfiner, 2012, ch. 5;
  Hengl and others, 2007). Fitting the variogram to OLS residuals biases it
  low at long lags; with a low-order trend and LOO checking the result this
  is accepted practice (Hengl and others, 2007).
* **Kriging with external drift (KED) / collocated cokriging**: a dense
  secondary map (a published structure-contour grid, or a regional framework
  surface) is the drift, and the wells correct it (Xu and others, 1992;
  Chilès and Delfiner, 2012). The SC Coastal Plain has regional framework
  surfaces (Aucott and others, 1987; Campbell and Coes, 2010) that could serve
  as drift where local wells are sparse.
* **Contour maps as data**: points digitized along contour lines are dense
  along each line and absent between lines, which distorts variograms and
  makes LOO optimistic (a held-out point always has neighbours on the same
  line). Practice is to resample lines at a spacing comparable to the well
  spacing, decluster, give them a measurement-error (nugget) term reflecting
  the map's scale and contour interval, or use the contoured surface as an
  external drift instead of as data (Hutchinson, 1989, for contour-to-grid;
  Deutsch, 1989, for declustering weights).
* **Anisotropy**: geometric anisotropy is common in Coastal Plain units
  (strike-parallel continuity), but estimating it needs many pairs in each
  direction (Zimmerman, 1993); with tens of points the direction should come
  from geology (regional strike) rather than from a search, which matches
  finding 4.
* **Stratigraphic consistency**: stacked surfaces are modelled together:
  either a reference surface plus kriged thicknesses (isochores) with zero
  where a unit is absent, constrained to be non-negative, or simultaneous
  kriging/cokriging of all horizons with thickness trends (Abrahamsen, 1993;
  Pyrcz and Deutsch, 2014). Implicit potential-field methods (Lajaunie and
  others, 1997) interpolate all contacts as level sets of one field, so
  surfaces cannot cross by construction; Laurent (2016) adds thickness
  control to such models.
* **Declustering**: when borings cluster (a site investigation next to
  sparse regional wells), cell or polygonal declustering weights keep the
  cluster from dominating global statistics and the short-lag variogram
  (Deutsch, 1989; Isaaks and Srivastava, 1989).
* **Uncertainty and cross-validation practice**: report LOO RMSE, mean error
  and the mean standardized squared error (MSSE ≈ 1 when the kriging
  variance is honest); variograms from fewer than about 100 points are
  unreliable, so a fixed model family and cross-validation matter more than
  fine tuning (Oliver and Webster, 2014). Model choices (variogram family,
  drift, anisotropy) should be validated with nested CV when chosen by CV.
  Robust variogram estimators reduce the effect of outliers (Cressie and
  Hawkins, 1980).

## 5. Recommendations, ranked

1. **Add a planar drift as a candidate in `build()`** (universal kriging with
   a linear drift, variogram fitted to the residuals), chosen by LOO against
   OK and the fallback with the existing 10% margin. Measured gain 2–18% on
   every subsurface top; the code and its exact LOO are in
   `model/surface_methods.py`. Report the fitted dip (ft/mile, direction) in
   the provenance. **Done** (2026-10-30): `trend_kriging` in `build()`, dip in
   `provenance()["trend"]`; see section 7.
2. **Judge kriging by LOO, not by variogram r².** **Done** (2026-10-30): both
   the r² < 0.3 rule and the "almost all nugget" check were dropped (approved:
   "don't use the fit rule, accept more results"); the minimum point count
   and the 10% LOO margin against the fallback stay.
3. **Stack surfaces before drawing cross sections.** Build the uppermost
   surface (or use the 3DEP ground surface), then krige each unit's thickness
   (zero where a hole shows it absent, never negative) and subtract down the
   column; where only tops are available, enforce order with
   lower = min(lower, upper) and flag those nodes inferred with the larger
   of the two uncertainties. Finding 5 shows this is needed before any
   section is drawn.
   **Done** (2026-10-30) as `model/stack.py`, ordered by geologic age (Geolex)
   (same-age units by superposition in the holes), with an inverse-variance weighted projection
   instead of a plain min() (it reduces to lower = upper at a crossing, with
   the less certain surface moving more) and the larger uncertainty kept.
   Isochores remain the better design once absences are logged.
4. **Use structure-contour maps as soft data or drift, not as dense points.**
   Resample digitized contours to about the well spacing, give them a nugget
   from the map's scale weight and contour interval (half the interval is a
   reasonable standard deviation), and prefer them as an external drift where
   wells are sparse. Keep their points out of the LOO score, or score them
   separately, so the cross-validation stays honest.
5. **Decluster once site borings arrive.** Weight clustered points (cell
   declustering) in the variogram and in any global trend fit.
6. **Do not search for anisotropy yet.** If wanted, fix the direction to the
   strike of the fitted planar dip (roughly east–west for these tops) and test
   only the ratio by nested LOO; revisit when a surface has 100+ points.
7. **Keep and extend the uncertainty reporting.** Store LOO RMSE, bias, MSSE
   and the method with every surface; keep the √MSSE calibration and the
   0.3-ft floor; add the datum and location uncertainty of the inputs (about
   1 ft where the datum is not stated) as a nugget floor.

## 6. What the cross-section viewer needs from the surfaces

* Every surface sampled along the section line at a fixed spacing, each
  sample with value, ± (1σ, shown as a ±2σ band), method, `extrapolated`, and
  a gap with its reason beyond the maximum distance.
* Surfaces in stratigraphic order that never cross (recommendation 3), and
  unit extents: where a unit is absent the section should pinch it out, not
  extrapolate its top.
* The data behind them: wells and borings within a buffer of the line drawn
  as sticks with their logged intervals, each linked to source and page;
  surfaces' input points listed with their references.
* Provenance per surface: method, variogram, drift/dip, LOO RMSE, bias and
  MSSE, so the viewer can show *why* a band is wide.
* Alternatives: where independent sources disagree (extract/agreement.py),
  both values shown with citations, never averaged silently.
* Vertical datum NAVD88 throughout, feet, with vertical exaggeration stated.

## 7. The new method on the same points

`build()` after the change against `build()` before it (the "Current" column
of section 3), on the same tops. RMSE, bias and MSSE are those of the method
each version chose. Dip is the trend kriging's generalized least-squares
drift (down-dip direction); "explained" is the share of variance a
least-squares plane explains.

| Top of | n | Before | After | Change | Bias before → after | MSSE before → after | Dip (ft/mile, toward) | Explained |
| --- | ---: | --- | --- | ---: | --- | --- | --- | ---: |
| Runnymede | 60 | 9.79 (kriging) | 9.64 (trend kriging) | −2% | +0.05 → −0.09 | 0.75 → 1.03 | 2.69, S13°E | 89% |
| Harleyville | 35 | 21.70 (kriging) | 18.71 (trend kriging) | −14% | −0.07 → −1.36 | 1.69 → 1.44 | 2.29, S9°W | 68% |
| Marks Head | 32 | 11.30 (kriging) | 9.22 (trend kriging) | −18% | +0.61 → +0.03 | 1.66 → 1.23 | 2.40, S27°E | 67% |
| Parkers Ferry | 26 | 18.55 (natural neighbour, r² 0.26) | 15.24 (trend kriging) | −18% | +0.98 → −1.39 | – → 0.79 | 1.28, S30°W | 17% |
| Givhans Ferry | 25 | 9.36 (kriging) | 8.63 (trend kriging) | −8% | +0.16 → −0.11 | 0.72 → 1.10 | 2.83, S6°W | 96% |
| Wando | 19 | 13.59 (kriging) | 12.68 (trend kriging) | −7% | −0.20 → −0.72 | 1.05 → 1.22 | 2.62, S27°E | 55% |
| Goose Creek | 10 | 21.01 (natural neighbour) | 21.01 (natural neighbour) | 0% | +8.28 → +8.28 | – | – (no variogram fits) | – |

Trend kriging was chosen for all six tops with 19 or more points; on each it
also beat ordinary kriging, so the r² gate (only Parkers Ferry) and the
trend both contributed. The fitted dips, 1.3–2.8 ft per mile toward S30°W to
S27°E, match the regional seaward dip of section 2.

**Crossings.** All seven tops, ordered by Geolex age (younger first): Wando
(late Pleistocene), Goose Creek (early to middle Pliocene), Marks Head (early
Miocene), Givhans Ferry and Runnymede (both early Oligocene), Harleyville and
Parkers Ferry (both late Eocene). That gives 19 age-ordered pairs, none
contradicted by the logged holes, and two same-age pairs ordered by
superposition: Givhans Ferry over Runnymede (18 holes, none reversed) and
Harleyville over Parkers Ferry (12 holes, none reversed), 21 in all. Counts
are 2,000-ft grid nodes over the extent of all seven tops (13,066 nodes)
where both surfaces of a pair have an estimate.

| | Pairs that cross | Crossed pair-nodes (of 104,552) | Worst crossing |
| --- | ---: | ---: | ---: |
| Before (old `build()`, each top alone) | 17 of 21 | 11,476 | 35.4 ft (Givhans Ferry above Marks Head) |
| New `build()`, each top alone | 16 of 21 | 9,649 | 41.3 ft (Givhans Ferry above Goose Creek) |
| New `build()` + `stack` | **0 of 21** | **0** | 0 |

Of these, the 19 age-ordered pairs alone: 15 → 14 → 0 pairs, 8,764 → 7,330 →
0 of 92,605 pair-nodes. Stacking moved at least one value at 5,782 of the
13,066 nodes.

Per pair (crossed nodes, before → new unstacked → stacked):

| Upper (younger) | Lower (older) | Holes in order | Before | New, unstacked | Stacked |
| --- | --- | ---: | ---: | ---: | ---: |
| Wando | Goose Creek | 15 | 143 | 417 | 0 |
| Wando | Givhans Ferry | 13 | 187 | 18 | 0 |
| Wando | Marks Head, Runnymede, Harleyville, Parkers Ferry | 19–30 | 0 | 0 | 0 |
| Goose Creek | Marks Head | 5 | 100 | 102 | 0 |
| Goose Creek | Givhans Ferry | 2 | 1,650 | 1,687 | 0 |
| Goose Creek | Runnymede | 7 | 463 | 572 | 0 |
| Goose Creek | Harleyville | 2 | 3 | 31 | 0 |
| Goose Creek | Parkers Ferry | 2 | 22 | 39 | 0 |
| Marks Head | Givhans Ferry | 7 | 1,305 | 733 | 0 |
| Marks Head | Runnymede | 15 | 977 | 503 | 0 |
| Marks Head | Harleyville | 10 | 40 | 0 | 0 |
| Marks Head | Parkers Ferry | 8 | 429 | 470 | 0 |
| Givhans Ferry | Harleyville | 6 | 661 | 582 | 0 |
| Givhans Ferry | Parkers Ferry | 3 | 559 | 248 | 0 |
| Runnymede | Harleyville | 16 | 946 | 713 | 0 |
| Runnymede | Parkers Ferry | 6 | 1,279 | 1,215 | 0 |
| Givhans Ferry | Runnymede (same age; superposition) | 18 | 1,674 | 1,652 | 0 |
| Harleyville | Parkers Ferry (same age; superposition) | 12 | 1,038 | 667 | 0 |

Most remaining raw crossings involve Goose Creek (ten points, natural
neighbour, LOO RMSE 21 ft): its surface is the least certain, so stacking
moves it most. Section 3's crossing counts used only pairs logged in 3+
holes and each pair's own extent, so they differ from these.

## References

* Abrahamsen, P., 1993, Bayesian kriging for seismic depth conversion of a
  multi-layer reservoir, in Soares, A., ed., Geostatistics Tróia '92:
  Dordrecht, Kluwer.
* Aucott, W.R., Davis, M.E., and Speiran, G.K., 1987, Geohydrologic framework
  of the Coastal Plain aquifers of South Carolina: USGS Water-Resources
  Investigations Report 85-4271, https://pubs.usgs.gov/publication/wri854271.
* Campbell, B.G., and Coes, A.L., eds., 2010, Groundwater availability in the
  Atlantic Coastal Plain of North and South Carolina: USGS Professional Paper
  1773, https://doi.org/10.3133/pp1773.
* Chilès, J.-P., and Delfiner, P., 2012, Geostatistics: Modeling spatial
  uncertainty, 2nd ed.: Wiley, https://doi.org/10.1002/9781118136188.
* Cressie, N., and Hawkins, D.M., 1980, Robust estimation of the variogram: I:
  Mathematical Geology, v. 12, p. 115–125, https://doi.org/10.1007/BF01035243.
* Deutsch, C.V., 1989, DECLUS: a Fortran 77 program for determining optimum
  spatial declustering weights: Computers & Geosciences, v. 15, p. 325–332,
  https://doi.org/10.1016/0098-3004(89)90043-5.
* Dubrule, O., 1983, Cross validation of kriging in a unique neighborhood:
  Mathematical Geology, v. 15, p. 687–699, https://doi.org/10.1007/BF01033232.
* Hengl, T., Heuvelink, G.B.M., and Rossiter, D.G., 2007, About
  regression-kriging: From equations to case studies: Computers &
  Geosciences, v. 33, p. 1301–1315, https://doi.org/10.1016/j.cageo.2007.05.001.
* Hutchinson, M.F., 1989, A new procedure for gridding elevation and stream
  line data with automatic removal of spurious pits: Journal of Hydrology,
  v. 106, p. 211–232, https://doi.org/10.1016/0022-1694(89)90073-5.
* Isaaks, E.H., and Srivastava, R.M., 1989, An introduction to applied
  geostatistics: New York, Oxford University Press.
* Lajaunie, C., Courrioux, G., and Manuel, L., 1997, Foliation fields and 3D
  cartography in geology: Principles of a method based on potential
  interpolation: Mathematical Geology, v. 29, p. 571–584,
  https://doi.org/10.1007/BF02775087.
* Laurent, G., 2016, Iterative thickness regularization of stratigraphic
  layers in discrete implicit modeling: Mathematical Geosciences, v. 48,
  https://doi.org/10.1007/s11004-016-9637-y.
* Matheron, G., 1963, Principles of geostatistics: Economic Geology, v. 58,
  p. 1246–1266, https://doi.org/10.2113/gsecongeo.58.8.1246.
* Oliver, M.A., and Webster, R., 2014, A tutorial guide to geostatistics:
  Computing and modelling variograms and kriging: Catena, v. 113, p. 56–69,
  https://doi.org/10.1016/j.catena.2013.09.006.
* Pyrcz, M.J., and Deutsch, C.V., 2014, Geostatistical reservoir modeling,
  2nd ed.: Oxford University Press.
* Weems, R.E., and Lewis, W.C., 2019, Detailed lithologic logs from auger
  holes in southern Charleston County, southwestern Dorchester County, and
  eastern Colleton County, South Carolina: USGS Open-File Report 2019-1119.
* Xu, W., Tran, T.T., Srivastava, R.M., and Journel, A.G., 1992, Integrating
  seismic data in reservoir modeling: The collocated cokriging alternative:
  SPE Annual Technical Conference, SPE-24742-MS, https://doi.org/10.2118/24742-MS.
* Zimmerman, D.L., 1993, Another look at anisotropy in geostatistics:
  Mathematical Geology, v. 25, p. 453–470, https://doi.org/10.1007/BF00894779.
