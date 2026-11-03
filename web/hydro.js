// Hydro folder: known wells, borings, cores, test holes and springs of the
// documents (merge/wells.py -> data/sites/wells.geojson) and their water tests
// (data/sites/water-tests.json). Pure helpers, free of DOM and MapLibre so they
// can be tested with `node --test`; the layer and popup live in hydro-ui.js.

export const HYDRO_FOLDER = { id: 'hydro', label: 'Hydro' };
export const WELLS_URL = 'data/sites/wells.geojson';
export const WATER_TESTS_URL = 'data/sites/water-tests.json';
export const WELLS_SOURCE = 'hydro-wells';
export const WATER_SOURCE = 'hydro-water';
export const HYDRO_LAYER_IDS = ['hydro-wells-clusters', 'hydro-wells-cluster-count', 'hydro-wells', 'hydro-water-tests'];
export const WELL_COLOR = '#a1887f';
export const WATER_COLOR = '#26c6da';

export const KIND_TEXT = {
  well: 'Well', boring: 'Boring', core: 'Core hole', auger_hole: 'Auger hole', test_pit: 'Test pit',
  cpt: 'CPT sounding', spring: 'Spring', outcrop: 'Outcrop', other: 'Site',
};

// Known wells are clustered: about a thousand points stay fast at state scale,
// and a click on a cluster zooms in. Water-test sites draw on top, unclustered.
export function hydroLayers(wells = WELLS_SOURCE, water = WATER_SOURCE) {
  const [clusters, count, points, tests] = HYDRO_LAYER_IDS;
  return [
    { id: clusters, type: 'circle', source: wells, filter: ['has', 'point_count'],
      paint: {
        'circle-color': WELL_COLOR, 'circle-opacity': 0.85,
        'circle-radius': ['step', ['get', 'point_count'], 11, 25, 14, 100, 18],
        'circle-stroke-color': '#3e2723', 'circle-stroke-width': 1.5,
      } },
    { id: count, type: 'symbol', source: wells, filter: ['has', 'point_count'],
      layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-font': ['Noto Sans Medium'], 'text-size': 11,
        'text-allow-overlap': true },
      paint: { 'text-color': '#ffffff', 'text-halo-color': '#3e2723', 'text-halo-width': 1 } },
    { id: points, type: 'circle', source: wells, filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-color': WELL_COLOR,
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 3.5, 14, 6],
        'circle-stroke-color': '#3e2723', 'circle-stroke-width': 1.2,
      } },
    { id: tests, type: 'circle', source: water,
      paint: {
        'circle-color': WATER_COLOR,
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 4.5, 14, 8],
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2,
      } },
  ];
}

// The wells that have water tests (one fetch of wells.geojson feeds both layers).
export function waterSites(wells) {
  const features = (wells?.features ?? []).filter((f) => (f.properties?.wt ?? 0) > 0);
  return { type: 'FeatureCollection', features };
}

const num = (x) => (typeof x === 'number' ? x.toLocaleString('en-US', { maximumFractionDigits: 2 }) : null);

function depthText(top, bottom, reference) {
  const t = num(top);
  const b = num(bottom);
  if (t == null && b == null) return '';
  const span = t != null && b != null && t !== b ? `${t}–${b}` : (t ?? b);
  if (reference === 'elevation') return `${span} ft (elevation)`;
  if (reference === 'land surface') return `${span} ft below land surface`;
  return `${span} ft`;
}

// "water_test_tables[0] row 3 column 2" -> "row 3, column 2"; other locators are not shown.
function whereText(locator) {
  const m = /\brow (\d+) column (\d+)\b/.exec(locator ?? '');
  return m ? `row ${m[1]}, column ${m[2]}` : null;
}

// One object per test of a water-tests.json site, in display form; every value keeps its page and quote.
export function waterRows(site, columns) {
  if (!site?.rows || !Array.isArray(columns)) return [];
  return site.rows.map((r) => {
    const o = Object.fromEntries(columns.map((c, i) => [c, r[i]]));
    return {
      parameter: String(o.parameter ?? o.name ?? ''),
      value: o.value == null ? '' : String(o.value),
      units: o.units == null ? '' : String(o.units),
      date: o.date == null ? '' : String(o.date),
      depth: depthText(o.top_ft, o.bottom_ft, o.depth_reference),
      span: depthText(o.top_ft, o.bottom_ft, null),
      reference: o.depth_reference ?? null,
      page: o.page ?? null,
      quote: o.quote == null ? '' : String(o.quote),
      inferred: Boolean(o.inferred),
      confidence: o.confidence ?? null,
      where: whereText(o.locator),
    };
  });
}

export function feetText(sv) {
  if (!sv) return '';
  return typeof sv.ft === 'number' ? `${num(sv.ft)} ft` : String(sv.v ?? '');
}

export function radiusText(p) {
  if (!p.ci) return 'exact coordinates';
  return p.r == null ? 'precision unknown' : `within about ${Math.max(1, Math.round(p.r)).toLocaleString('en-US')} m`;
}
