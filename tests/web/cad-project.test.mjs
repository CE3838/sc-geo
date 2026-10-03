import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SC_SPCS, lccForward, lccInverse, makeProjector } from '../../web/cad/project.js';
import { near } from './cad-helpers.mjs';

// Snyder, Map Projections: A Working Manual (USGS PP 1395), p. 296-297:
// Clarke 1866, standard parallels 33N and 45N, origin 23N 96W.
const SNYDER = { a: 6378206.4, e2: 0.00676866, lat1: 33, lat2: 45, lat0: 23, lon0: -96, fe: 0, fn: 0 };

test('lccForward matches Snyder worked example', () => {
  const [x, y] = lccForward(-75, 35, SNYDER);
  assert.ok(near(x, 1894410.9, 0.5), `x=${x}`);
  assert.ok(near(y, 1564649.5, 0.5), `y=${y}`);
});

test('lccInverse inverts Snyder worked example', () => {
  const [lng, lat] = lccInverse(1894410.9, 1564649.5, SNYDER);
  assert.ok(near(lng, -75, 1e-6) && near(lat, 35, 1e-6), `${lng},${lat}`);
});

test('SC State Plane origin is 81W 31d50m at false easting 609600 m', () => {
  const [lng, lat] = lccInverse(609600, 0, SC_SPCS);
  assert.ok(near(lng, -81, 1e-9) && near(lat, 31 + 50 / 60, 1e-9));
});

test('SC State Plane round-trips through Charleston', () => {
  const [x, y] = lccForward(-79.93, 32.78, SC_SPCS);
  const [lng, lat] = lccInverse(x, y, SC_SPCS);
  assert.ok(near(lng, -79.93, 1e-9) && near(lat, 32.78, 1e-9));
});

test('makeProjector converts feet and passes lon/lat through', () => {
  const [x, y] = lccForward(-79.93, 32.78, SC_SPCS);
  const ft = makeProjector('sc-ft');
  const [lng, lat] = ft(x / 0.3048, y / 0.3048);
  assert.ok(near(lng, -79.93, 1e-9) && near(lat, 32.78, 1e-9));
  const usft = makeProjector('sc-usft');
  const [lng2] = usft(x * 3937 / 1200, y * 3937 / 1200);
  assert.ok(near(lng2, -79.93, 1e-9));
  assert.deepEqual(makeProjector('lnglat')(-80, 33), [-80, 33]);
  assert.throws(() => makeProjector('nope'));
});
