import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  confidenceLevel, confidenceWhy, formatMa, keyReferences, mergedCard, sgmcCard, shortRef,
} from '../../web/card.js';

test('confidenceLevel: High >= 0.7, Medium 0.4-0.7, Low < 0.4', () => {
  assert.deepEqual(confidenceLevel(0.66), { value: 0.66, level: 'Medium', text: '0.66 · Medium' });
  assert.equal(confidenceLevel(0.7).level, 'High');
  assert.equal(confidenceLevel(0.4).level, 'Medium');
  assert.equal(confidenceLevel(0.399).level, 'Low');
  assert.equal(confidenceLevel(undefined), null);
});

test('confidenceWhy rebuilds the score from the stored fields (merge/score.py)', () => {
  // 1:24,000 (0.95) x identity not stated (0.9) = 0.855; 3 maps, 50% agree:
  // x (0.8 + 0.25 x 0.5) = 0.925; Geolex unit +0.03 -> 0.821.
  const p = { conf: 0.821, conf_base: 0.855, agreement: 0.5, n_sources: 3, research_support: true,
    identity_confidence: null };
  const why = confidenceWhy(p, { scale: 24000 });
  assert.deepEqual(why.map((w) => [w.label, w.value]), [
    ['Map scale 1:24,000', '0.95'],
    ['Mapper’s identification: not stated', '× 0.90'],
    ['2 other maps cover this ground; 50% agree', '× 0.93'],
    ['Recognized Geolex unit, age matches', '+ 0.03'],
    ['Confidence', '0.82'],
  ]);
});

test('confidenceWhy for a lone map with a certain identification and no Geolex match', () => {
  const p = { conf: 0.874, conf_base: 0.95, agreement: null, n_sources: 1, research_support: false,
    identity_confidence: 'certain' };
  const why = confidenceWhy(p, { scale: 24000 });
  assert.deepEqual(why.map((w) => w.value), ['0.95', '× 1.00', '× 0.92', '+ 0', '0.87']);
  assert.equal(why[2].label, 'No other map covers this ground');
  assert.equal(why[3].label, 'Not matched to a Geolex unit');
  assert.deepEqual(confidenceWhy({}, {}), []);
});

test('confidenceWhy names one other map in the singular', () => {
  const why = confidenceWhy({ conf: 0.5, conf_base: 0.55, agreement: 1, n_sources: 2 }, { scale: 500000 });
  assert.equal(why[2].label, '1 other map covers this ground; 100% agree');
});

test('formatMa gives old to young with three significant digits', () => {
  assert.equal(formatMa([0.0117, 0.129]), '0.129–0.0117 Ma');
  assert.equal(formatMa([538.8, 541]), '541–539 Ma');
  assert.equal(formatMa([2.58, 2.58]), '2.58 Ma');
  assert.equal(formatMa(null), null);
  assert.equal(formatMa('junk'), null);
});

test('shortRef: first author and year', () => {
  assert.equal(shortRef({ citation: 'Weems, R.E., and Lemon, E.M., 1993, Geology of ...', year: 1993 }), 'Weems and Lemon, 1993');
  assert.equal(shortRef({ citation: 'Weems, R.E., Lewis, W.C., and Lemon, E.M., 2014, Surficial ...', year: 2014 }),
    'Weems and others, 2014');
  assert.equal(shortRef({ citation: 'State Geologic Map Compilation', year: 2017 }), 'State Geologic Map Compilation, 2017');
  assert.equal(shortRef({ title: 'Untitled' }), 'Untitled');
});

const RECORDS = [
  { id: 'ngmdb:1', citation: 'A, 1990, big map', year: 1990, scale: 250000, bbox: [-81, 32, -79, 34] },
  { id: 'ngmdb:2', citation: 'B, 2010, quad', year: 2010, scale: 24000, bbox: [-80, 32.75, -79.875, 32.875] },
  { id: 'ngmdb:3', citation: 'C, 2015, quad', year: 2015, scale: 24000, bbox: [-80, 32.75, -79.875, 32.875] },
  { id: 'ngmdb:4', citation: 'D, 2001, report', year: 2001, bbox: [-82, 31, -78, 35] },
  { id: 'ngmdb:5', citation: 'E, 2020, far away', year: 2020, scale: 24000, bbox: [-83, 34.5, -82.875, 34.625] },
  { id: 'ngmdb:6', citation: 'F, 2000, 100k', year: 2000, scale: 100000, bbox: [-81, 32, -79, 34] },
  { id: 'ngmdb:7', citation: 'G, 1999, 100k', year: 1999, scale: 100000, bbox: [-81, 32, -79, 34] },
];

test('keyReferences: records covering the point, by scale then newest, without the source map', () => {
  assert.deepEqual(keyReferences(RECORDS, -79.95, 32.8, 'ngmdb:2').map((r) => r.id),
    ['ngmdb:3', 'ngmdb:6', 'ngmdb:7', 'ngmdb:1']);
  assert.deepEqual(keyReferences(RECORDS, -79.95, 32.8, null, 2).map((r) => r.id), ['ngmdb:3', 'ngmdb:2']);
  assert.deepEqual(keyReferences(null, -79.95, 32.8), []);
});

test('keyReferences: a footprint larger than South Carolina ranks as if its scale were unknown', () => {
  const wide = { id: 'ngmdb:9', citation: 'J, 1956, nearshore', year: 1956, scale: 26670, bbox: [-95, 27.5, -73.8, 44] };
  const ids = keyReferences([wide, ...RECORDS], -79.95, 32.8, null, 10).map((r) => r.id);
  assert.deepEqual(ids.slice(-2), ['ngmdb:4', 'ngmdb:9']);
});

const UNIT = {
  source: 'ngmdb:2', map_unit: 'Qws', name: 'Barrier-island sand facies', full_name: null,
  formation: 'Wando Formation', unit_name: 'Wando Formation, barrier-island sand facies', canonical: 'Wando',
  age: 'late Pleistocene', age_ma: [0.0117, 0.129], geomaterial: 'Coastal zone sediment', lith: null,
  description: 'Fine to medium quartz sand.',
};
const POLY = {
  source: 'ngmdb:2', map_unit: 'Qws', layer: 'surficial', identity_confidence: 'certain',
  locator: 'MapUnitPolys_ID=MUP001', conf: 0.66, conf_base: 0.95, agreement: 0.2, n_sources: 2,
  research_support: false, unit: 'ngmdb:2|Qws', age_class: 'late Pleistocene', material_class: 'Sand',
  alternatives: JSON.stringify([{ source: 'usgs-sgmc', name: 'Wando Formation', age: 'Pleistocene', scale: 500000,
    overlap: 0.9, agreement: 0.5 }]),
};
const SOURCES = {
  'ngmdb:2': { title: 'Geology of B quadrangle', citation: 'Bee, A.B., 2010, Geology of B quadrangle', scale: 24000, year: 2010 },
  'usgs-sgmc': { title: 'SGMC', citation: 'Horton, J.D., San Juan, C.A., and Stoeser, D.B., 2017, SGMC', scale: 500000, year: 2017 },
};

test('mergedCard: name, group, age, Ma range, aliases, confidence and cited rows', () => {
  const c = mergedCard({ props: POLY, unit: UNIT, sources: SOURCES, records: RECORDS, lng: -79.95, lat: 32.8 });
  assert.equal(c.title, 'Wando Formation, barrier-island sand facies');
  assert.equal(c.group, 'Wando Formation');
  assert.equal(c.subtitle, 'Surficial · map label Qws');
  assert.equal(c.age, 'late Pleistocene');
  assert.equal(c.ma, '0.129–0.0117 Ma');
  assert.deepEqual(c.aliases, ['Barrier-island sand facies', 'Wando']);
  assert.equal(c.confidence.text, '0.66 · Medium');
  assert.equal(c.confidence.why.length, 5);
  const rows = Object.fromEntries(c.rows.map((r) => [r.label, r]));
  assert.equal(rows['Map unit'].value, 'Qws');
  assert.equal(rows['Map unit'].cite, 1);
  assert.equal(rows['Age range'].inferred, true);
  assert.equal(rows['Material class'].inferred, true);
  assert.equal(rows['Geomaterial'].value, 'Coastal zone sediment');
  assert.equal(rows['Description'].value, 'Fine to medium quartz sand.');
  assert.equal(rows['Map unit'].locator, 'MapUnitPolys_ID=MUP001');
});

test('mergedCard: key references start with the source map; alternatives are cited', () => {
  const c = mergedCard({ props: POLY, unit: UNIT, sources: SOURCES, records: RECORDS, lng: -79.95, lat: 32.8 });
  assert.deepEqual(c.references.map((r) => [r.n, r.id]),
    [[1, 'ngmdb:2'], [2, 'ngmdb:3'], [3, 'ngmdb:6'], [4, 'ngmdb:7'], [5, 'ngmdb:1']]);
  assert.equal(c.references[0].citation, 'Bee, A.B., 2010, Geology of B quadrangle');
  assert.equal(c.references[0].url, 'https://ngmdb.usgs.gov/Prodesc/proddesc_2.htm');
  assert.equal(c.references[0].scale, 24000);
  assert.equal(c.alternatives.length, 1);
  assert.equal(c.alternatives[0].name, 'Wando Formation');
  assert.equal(c.alternatives[0].citation, 'Horton and others, 2017');
  assert.equal(c.alternatives[0].detail, 'Pleistocene · 1:500,000 · covers 90%');
});

test('mergedCard copes with a unit missing from the table', () => {
  const c = mergedCard({ props: { ...POLY, alternatives: 'x' }, unit: undefined, sources: {}, records: [], lng: 0, lat: 0 });
  assert.equal(c.title, 'Qws');
  assert.equal(c.ma, null);
  assert.deepEqual(c.alternatives, []);
  assert.equal(c.references[0].citation, 'ngmdb:2');
});

test('sgmcCard: SGMC unit with its source map and no merge score', () => {
  const props = { unit: 'Qw;1', name: 'Wando Formation', age_min: 'Phanerozoic - Cenozoic - Quaternary - Pleistocene',
    age_max: 'Phanerozoic - Cenozoic - Quaternary - Pleistocene', major: 'Clay', minor: 'Sand',
    lith: 'Unconsolidated, undifferentiated', ref_id: 'SC002', province: 'Coastal Plain',
    description: 'Clayey sand', locator: 'OBJECTID=1; UNIT_LINK=SCQw;1',
    ngmdb: 'https://ngmdb.usgs.gov/Prodesc/proddesc_1.htm', age_class: 'Quaternary', lith_class: 'Unconsolidated' };
  const c = sgmcCard({ props, meta: { references: { SC002: 'Surficial geology of the Coastal Plain' } },
    records: RECORDS, lng: -79.95, lat: 32.8 });
  assert.equal(c.title, 'Wando Formation');
  assert.equal(c.age, 'Pleistocene');
  assert.equal(c.confidence, null);
  assert.match(c.confidenceNote, /not scored/);
  assert.equal(c.references[0].id, 'usgs-sgmc');
  assert.equal(c.references[1].citation, 'Surficial geology of the Coastal Plain');
  assert.equal(c.references[1].url, 'https://ngmdb.usgs.gov/Prodesc/proddesc_1.htm');
  assert.equal(c.references.length, 5);
  const rows = Object.fromEntries(c.rows.map((r) => [r.label, r]));
  assert.equal(rows.Rock.value, 'Clay; minor Sand');
  assert.equal(rows.Rock.cite, 2);
  assert.equal(rows['Age class'].inferred, true);
});
