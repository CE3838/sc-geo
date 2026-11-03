// Hydro folder layers: "Known wells (documents)" (clustered points from
// data/sites/wells.geojson) and "Water tests" (the wells with water tests,
// drawn on top), plus the well popup: label, kind, depth, elevation and a
// small table of its water tests, every value cited (source, page, quote).
// Both files are served with the viewer; nothing is fetched from other sites.
// All text from the data is added as text nodes (dom.js `el`), never as HTML.
import {
  HYDRO_LAYER_IDS, KIND_TEXT, WATER_COLOR, WATER_SOURCE, WATER_TESTS_URL, WELLS_SOURCE, WELLS_URL, WELL_COLOR,
  feetText, hydroLayers, radiusText, waterRows, waterSites,
} from './hydro.js';
import { shortRef } from './card.js';
import { safeHttpsUrl } from './geology.js';
import { el } from './dom.js';
import { onStyleReady } from './geo.js';

const [CLUSTERS, , POINTS, TESTS] = HYDRO_LAYER_IDS;
const MAX_ROWS = 25;
const NOTE = 'Read from published documents: values and units as printed; inferred values are marked. '
  + 'Provided as is, without warranty.';

function sourceLink(src, text, title) {
  const url = safeHttpsUrl(src?.url);
  return url
    ? el('a', { href: url, target: '_blank', rel: 'noopener noreferrer', ...(title ? { title } : {}) }, text)
    : el('span', title ? { title } : {}, text);
}

const quoteTitle = (q) => (q ? `“${q}”` : null);
const inferredTag = () => el('span', { class: 'hydro-inferred', title: 'Inferred, not read directly' }, 'inferred');

function cite(src, sv) {
  if (!sv || sv.p == null) return null;
  return el('span', { class: 'hydro-cite' }, ' (', sourceLink(src, `p. ${sv.p}`, quoteTitle(sv.q)), ')');
}

function testsTable(src, rows) {
  const shown = rows.slice(0, MAX_ROWS);
  // One depth reference for every row: say it once in the header and keep the cells short.
  const refs = new Set(shown.filter((r) => r.span).map((r) => r.reference));
  const oneRef = refs.size === 1 && [...refs][0] === 'land surface';
  const table = el('table', { class: 'hydro-tests' },
    el('thead', {}, el('tr', {}, ...['Parameter', 'Value', 'Units', 'Date',
      oneRef ? 'Depth below land surface' : 'Depth', 'Page'].map((h) =>
      el('th', { scope: 'col' }, h)))),
    el('tbody', {}, ...shown.map((r) => el('tr', {},
      el('th', { scope: 'row' }, r.parameter),
      el('td', {}, r.value, r.inferred && ' ', r.inferred && inferredTag()),
      el('td', {}, r.units || el('span', { class: 'card-muted' }, 'not printed')),
      el('td', { class: 'hydro-nowrap' }, r.date),
      el('td', { class: 'hydro-nowrap' }, oneRef ? r.span : r.depth),
      el('td', {}, r.page != null
        ? sourceLink(src, `p. ${r.page}`, [quoteTitle(r.quote), r.where].filter(Boolean).join(' · ') || null)
        : '')))));
  return el('div', { class: 'hydro-table-wrap' }, table,
    rows.length > shown.length && el('p', { class: 'card-muted' },
      `First ${shown.length} of ${rows.length} tests; all are in the data package (water-tests.json).`));
}

// The popup body for one well (properties of a wells.geojson feature).
export function describeSite(p, { sources = {}, water = null } = {}) {
  const src = sources?.[p.s] ?? null;
  const ref = src ? shortRef(src) : 'Source document';
  const facts = [
    ['Location', [p.loc ?? '', ' — placed ', radiusText(p), p.ci ? ' ' : '', p.ci ? inferredTag() : null,
      cite(src, { p: p.p, q: p.q })]],
  ];
  if (p.td) facts.push(['Total depth', [feetText(p.td), p.td.i ? ' ' : '', p.td.i ? inferredTag() : null, cite(src, p.td)]]);
  if (p.el) {
    const n88 = p.el.n88;
    facts.push(['Land surface', [feetText(p.el), ` ${p.el.d ?? '(datum not printed)'}`,
      p.el.i ? ' ' : '', p.el.i ? inferredTag() : null, cite(src, p.el),
      n88 && typeof n88.ft === 'number' && p.el.d !== 'NAVD88' && el('span', { class: 'hydro-navd' }, ` · NAVD 88 ${feetText(n88)} `,
        inferredTag())]]);
  }
  const testsBox = el('div', { class: 'hydro-tests-box' });
  const fill = (w) => {
    const rows = waterRows(w?.sites?.[p.id], w?.columns);
    if (rows.length) {
      testsBox.replaceChildren(el('div', { class: 'hydro-tests-h' }, `Water tests (${rows.length})`),
        testsTable(src, rows));
    } else if (p.wt > 0 && !w) {
      testsBox.replaceChildren(el('p', { class: 'card-muted' }, 'Loading water tests…'));
    } else {
      testsBox.replaceChildren(el('p', { class: 'card-muted' }, 'No water tests from this document.'));
    }
  };
  fill(water);
  const node = el('div', { class: 'feature-info hydro-site' },
    el('div', { class: 'feature-layer' }, p.l ?? KIND_TEXT[p.k] ?? 'Site'),
    el('div', { class: 'callout-sub' }, [KIND_TEXT[p.k] ?? 'Site', p.rt ? `${p.rt} rock test${p.rt === 1 ? '' : 's'}` : null]
      .filter(Boolean).join(' · ')),
    el('dl', { class: 'hydro-facts' }, ...facts.flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, ...v)])),
    testsBox,
    el('p', { class: 'geo-cite hydro-note' }, 'Source: ', sourceLink(src, ref), '. ', NOTE));
  node.fillTests = fill;
  return node;
}

function legendDot(color) {
  return el('span', { class: 'hydro-dot', style: `background:${color}` });
}

export function setupHydro(map, folder) {
  let wells = null;
  let sources = {};
  let water = null;
  let waterLoad = null;
  const vis = { wells: true, water: true };

  const wellsRow = folder.addLayer({ id: 'hydro-wells', label: 'Known Wells (Documents)', order: 10,
    detail: el('div', { class: 'water-key hydro-key' }, el('p', { class: 'geo-cite' }, legendDot(WELL_COLOR),
      ' Wells, borings, cores, test holes and springs printed in public reports, placed to within 1 mile. '
      + 'Click one for its record.')),
    onChange: (on) => { vis.wells = on; apply(); } });
  const waterRow = folder.addLayer({ id: 'hydro-water', label: 'Water Tests', order: 20,
    detail: el('div', { class: 'water-key hydro-key' }, el('p', { class: 'geo-cite' }, legendDot(WATER_COLOR),
      ' Sites with water-quality or aquifer tests in those reports.')),
    onChange: (on) => { vis.water = on; apply(); } });

  function apply() {
    for (const id of HYDRO_LAYER_IDS) {
      if (!map.getLayer(id)) continue;
      const on = id === TESTS ? vis.water : vis.wells;
      map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
    }
  }

  function loadWater() {
    waterLoad ??= fetch(WATER_TESTS_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { water = d; return d; })
      .catch((err) => { console.warn('Water tests not available:', err.message); water = { columns: [], sites: {} }; return water; });
    return waterLoad;
  }

  onStyleReady(map, () => {
    map.addSource(WELLS_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      cluster: true, clusterRadius: 40, clusterMaxZoom: 12, attribution: 'Wells: cited public reports' });
    map.addSource(WATER_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    for (const layer of hydroLayers()) map.addLayer(layer);
    apply();
    fetch(WELLS_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        wells = d;
        sources = d.sources ?? {};
        map.getSource(WELLS_SOURCE)?.setData(d);
        const ws = waterSites(d);
        map.getSource(WATER_SOURCE)?.setData(ws);
        wellsRow.setNote(` ${(d.features?.length ?? 0).toLocaleString()}`);
        waterRow.setNote(` ${ws.features.length.toLocaleString()}`);
      })
      .catch((err) => {
        console.warn('Known wells not available:', err.message);
        wellsRow.disable(' not available');
        waterRow.disable(' not available');
      });
  });

  for (const id of [CLUSTERS, POINTS, TESTS]) {
    map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
  }

  function hitAt(point, tolerance = 6) {
    if (!wells) return null;
    const layers = [TESTS, POINTS, CLUSTERS].filter((id) => map.getLayer(id)
      && map.getLayoutProperty(id, 'visibility') !== 'none');
    if (!layers.length) return null;
    const box = [[point.x - tolerance, point.y - tolerance], [point.x + tolerance, point.y + tolerance]];
    const hits = map.queryRenderedFeatures(box, { layers });
    return hits.find((f) => f.layer.id === TESTS) ?? hits.find((f) => f.layer.id === POINTS) ?? hits[0] ?? null;
  }

  // A click popup item (window.scGeo.popupItems): the well under the click, or a cluster to zoom into.
  function popupItem(e) {
    const f = hitAt(e.point);
    if (!f) return null;
    if (f.properties.point_count) {
      const src = map.getSource(WELLS_SOURCE);
      Promise.resolve(src.getClusterExpansionZoom(f.properties.cluster_id))
        .then((zoom) => map.easeTo({ center: f.geometry.coordinates, zoom }))
        .catch(() => {});
      return el('div', { class: 'feature-info' },
        el('div', { class: 'feature-layer' }, `${Number(f.properties.point_count).toLocaleString()} known wells`),
        el('div', { class: 'callout-sub' }, 'Zooming in…'));
    }
    // Feature properties from MapLibre are flattened to strings for nested objects; use the source data.
    const p = wells.features.find((x) => x.properties.id === f.properties.id)?.properties ?? f.properties;
    const node = describeSite(p, { sources, water });
    if (!water && p.wt > 0) loadWater().then((w) => node.fillTests(w));
    return node;
  }

  return { popupItem, siteAt: hitAt };
}
