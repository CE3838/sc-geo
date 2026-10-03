import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  confidenceColor, confidenceText, legendFor, matchColor, parseAlternatives, scaleText, sourceLink,
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
