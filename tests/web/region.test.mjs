import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { IMAGERY_BOUNDS, MAX_BOUNDS, SC_BOUNDS, hiDpiUrl, NAIP_SOURCES } from '../../web/geo.js';

const region = JSON.parse(readFileSync(new URL('../../web/data/sc-region.geojson', import.meta.url)));

function inRing([x, y], ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function inGeometry(p, g) {
  const polys = g.type === 'MultiPolygon' ? g.coordinates : [g.coordinates];
  return polys.some((poly) => inRing(p, poly[0]) && !poly.slice(1).some((h) => inRing(p, h)));
}
const byName = (n) => region.features.find((f) => f.properties.name === n);

test('sc-region has South Carolina and the three masked neighbors', () => {
  assert.deepEqual(region.features.map((f) => [f.properties.name, f.properties.role]), [
    ['South Carolina', 'state'], ['Georgia', 'mask'], ['North Carolina', 'mask'], ['Tennessee', 'mask'],
  ]);
});

test('places fall in the right state', () => {
  const sc = byName('South Carolina').geometry;
  assert.ok(inGeometry([-79.93, 32.78], sc), 'Charleston');
  assert.ok(inGeometry([-81.03, 34.0], sc), 'Columbia');
  assert.ok(inGeometry([-82.4, 34.85], sc), 'Greenville');
  assert.ok(!inGeometry([-81.09, 32.08], sc), 'Savannah is not in SC');
  assert.ok(inGeometry([-81.09, 32.08], byName('Georgia').geometry), 'Savannah');
  assert.ok(inGeometry([-80.84, 35.23], byName('North Carolina').geometry), 'Charlotte');
  // The mask never covers South Carolina.
  for (const f of region.features.filter((x) => x.properties.role === 'mask')) {
    assert.ok(!inGeometry([-79.93, 32.78], f.geometry) && !inGeometry([-81.03, 34.0], f.geometry));
  }
});

test('imagery and pan bounds contain South Carolina', () => {
  const contains = ([[w, s], [e, n]], [[w2, s2], [e2, n2]]) => w <= w2 && s <= s2 && e >= e2 && n >= n2;
  assert.ok(contains(IMAGERY_BOUNDS, SC_BOUNDS));
  assert.ok(contains(MAX_BOUNDS, IMAGERY_BOUNDS));
});

test('hiDpiUrl doubles the export size only on high-density screens', () => {
  const naip = NAIP_SOURCES[0].url;
  assert.ok(hiDpiUrl(naip, 2).includes('size=512,512'));
  assert.equal(hiDpiUrl(naip, 1), naip);
  const cached = NAIP_SOURCES[1].url;
  assert.equal(hiDpiUrl(cached, 2), cached);
});
