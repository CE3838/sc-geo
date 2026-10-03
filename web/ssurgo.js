// Soil properties at a point from NRCS SSURGO through Soil Data Access
// (https://sdmdataaccess.sc.egov.usda.gov). Two requests: the map unit
// under the point, then the dominant component's top horizon. Values are
// SSURGO representative values (estimates, "_r"), not measurements.
// Query building and parsing are pure so they can be tested with fixtures.

export const SDA_URL = 'https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest';
export const SDA_CITATION = 'Soil Survey Staff, Natural Resources Conservation Service, USDA. '
  + 'Soil Survey Geographic (SSURGO) Database, via Soil Data Access.';

function point(lng, lat) {
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) throw new RangeError('lng and lat must be finite numbers');
  return `point(${lng.toFixed(6)} ${lat.toFixed(6)})`;
}

// Map unit(s) under a point.
export function mapUnitQuery(lng, lat) {
  return 'SELECT mu.mukey, mu.musym, mu.muname, l.areasymbol, l.areaname '
    + 'FROM mapunit mu INNER JOIN legend l ON l.lkey = mu.lkey '
    + `WHERE mu.mukey IN (SELECT mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('${point(lng, lat)}'))`;
}

// The map unit's dominant component (largest percent) and its top horizon,
// with the representative Unified class of that horizon.
export function horizonQuery(mukey) {
  if (!/^\d+$/.test(String(mukey))) throw new RangeError(`bad mukey: ${mukey}`);
  return 'SELECT TOP 1 c.cokey, c.compname, c.comppct_r, h.chkey, h.hzname, h.hzdept_r, h.hzdepb_r, '
    + 'h.sandtotal_r, h.silttotal_r, h.claytotal_r, h.ll_r, h.pi_r, h.lep_r, '
    + '(SELECT TOP 1 u.unifiedcl FROM chunified u WHERE u.chkey = h.chkey '
    + "ORDER BY CASE WHEN u.rvindicator = 'Yes' THEN 0 ELSE 1 END, u.chunifiedkey) AS unifiedcl "
    + 'FROM component c LEFT JOIN chorizon h ON h.cokey = c.cokey '
    + 'AND h.hzdept_r = (SELECT MIN(h2.hzdept_r) FROM chorizon h2 WHERE h2.cokey = c.cokey) '
    + `WHERE c.mukey = '${mukey}' ORDER BY c.comppct_r DESC, c.cokey`;
}

export function requestBody(query) {
  return JSON.stringify({ query, format: 'JSON+COLUMNNAME' });
}

// SDA "JSON+COLUMNNAME": {Table: [[col, ...], [val, ...], ...]} -> [{col: val}].
// An empty result is {} (no Table).
export function parseTable(json) {
  const table = json?.Table;
  if (!Array.isArray(table) || table.length < 1) return [];
  const [cols, ...rows] = table;
  return rows.map((r) => Object.fromEntries(cols.map((c, i) => [c, r[i]])));
}

const num = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));

// Shrink-swell class from linear extensibility percent (NRCS National Soil
// Survey Handbook, part 618: low < 3, moderate 3-6, high 6-9, very high >= 9).
export function shrinkSwell(lep) {
  const v = num(lep);
  if (v === null) return null;
  if (v < 3) return 'Low';
  if (v < 6) return 'Moderate';
  if (v < 9) return 'High';
  return 'Very high';
}

// One soil record with provenance, or null when the point has no soil map unit.
export function soilRecord(mapUnitRows, horizonRows) {
  const mu = mapUnitRows[0];
  if (!mu) return null;
  const h = horizonRows[0] ?? {};
  const locator = [`mukey ${mu.mukey}`, h.cokey && `cokey ${h.cokey}`, h.chkey && `chkey ${h.chkey}`]
    .filter(Boolean).join(', ');
  const lep = num(h.lep_r);
  return {
    mapUnit: { mukey: mu.mukey, symbol: mu.musym, name: mu.muname, area: mu.areaname, areaSymbol: mu.areasymbol },
    component: h.cokey ? { name: h.compname, percent: num(h.comppct_r) } : null,
    horizon: h.chkey ? { name: h.hzname, topCm: num(h.hzdept_r), bottomCm: num(h.hzdepb_r) } : null,
    values: {
      sand: num(h.sandtotal_r),
      silt: num(h.silttotal_r),
      clay: num(h.claytotal_r),
      liquidLimit: num(h.ll_r),
      plasticityIndex: num(h.pi_r),
      unified: h.unifiedcl || null,
      lep,
    },
    // Derived here from LEP: an inference.
    shrinkSwell: lep === null ? null : { value: shrinkSwell(lep), inferred: true, basis: `LEP ${lep}%` },
    provenance: {
      source_id: 'nrcs-ssurgo', locator, extraction_method: 'gis_import', confidence: 1.0,
      note: 'SSURGO representative values (estimates)',
    },
  };
}

async function post(query, fetchFn, signal) {
  const r = await fetchFn(SDA_URL, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: requestBody(query), signal,
  });
  if (!r.ok) throw new Error(`Soil Data Access: HTTP ${r.status}`);
  return parseTable(await r.json());
}

// Soil record at a point; rejects on network or service errors.
export async function soilAt(lng, lat, { fetch: fetchFn = globalThis.fetch, signal } = {}) {
  const units = await post(mapUnitQuery(lng, lat), fetchFn, signal);
  if (!units.length) return null;
  const horizons = await post(horizonQuery(units[0].mukey), fetchFn, signal);
  return soilRecord(units, horizons);
}
