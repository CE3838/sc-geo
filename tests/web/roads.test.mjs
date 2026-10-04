import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ROAD_ATTRIBUTION, ROAD_FIELDS, ROAD_LABEL_LAYER_IDS, ROAD_LINE_LAYER_IDS, ROAD_ORDER_BY, ROAD_SOURCES, ROAD_TIERS,
  TIGER_LOCAL_ROADS, TIGER_PRIMARY_ROADS, TIGER_SECONDARY_ROADS, TIGER_TRANSPORTATION, classifyRoad, describeRoad,
  normalizeRoad, roadLayers, routeRef, shieldSpec, streetName, tiersForZoom,
} from '../../web/roads.js';

const byId = (layers) => Object.fromEntries(layers.map((l) => [l.id, l]));

const tiger = (NAME, RTTYP, MTFCC = 'S1200') => ({ NAME, RTTYP, MTFCC });

test('routeRef: route numbers parsed from TIGER names', () => {
  assert.deepEqual(routeRef('I- 26', 'I'), { cls: 'interstate', ref: 'I-26' });
  assert.deepEqual(routeRef('I-526', 'I'), { cls: 'interstate', ref: 'I-526' });
  assert.deepEqual(routeRef('US Hwy 17', 'U'), { cls: 'us', ref: 'US 17' });
  assert.deepEqual(routeRef('US Hwy 52 Spr', 'U'), { cls: 'us', ref: 'US 52 Spur' });
  assert.deepEqual(routeRef('US Hwy 1 Alt', 'U'), { cls: 'us', ref: 'US 1 Alt' });
  assert.deepEqual(routeRef('US Hwy 17 Bus', 'U'), { cls: 'us', ref: 'US 17 Bus' });
  assert.deepEqual(routeRef('State Hwy 61', 'S'), { cls: 'sc', ref: 'SC 61' });
  assert.deepEqual(routeRef('State Rte 61', 'S'), { cls: 'sc', ref: 'SC 61' });
  assert.deepEqual(routeRef('State Hwy 7 Conn', 'S'), { cls: 'sc', ref: 'SC 7 Conn' });
  assert.deepEqual(routeRef('SC Hwy 642', 'S'), { cls: 'sc', ref: 'SC 642' });
  // A street name, or a route type without a number, gives no shield.
  assert.equal(routeRef('Savannah Hwy', 'M'), null);
  assert.equal(routeRef('Rivers Ave', 'U'), null);
  assert.equal(routeRef('State Rd S-10-62', 'S'), null);
  assert.equal(routeRef(null, 'I'), null);
});

test('classifyRoad: interstates, US and SC routes from TIGER RTTYP and NAME', () => {
  assert.deepEqual(classifyRoad(tiger('I- 26', 'I', 'S1100')), { cls: 'interstate', ref: 'I-26', name: null });
  assert.deepEqual(classifyRoad(tiger('US Hwy 17', 'U', 'S1100')), { cls: 'us', ref: 'US 17', name: null });
  assert.deepEqual(classifyRoad(tiger('State Hwy 61', 'S')), { cls: 'sc', ref: 'SC 61', name: null });
  assert.equal(classifyRoad(tiger('US Hwy 52 Spr', 'U')).ref, 'US 52 Spur');
  // Street names (RTTYP M) are names, not routes.
  assert.deepEqual(classifyRoad(tiger('Savannah Hwy', 'M')), { cls: 'secondary', ref: null, name: 'Savannah Hwy' });
  assert.deepEqual(classifyRoad(tiger('Mark Clark Expy', 'M', 'S1100')),
    { cls: 'secondary', ref: null, name: 'Mark Clark Expy' });
});

test('classifyRoad: secondary, ramps, local, alleys and private roads by MTFCC', () => {
  assert.equal(classifyRoad(tiger('State Rd S-10-62', 'S', 'S1400')).cls, 'secondary');
  assert.equal(classifyRoad(tiger('Co Rd 12', 'C', 'S1400')).cls, 'secondary');
  assert.deepEqual(classifyRoad(tiger(null, null, 'S1630')), { cls: 'ramp', ref: null, name: null });
  assert.deepEqual(classifyRoad(tiger('King St', 'M', 'S1400')), { cls: 'local', ref: null, name: 'King St' });
  assert.equal(classifyRoad(tiger('Frontage Rd', 'M', 'S1640')).cls, 'local');
  assert.equal(classifyRoad(tiger(null, null, 'S1730')).cls, 'local');
  assert.equal(classifyRoad(tiger('Pvt Dr', null, 'S1740')).cls, 'private');
  assert.equal(classifyRoad(tiger('  ', null, 'S1400')).name, null);
  assert.equal(classifyRoad({}).cls, 'local');
});

test('normalizeRoad: TIGER LINEARID (OID) locates the record', () => {
  const f = normalizeRoad({ type: 'Feature', id: 115519, properties: { OBJECTID: 115519, OID: '1102844054320',
    NAME: 'State Hwy 61', MTFCC: 'S1200', RTTYP: 'S' }, geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] } },
  'Secondary Roads');
  assert.equal(f.properties.fid, '1102844054320');
  assert.equal(f.properties.key, 'Secondary Roads:1102844054320');
  assert.equal(f.properties.ref, 'SC 61');
  assert.equal(f.properties.rank, 5);
});

test('tiersForZoom: interstates at state scale, highways from z8, local roads from z13', () => {
  const ids = (z) => tiersForZoom(z).map((t) => t.id);
  assert.deepEqual(ids(6), ['interstate']);
  assert.deepEqual(ids(8), ['interstate', 'highway']);
  assert.deepEqual(ids(12.5), ['interstate', 'highway']);
  assert.deepEqual(ids(13), ['local']);
  assert.deepEqual(ids(17), ['local']);
  for (const t of ROAD_TIERS) {
    assert.ok(t.layers.length >= 1);
    for (const l of t.layers) {
      assert.match(l.url, /^https:\/\/tigerweb\.geo\.census\.gov\/arcgis\/rest\/services\/TIGERweb\/Transportation\/MapServer\/\d+$/);
      assert.ok(['Primary Roads', 'Secondary Roads', 'Local Roads'].includes(l.name), l.name);
    }
  }
  assert.equal(TIGER_PRIMARY_ROADS, `${TIGER_TRANSPORTATION}/2`);
  assert.equal(TIGER_SECONDARY_ROADS, `${TIGER_TRANSPORTATION}/6`);
  assert.equal(TIGER_LOCAL_ROADS, `${TIGER_TRANSPORTATION}/8`);
  const tier = (id) => ROAD_TIERS.find((t) => t.id === id);
  assert.deepEqual(tier('interstate').layers.map((l) => [l.url, l.where]), [[TIGER_PRIMARY_ROADS, "RTTYP='I'"]]);
  assert.deepEqual(tier('highway').layers.map((l) => [l.url, l.where]),
    [[TIGER_PRIMARY_ROADS, "RTTYP IN ('U','S')"], [TIGER_SECONDARY_ROADS, "RTTYP IN ('U','S')"]]);
  const local = tier('local');
  assert.equal(local.tileZoom, 13);
  assert.deepEqual(local.layers.map((l) => l.url), [TIGER_PRIMARY_ROADS, TIGER_SECONDARY_ROADS, TIGER_LOCAL_ROADS]);
  // Walkways, parking lots and internal census features are not requested.
  const localWhere = local.layers[2].where;
  for (const code of ['S1400', 'S1630', 'S1640', 'S1730', 'S1740']) assert.ok(localWhere.includes(code), code);
  for (const code of ['S1710', 'S1750', 'S1780', 'S1820']) assert.ok(!localWhere.includes(code), code);
  assert.deepEqual(ROAD_FIELDS, ['OBJECTID', 'OID', 'NAME', 'MTFCC', 'RTTYP']);
  assert.equal(ROAD_ORDER_BY, 'OBJECTID');
  assert.equal(ROAD_ATTRIBUTION, 'Roads: US Census Bureau TIGER/Line (live)');
});

test('roadLayers: casing under lines, ordered by class, labels with halos', () => {
  const layers = roadLayers();
  const L = byId(layers);
  assert.deepEqual(Object.keys(L).filter((id) => ROAD_LINE_LAYER_IDS.includes(id)), ROAD_LINE_LAYER_IDS);
  for (const src of ROAD_SOURCES) {
    const casing = layers.findIndex((l) => l.id === `${src}-casing`);
    const line = layers.findIndex((l) => l.id === `${src}-line`);
    assert.ok(casing >= 0 && line > casing, `${src}: casing drawn first`);
    assert.equal(L[`${src}-line`].source, src);
    assert.equal(L[`${src}-line`].layout['line-sort-key'][0], 'match');
  }
  assert.equal(L['roads-state-line'].maxzoom, 13);
  assert.equal(L['roads-hwy-line'].minzoom, 8);
  assert.equal(L['roads-local-line'].minzoom, 13);
  const names = L['roads-names'];
  assert.equal(names.type, 'symbol');
  assert.equal(names.layout['symbol-placement'], 'line');
  assert.equal(names.minzoom, 13);
  assert.deepEqual(names.layout['text-font'], ['Noto Sans Medium']);
  assert.ok(names.paint['text-halo-width'] >= 1);
  const shields = L['roads-shields-local'];
  assert.equal(shields.layout['icon-image'][0], 'concat');
  assert.ok(ROAD_LABEL_LAYER_IDS.includes('roads-shields-state'));
  assert.ok(ROAD_LABEL_LAYER_IDS.every((id) => L[id].type === 'symbol'));
});

test('shieldSpec: interstate shield, US shield, SC box; width grows with the number', () => {
  const i = shieldSpec('interstate', 'I-526');
  assert.equal(i.text, '526');
  assert.equal(i.shape, 'interstate');
  const us = shieldSpec('us', 'US 17');
  assert.equal(us.text, '17');
  assert.equal(us.shape, 'us');
  const sc = shieldSpec('sc', 'SC 7 Conn');
  assert.equal(sc.text, '7');
  assert.equal(sc.shape, 'sc');
  assert.ok(shieldSpec('us', 'US 521').width > us.width);
  assert.equal(shieldSpec('local', null), null);
});

test('describeRoad: name, route and TIGER source for the callout', () => {
  assert.deepEqual(describeRoad({ cls: 'us', ref: 'US 17', name: 'Savannah Hwy', layer: 'Secondary Roads', fid: '1102844048026' }), {
    title: 'Savannah Hwy',
    detail: 'US 17 · U.S. highway',
    source: 'US Census Bureau TIGER/Line, TIGERweb Secondary Roads (LINEARID 1102844048026)',
  });
  assert.equal(describeRoad({ cls: 'interstate', ref: 'I-26', name: null }).title, 'I-26');
  assert.equal(describeRoad({ cls: 'interstate', ref: 'I-26', name: null }).source, 'US Census Bureau TIGER/Line');
  assert.equal(describeRoad({ cls: 'local', ref: null, name: null }).title, 'Unnamed road');
  assert.equal(describeRoad({ cls: 'local', ref: null, name: 'King St' }).detail, 'Local road');
  assert.equal(describeRoad({ cls: 'secondary', ref: null, name: 'Rivers Ave' }).detail, 'Secondary road');
});
