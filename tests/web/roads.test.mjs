import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ROAD_LABEL_LAYER_IDS, ROAD_LINE_LAYER_IDS, ROAD_SOURCES, ROAD_TIERS, classifyRoad, describeRoad, roadLayers,
  shieldSpec, streetName, tiersForZoom,
} from '../../web/roads.js';

const byId = (layers) => Object.fromEntries(layers.map((l) => [l.id, l]));

test('classifyRoad: interstates, US and SC routes with their route numbers', () => {
  assert.deepEqual(classifyRoad({ ROUTE_TYPE: 'I-', ROUTE_NUMB: 26, ROUTE_AUX: ' ', STREET_NAM: 'INTERSTATE 26' }),
    { cls: 'interstate', ref: 'I-26', name: null });
  assert.deepEqual(classifyRoad({ ROUTE_TYPE: 'US', ROUTE_NUMB: 17, ROUTE_AUX: ' ', STREET_NAM: 'SAVANNAH HWY' }),
    { cls: 'us', ref: 'US 17', name: 'Savannah Hwy' });
  assert.deepEqual(classifyRoad({ ROUTE_TYPE: 'SC', ROUTE_NUMB: 61, ROUTE_AUX: ' ', STREET_NAM: 'ASHLEY RIVER RD' }),
    { cls: 'sc', ref: 'SC 61', name: 'Ashley River Rd' });
  // Business, alternate, truck and connector routes keep their qualifier.
  assert.equal(classifyRoad({ ROUTE_TYPE: 'US', ROUTE_NUMB: 52, ROUTE_AUX: 'BUS' }).ref, 'US 52 Bus');
  assert.equal(classifyRoad({ ROUTE_TYPE: 'US', ROUTE_NUMB: 1, ROUTE_AUX: 'ALT' }).ref, 'US 1 Alt');
  assert.equal(classifyRoad({ ROUTE_TYPE: 'SC', ROUTE_NUMB: 7, ROUTE_AUX: 'CON' }).ref, 'SC 7 Conn');
  // A street name that only repeats the route number is not shown as a name.
  assert.equal(classifyRoad({ ROUTE_TYPE: 'US', ROUTE_NUMB: 78, STREET_NAM: 'HIGHWAY 78' }).name, null);
});

test('classifyRoad: secondary, ramps, local and private roads', () => {
  assert.deepEqual(classifyRoad({ ROUTE_TYPE: 'S-', ROUTE_NUMB: 62, COUNTY_ID: 10, STREET_NAM: 'E MONTAGUE AVE' }),
    { cls: 'secondary', ref: 'S-10-62', name: 'E Montague Ave' });
  assert.equal(classifyRoad({ ROUTE_TYPE: 'R-', ROUTE_NUMB: 5167, STREET_NAM: 'Ramp to I-26 W' }).cls, 'ramp');
  assert.equal(classifyRoad({ ROUTE_TYPE: 'CD', ROUTE_NUMB: 4004, STREET_NAM: 'Exit 211 B' }).cls, 'ramp');
  assert.deepEqual(classifyRoad({ ROUTE_TYPE: 'L-', ROUTE_NUMB: 0, STREET_NAM: 'KING ST' }),
    { cls: 'local', ref: null, name: 'King St' });
  assert.equal(classifyRoad({ ROUTE_TYPE: 'PR', STREET_NAM: 'NO NAME' }).cls, 'private');
  assert.equal(classifyRoad({ ROUTE_TYPE: 'PR', STREET_NAM: 'NO NAME' }).name, null);
  assert.equal(classifyRoad({ ROUTE_TYPE: 'D-', STREET_NAM: 'ASHLEY BLVD' }).cls, 'secondary');
  assert.equal(classifyRoad({}).cls, 'local');
});

test('streetName: title case with SCDOT abbreviations tidied', () => {
  assert.equal(streetName('RIVERS AV'), 'Rivers Ave');
  assert.equal(streetName('MAYBANK HWY'), 'Maybank Hwy');
  assert.equal(streetName('MCLEOD MILL RD'), 'McLeod Mill Rd');
  assert.equal(streetName('MARTIN LUTHER KING JR BLVD'), 'Martin Luther King Jr Blvd');
  assert.equal(streetName('Ramp to I-26 W'), 'Ramp to I-26 W');
  assert.equal(streetName('  '), null);
  assert.equal(streetName('NO NAME'), null);
  assert.equal(streetName(null), null);
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
    for (const l of t.layers) assert.match(l.url, /^https:\/\/services1\.arcgis\.com\/VaY7cY9pvUYUP1Lf\/arcgis\/rest\/services\/.+\/FeatureServer\/0$/);
  }
  const local = ROAD_TIERS.find((t) => t.id === 'local');
  assert.equal(local.tileZoom, 13);
  assert.ok(local.layers.some((l) => /OTHER_ROADS/.test(l.url)));
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

test('describeRoad: name, route and source for the callout', () => {
  assert.deepEqual(describeRoad({ cls: 'us', ref: 'US 17', name: 'Savannah Hwy', layer: 'Statewide_Highways', fid: 12 }), {
    title: 'Savannah Hwy',
    detail: 'US 17 · U.S. highway',
    source: 'SCDOT road inventory (Statewide_Highways FID 12)',
  });
  assert.equal(describeRoad({ cls: 'interstate', ref: 'I-26', name: null }).title, 'I-26');
  assert.equal(describeRoad({ cls: 'local', ref: null, name: null }).title, 'Unnamed road');
  assert.equal(describeRoad({ cls: 'local', ref: null, name: 'King St' }).detail, 'Local road');
});
