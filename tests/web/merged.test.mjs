import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  GEOLOGY_LAYERS, confidenceColor, confidenceText, groupUnits, layerName, legendFor, matchColor, parseAlternatives, scaleText, sourceLink,
} from '../../web/merged.js';

const CLASSES = [{ id: 'Holocene', color: '#fff7bc' }, { id: 'late Pleistocene', color: '#fee391' },
  { id: 'Unknown', color: '#bdbdbd' }];

test('matchColor builds a MapLibre match with Unknown as fallback', () => {
  assert.deepEqual(matchColor('age_class', CLASSES),
    ['match', ['get', 'age_class'], 'Holocene', '#fff7bc', 'late Pleistocene', '#fee391', '#bdbdbd']);
});

test('confidenceColor interpolates from red to green', () => {
  const e = confidenceColor();
  assert.equal(e[0], 'interpolate');
  assert.deepEqual(e[2], ['coalesce', ['get', 'conf'], 0]);
  assert.ok(e.includes('#d73027') && e.includes('#1a9850'));
});

test('confidenceText explains the score', () => {
  assert.equal(confidenceText({ conf: 0.874, n_sources: 1, agreement: null, research_support: false }),
    '87% confidence · only map here');
  assert.equal(confidenceText({ conf: 0.98, n_sources: 3, agreement: 0.75, research_support: true }),
    '98% confidence · 3 maps, 75% agree · Geolex unit');
  assert.equal(confidenceText({}), 'Confidence unknown');
});

test('parseAlternatives tolerates bad input', () => {
  assert.deepEqual(parseAlternatives('[{"source":"a","name":"X","overlap":0.4}]'), [{ source: 'a', name: 'X', overlap: 0.4 }]);
  assert.deepEqual(parseAlternatives('not json'), []);
  assert.deepEqual(parseAlternatives(undefined), []);
});

test('sourceLink and scaleText', () => {
  assert.equal(sourceLink('ngmdb:100396'), 'https://ngmdb.usgs.gov/Prodesc/proddesc_100396.htm');
  assert.equal(sourceLink('usgs-sgmc:SC002'), 'https://doi.org/10.5066/F7WH2N65');
  assert.equal(sourceLink('other'), null);
  assert.equal(scaleText(24000), '1:24,000');
  assert.equal(scaleText(null), 'scale unknown');
});

test('legendFor lists classes present, in class order, with counts', () => {
  const feats = [{ properties: { age_class: 'late Pleistocene' } }, { properties: { age_class: 'Holocene' } },
    { properties: { age_class: 'Holocene' } }, { properties: { age_class: 'Odd' } }];
  assert.deepEqual(legendFor(feats, 'age_class', CLASSES).map((e) => [e.id, e.count]),
    [['Holocene', 2], ['late Pleistocene', 1], ['Unknown', 1]]);
});


test('merged layers are named by material: Unconsolidated Deposits and Consolidated Rock', () => {
  assert.deepEqual(GEOLOGY_LAYERS.map((l) => [l.id, l.label]),
    [['surficial', 'Unconsolidated Deposits'], ['bedrock', 'Consolidated Rock']]);
  assert.equal(layerName('bedrock'), 'Consolidated Rock');
  assert.equal(layerName('surficial'), 'Unconsolidated Deposits');
});

const AGE = [
  { id: 'Holocene', color: '#a', period: 'Quaternary' }, { id: 'Pleistocene', color: '#b', period: 'Quaternary' },
  { id: 'Miocene', color: '#c', period: 'Neogene' }, { id: 'Cretaceous', color: '#d', period: 'Cretaceous' },
  { id: 'Unknown', color: '#e', period: 'Unknown' }];
const UNITS = {
  'a|Qws': { map_unit: 'Qws', unit_name: 'Wando Formation, sand facies', canonical: 'Wando', age_ma: [0.0117, 0.129] },
  'b|Qw': { map_unit: 'Qw', name: 'Wando Formation', canonical: 'Wando', age_ma: [0.0117, 0.129] },
  'a|Qhm': { map_unit: 'Qhm', name: 'Marsh deposits', age_ma: [0, 0.0117] },
  'a|Qp': { map_unit: 'Qp', name: 'Penholoway Formation', age_ma: [0.774, 0.97] },
  'a|Tmh': { map_unit: 'Tmh', name: 'Hawthorn Group', age_ma: [5.333, 23.03] },
  'a|Kb': { map_unit: 'Kb', name: 'Black Creek Group', age_ma: [72, 84] },
};
const f = (unit, age_class, material_class = 'Sand') => ({ properties: { unit, age_class, material_class } });

test('groupUnits nests map units under periods and epochs, youngest first', () => {
  const feats = [f('a|Qp', 'Pleistocene'), f('a|Kb', 'Cretaceous'), f('a|Qws', 'Pleistocene'), f('b|Qw', 'Pleistocene'),
    f('a|Qhm', 'Holocene'), f('a|Tmh', 'Miocene'), f('a|Qws', 'Pleistocene'), f('x|?', 'Odd')];
  const g = groupUnits(feats, UNITS, AGE);
  assert.deepEqual(g.map((p) => [p.period, p.count]), [['Quaternary', 5], ['Neogene', 1], ['Cretaceous', 1], ['Unknown', 1]]);
  const q = g[0];
  assert.deepEqual(q.epochs.map((e) => [e.id, e.color]), [['Holocene', '#a'], ['Pleistocene', '#b']]);
  // Units with the same Geolex name are one entry, with every map label; the younger units come first.
  assert.deepEqual(q.epochs[1].units.map((u) => [u.name, u.labels, u.count]),
    [['Wando Formation', ['Qw', 'Qws'], 3], ['Penholoway Formation', ['Qp'], 1]]);
  assert.equal(q.epochs[1].units[0].ma, '0.0117–0.129 Ma');
  // A period with no epochs in the legend has one group named for the period.
  assert.deepEqual(g[2].epochs.map((e) => e.id), ['Cretaceous']);
  assert.deepEqual(g[3].epochs[0].units.map((u) => u.name), ['?']);
});

test('groupUnits works with an older legend that has no periods', () => {
  const g = groupUnits([f('a|Tmh', 'Miocene')], UNITS, AGE.map(({ period, ...c }) => c));
  assert.deepEqual(g.map((p) => p.period), ['Miocene']);
});

test('groupUnits lists undivided and undifferentiated units as Undifferentiated - epoch', () => {
  const units = {
    'a|Qtu': { map_unit: 'Qtu', name: 'Undifferentiated terrace deposits', age_ma: [0.0117, 2.58] },
    'b|Qt': { map_unit: 'Qt', name: 'Undifferentiated Terrace Deposits', age_ma: [0.0117, 2.58] },
    'c|Qcp': { map_unit: 'Qcp', name: 'Atlantic Coastal Plain deposit, undivided', age_ma: [0.0117, 0.129] },
    'a|Trc': { map_unit: 'Trc', name: 'Chatham Group, undivided', age_ma: [201.4, 237] },
    'a|Qal': { map_unit: 'Qal', name: 'Alluvium', age_ma: [0, 0.0117] },
    'b|Qal': { map_unit: 'Qal', name: 'alluvium', age_ma: [0, 0.0117] },
  };
  const ages = [...AGE.slice(0, 2), { id: 'Triassic', color: '#f', period: 'Triassic' }, AGE[4]];
  const g = groupUnits([f('a|Qtu', 'Pleistocene'), f('b|Qt', 'Pleistocene'), f('c|Qcp', 'Pleistocene'),
    f('a|Trc', 'Triassic'), f('a|Qal', 'Holocene'), f('b|Qal', 'Holocene')], units, ages);
  const pleist = g[0].epochs[1].units;
  assert.deepEqual(pleist.map((u) => [u.name, u.labels, u.count]), [['Undifferentiated - Pleistocene', ['Qcp', 'Qt', 'Qtu'], 3]]);
  // The names as printed stay with the entry.
  assert.deepEqual(pleist[0].includes, ['Atlantic Coastal Plain deposit, undivided', 'Undifferentiated terrace deposits',
    'Undifferentiated Terrace Deposits']);
  assert.equal(g[1].epochs[0].units[0].name, 'Undifferentiated - Triassic');
  // Names that differ only in capitals are one unit.
  assert.deepEqual(g[0].epochs[0].units.map((u) => [u.name, u.count]), [['Alluvium', 2]]);
});
