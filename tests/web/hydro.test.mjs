import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// A very small DOM: enough for web/dom.js `el`, with innerHTML forbidden so data can only enter as text.
class Node {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.attrs = {}; this.children = []; this.listeners = {}; this.hidden = false; }
  set className(v) { this.attrs.class = v; }
  get className() { return this.attrs.class ?? ''; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  click() { for (const fn of this.listeners.click ?? []) fn({ stopPropagation() {} }); }
  append(...kids) { for (const k of kids) this.children.push(typeof k === 'string' || typeof k === 'number' ? new Text(String(k)) : k); }
  insertBefore(node, ref) { const i = ref ? this.children.indexOf(ref) : -1; if (i < 0) this.children.push(node); else this.children.splice(i, 0, node); }
  get textContent() { return this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this.children = [new Text(String(v))]; }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  set innerHTML(_) { throw new Error('innerHTML used'); }
  get dataset() { return Object.fromEntries(Object.entries(this.attrs).filter(([k]) => k.startsWith('data-')).map(([k, v]) => [k.slice(5), v])); }
  *walk() { yield this; for (const c of this.children) if (c instanceof Node) yield* c.walk(); }
  all(pred) { return [...this.walk()].filter(pred); }
}
class Text { constructor(t) { this.data = t; } get textContent() { return this.data; } }
globalThis.document = { createElement: (t) => new Node(t), createElementNS: (_, t) => new Node(t) };

const {
  HYDRO_FOLDER, HYDRO_LAYER_IDS, KIND_TEXT, WELLS_URL, WATER_TESTS_URL, hydroLayers, waterSites, waterRows,
} = await import('../../web/hydro.js');
const { describeSite } = await import('../../web/hydro-ui.js');
const { createSidebar } = await import('../../web/sidebar.js');

const web = (f) => readFileSync(new URL(`../../web/${f}`, import.meta.url), 'utf8');
const ID_LIKE = /\b[a-z][a-z0-9-]*:\d+\b/;

const SOURCES = {
  'ngmdb:78': { citation: 'Doe, J., and Roe, R., 1998, Ground-water quality near Summerville: USGS WRIR 98-1.',
    title: 'Ground-water quality near Summerville', year: 1998, url: 'https://ngmdb.usgs.gov/Prodesc/proddesc_78.htm' },
};
const PROPS = {
  id: 'ngmdb:78#DOR120', l: 'DOR-120 <img src=x onerror=alert(1)>', k: 'well', s: 'ngmdb:78', p: 1,
  q: 'DOR-120 330112 0801005', loc: 'lat 330112, long 0801005', ci: 1, cf: 0.64, d: null, r: 46,
  td: { v: '25 ft', ft: 25, p: 1, q: 'depth 25 ft', c: 0.8, i: 0, m: 'llm', lc: null },
  el: { v: 42, ft: 42, p: 1, q: '42', c: 0.8, i: 0, m: 'llm', lc: null, d: 'NGVD29',
    n88: { ft: 42.9, c: 0.6, i: 1, m: 'datum_conversion', cv: 'VERTCON', p: 1 } },
  wt: 2, rt: 0, n: 1,
};
const COLUMNS = ['parameter', 'name', 'category', 'value', 'qualifier', 'number', 'range', 'units', 'date', 'top_ft',
  'bottom_ft', 'depth_reference', 'sample_id', 'source_table', 'page', 'quote', 'confidence', 'inferred', 'locator'];
const row = (o) => COLUMNS.map((c) => o[c] ?? null);
const WATER = {
  columns: COLUMNS,
  sites: { 'ngmdb:78#DOR120': { label: 'DOR-120', source_id: 'ngmdb:78', rows: [
    row({ parameter: 'pH', value: 5.4, units: 'standard units', date: '1997-06-10', top_ft: 15, bottom_ft: 25,
      depth_reference: 'land surface', page: 1, quote: '5.4', confidence: 0.8, inferred: 0 }),
    row({ parameter: 'Chloride <b>', value: '<0.5', units: 'mg/L', page: 2, quote: '<0.5', confidence: 0.7, inferred: 1,
      locator: 'water_test_tables[0] row 3 column 2' }),
  ] } },
};

test('the Hydro folder holds the known wells, water tests and the USGS live layer', () => {
  assert.deepEqual(HYDRO_FOLDER, { id: 'hydro', label: 'Hydro' });
  assert.deepEqual(HYDRO_LAYER_IDS, ['hydro-wells-clusters', 'hydro-wells-cluster-count', 'hydro-wells',
    'hydro-water-tests']);
  const ids = hydroLayers().map((l) => l.id);
  assert.deepEqual(ids, HYDRO_LAYER_IDS);
  assert.equal(WELLS_URL, 'data/sites/wells.geojson');
  assert.equal(WATER_TESTS_URL, 'data/sites/water-tests.json');
  const app = web('app.js');
  assert.match(app, /addFolder\(HYDRO_FOLDER\)/);
  assert.match(app, /setupWater\(map, hydro,/);         // the live USGS layer moved into the folder
  assert.match(app, /setupHydro\(map, hydro,/);
});

test('the known-wells layer is clustered and the water-test layer is styled apart', () => {
  const [clusters, count, points, water] = hydroLayers();
  assert.equal(clusters.source, 'hydro-wells');
  assert.deepEqual(clusters.filter, ['has', 'point_count']);
  assert.deepEqual(points.filter, ['!', ['has', 'point_count']]);
  assert.equal(water.source, 'hydro-water');
  assert.notEqual(water.paint['circle-color'], points.paint['circle-color']);
  assert.equal(count.layout['text-font'][0], 'Noto Sans Medium');
  const src = web('hydro-ui.js');
  assert.match(src, /cluster: true/);
});

test('water sites are the wells with water tests', () => {
  const fc = { type: 'FeatureCollection', features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-80, 33] }, properties: { wt: 2 } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-80.1, 33] }, properties: { wt: 0 } }] };
  assert.equal(waterSites(fc).features.length, 1);
  assert.equal(waterSites(null).features.length, 0);
});

test('water rows keep units as printed, page, quote and the inferred flag', () => {
  const rows = waterRows(WATER.sites['ngmdb:78#DOR120'], COLUMNS);
  assert.equal(rows.length, 2);
  assert.deepEqual([rows[0].parameter, rows[0].value, rows[0].units, rows[0].page, rows[0].inferred],
    ['pH', '5.4', 'standard units', 1, false]);
  assert.equal(rows[0].depth, '15–25 ft below land surface');
  assert.equal(rows[1].inferred, true);
  assert.equal(rows[1].where, 'row 3, column 2');       // the table locator, without internal names
});

test('the well popup shows label, kind, depth, elevation, cited water tests and no warranty, as text only', () => {
  const node = describeSite(PROPS, { sources: SOURCES, water: WATER });
  const text = node.textContent;
  assert.match(text, /DOR-120 <img src=x onerror=alert\(1\)>/);       // escaped: kept as text
  assert.equal(node.all((n) => n.tagName === 'IMG').length, 0);
  assert.match(text, new RegExp(KIND_TEXT.well));
  assert.match(text, /25 ft/);
  assert.match(text, /42 ft/);
  assert.match(text, /NAVD 88/);
  assert.match(text, /Doe and Roe, 1998/);
  assert.match(text, /without warranty/i);
  assert.match(text, /within about 46 m/);
  const table = node.all((n) => n.tagName === 'TABLE' && n.className.includes('hydro-tests'));
  assert.equal(table.length, 1);
  const cells = table[0].all((n) => n.tagName === 'TD').map((n) => n.textContent);
  assert.ok(cells.includes('standard units') && cells.includes('mg/L'));
  assert.ok(cells.some((c) => c.includes('<0.5')));
  assert.ok(table[0].all((n) => n.tagName === 'TH').some((n) => n.textContent === 'Chloride <b>'));
  // inferred values are marked
  assert.ok(node.all((n) => n.className.includes('hydro-inferred')).length >= 1);
  // cited pages link to the source record
  const links = node.all((n) => n.tagName === 'A');
  assert.ok(links.length >= 2 && links.every((a) => a.getAttribute('href') === SOURCES['ngmdb:78'].url));
  assert.ok(links.every((a) => a.getAttribute('rel') === 'noopener noreferrer'));
});

test('popup text and tooltips show no record or project ids', () => {
  const node = describeSite(PROPS, { sources: SOURCES, water: WATER });
  assert.doesNotMatch(node.textContent, ID_LIKE);
  for (const n of node.all(() => true)) {
    assert.doesNotMatch(n.getAttribute('title') ?? '', ID_LIKE);
    assert.doesNotMatch(n.getAttribute('aria-label') ?? '', ID_LIKE);
  }
  // a source with no citation falls back to its title, never its id
  const bare = describeSite({ ...PROPS, wt: 0 }, { sources: { 'ngmdb:78': { title: 'A report', year: 2001 } }, water: null });
  assert.doesNotMatch(bare.textContent, ID_LIKE);
  assert.match(bare.textContent, /A report, 2001/);
});

test('a link only for https records; a site without tests says so', () => {
  const node = describeSite({ ...PROPS, wt: 0, td: undefined, el: undefined },
    { sources: { 'ngmdb:78': { ...SOURCES['ngmdb:78'], url: 'javascript:alert(1)' } }, water: null });
  assert.equal(node.all((n) => n.tagName === 'A').length, 0);
  assert.match(node.textContent, /No water tests/);
});

test('sidebar folders are collapsible, keep layer rows inside and leave the panel sections alone', () => {
  const root = new Node('div');
  const sidebar = createSidebar(root);
  const folder = sidebar.addFolder({ id: 'hydro', label: 'Hydro', order: 60 });
  folder.addLayer({ id: 'hydro-wells', label: 'Known Wells (Documents)', order: 1 });
  folder.addLayer({ id: 'water', label: 'Water Monitoring (USGS)', order: 3, checked: false });
  folder.addLayer({ id: 'hydro-water', label: 'Water Tests', order: 2 });
  sidebar.addLayer({ id: 'imagery', label: 'Aerial Imagery (NAIP)', order: 90 });
  const h2 = root.all((n) => n.tagName === 'H2').map((n) => n.textContent);
  assert.deepEqual(h2, ['Layers', 'Map units']);
  const labels = folder.list.all((n) => n.tagName === 'LABEL').map((n) => n.textContent);
  assert.deepEqual(labels, ['Known Wells (Documents)', 'Water Tests', 'Water Monitoring (USGS)']);
  const button = folder.row.all((n) => n.tagName === 'BUTTON')[0];
  assert.equal(button.textContent.trim(), 'Hydro');
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  button.click();
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  assert.equal(folder.list.hidden, true);
  button.click();
  assert.equal(folder.list.hidden, false);
});
