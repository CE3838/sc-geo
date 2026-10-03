import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  AGE_CLASSES, LITH_CLASSES, colorExpression, formatAgeRange, legendEntries, safeHttpsUrl, shortCitation,
} from '../../web/geology.js';

test('every class has a distinct hex color', () => {
  for (const classes of [AGE_CLASSES, LITH_CLASSES]) {
    const colors = classes.map((c) => c.color);
    assert.ok(colors.every((c) => /^#[0-9a-f]{6}$/i.test(c)));
    assert.equal(new Set(colors).size, colors.length);
    assert.ok(classes.some((c) => c.id === 'Unknown'));
  }
});

test('age classes run youngest to oldest', () => {
  const ids = AGE_CLASSES.map((c) => c.id);
  assert.ok(ids.indexOf('Quaternary') < ids.indexOf('Cretaceous'));
  assert.ok(ids.indexOf('Cretaceous') < ids.indexOf('Cambrian'));
  assert.ok(ids.indexOf('Cambrian') < ids.indexOf('Neoproterozoic'));
});

test('colorExpression is a MapLibre match on the chosen class', () => {
  const expr = colorExpression('age');
  assert.deepEqual(expr.slice(0, 2), ['match', ['get', 'age_class']]);
  assert.equal(expr[expr.length - 1], AGE_CLASSES.find((c) => c.id === 'Unknown').color);
  assert.equal(expr.length, 2 + 2 * (AGE_CLASSES.length - 1) + 1);
  assert.deepEqual(colorExpression('lith').slice(0, 2), ['match', ['get', 'lith_class']]);
  assert.throws(() => colorExpression('nope'));
});

test('legendEntries lists only classes present, in class order, with counts', () => {
  const features = [
    { properties: { age_class: 'Cambrian', lith_class: 'Metamorphic' } },
    { properties: { age_class: 'Quaternary', lith_class: 'Unconsolidated' } },
    { properties: { age_class: 'Quaternary', lith_class: 'Unconsolidated' } },
    { properties: { age_class: 'Mystery', lith_class: 'Unconsolidated' } },
  ];
  assert.deepEqual(legendEntries(features, 'age').map((e) => [e.id, e.count]),
    [['Quaternary', 2], ['Cambrian', 1], ['Unknown', 1]]);
  assert.deepEqual(legendEntries(features, 'lith').map((e) => e.id), ['Unconsolidated', 'Metamorphic']);
});

test('formatAgeRange gives oldest to youngest using the finest terms', () => {
  assert.equal(formatAgeRange('Phanerozoic - Paleozoic - Permian', 'Phanerozoic - Paleozoic - Carboniferous'),
    'Carboniferous to Permian');
  const pl = 'Phanerozoic - Cenozoic - Quaternary - Pleistocene';
  assert.equal(formatAgeRange(pl, pl), 'Pleistocene');
  assert.equal(formatAgeRange('Phanerozoic - Cenozoic - Tertiary-Neogene - Miocene', null), 'Miocene');
  assert.equal(formatAgeRange(null, null), 'Unknown');
  assert.equal(formatAgeRange('Undetermined', 'Undetermined'), 'Undetermined');
});

test('safeHttpsUrl only allows https links', () => {
  assert.equal(safeHttpsUrl('https://ngmdb.usgs.gov/x'), 'https://ngmdb.usgs.gov/x');
  assert.equal(safeHttpsUrl('http://ngmdb.usgs.gov/x'), null);
  assert.equal(safeHttpsUrl('javascript:alert(1)'), null);
  assert.equal(safeHttpsUrl(undefined), null);
});

test('shortCitation trims long references', () => {
  assert.equal(shortCitation('Short ref'), 'Short ref');
  const long = 'x'.repeat(300);
  assert.ok(shortCitation(long).length <= 161 && shortCitation(long).endsWith('…'));
});
