import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatStatePlane, fromStatePlane, toStatePlane } from '../../web/stateplane.js';

const near = (actual, expected, tol, msg) =>
  assert.ok(Math.abs(actual - expected) <= tol, `${msg}: ${actual} vs ${expected} (tol ${tol})`);

test('the projection origin maps to the false easting (609,600 m = 2,000,000 ft) and N 0', () => {
  const { e, n } = toStatePlane(-81, 31 + 50 / 60);
  near(e, 2000000, 1e-6, 'E');
  near(n, 0, 1e-6, 'N');
});

// Reference values from proj4js 2.12.1 (an independent implementation):
// +proj=lcc +lat_1=34.8333 +lat_2=32.5 +lat_0=31.8333 +lon_0=-81
// +x_0=609600 +y_0=0 +ellps=GRS80 +units=ft (international feet).
const REFERENCE = [
  [[-79.96, 32.86], [2319332.1997, 375156.9311]], // North Charleston
  [[-80.0, 33.0], [2306557.7533, 425966.8339]],
  [[-82.4, 34.85], [1579943.9858, 1100467.2299]], // Greenville
  [[-79.0, 33.5], [2609566.7633, 612287.1619]],
];

test('forward matches the reference implementation to a hundredth of a foot', () => {
  for (const [[lng, lat], [e, n]] of REFERENCE) {
    const r = toStatePlane(lng, lat);
    near(r.e, e, 0.01, `E at ${lng},${lat}`);
    near(r.n, n, 0.01, `N at ${lng},${lat}`);
  }
});

test('round trip through the inverse returns the same point', () => {
  for (let lat = 32; lat <= 35.2; lat += 0.4) {
    for (let lng = -83.3; lng <= -78.5; lng += 0.6) {
      const { e, n } = toStatePlane(lng, lat);
      const back = fromStatePlane(e, n);
      near(back.lng, lng, 1e-9, 'lng');
      near(back.lat, lat, 1e-9, 'lat');
    }
  }
});

test('formatStatePlane gives northing then easting in whole feet', () => {
  assert.equal(formatStatePlane(-79.96, 32.86), 'N 375,157 ft · E 2,319,332 ft');
  assert.equal(formatStatePlane(Number.NaN, 32), '');
});
