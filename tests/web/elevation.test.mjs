import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { elevationAt, epqsUrl, formatElevation, parseElevation } from '../../web/elevation.js';

const fixture = JSON.parse(readFileSync(new URL('../fixtures/web/epqs-point.json', import.meta.url)));

test('epqsUrl asks EPQS for feet at a WGS84 point', () => {
  assert.equal(epqsUrl(-79.96, 32.86),
    'https://epqs.nationalmap.gov/v1/json?x=-79.960000&y=32.860000&wkid=4326&units=Feet&includeDate=false');
  assert.throws(() => epqsUrl(Number.NaN, 1), RangeError);
});

test('parseElevation reads the value and treats the no-data marker as null', () => {
  assert.equal(parseElevation(fixture), 13.27);
  assert.equal(parseElevation({ value: -1000000 }), null);
  assert.equal(parseElevation({ value: '-1000000' }), null);
  assert.equal(parseElevation({ value: 'abc' }), null);
  assert.equal(parseElevation({}), null);
  assert.equal(parseElevation(null), null);
  assert.equal(parseElevation({ value: -4.2 }), -4.2); // below sea level is fine
});

test('formatElevation', () => {
  assert.equal(formatElevation(13.27), '13.3 ft (NAVD88)');
  assert.equal(formatElevation(null), 'Elevation unavailable');
});

test('elevationAt returns feet with provenance', async () => {
  const got = await elevationAt(-79.96, 32.86, { fetch: async () => ({ ok: true, json: async () => fixture }) });
  assert.equal(got.feet, 13.27);
  assert.equal(got.source_id, 'usgs-3dep-epqs');
  assert.match(got.locator, /^https:\/\/epqs\.nationalmap\.gov\/v1\/json\?x=-79\.96/);
});

test('elevationAt rejects on HTTP errors and times out', async () => {
  await assert.rejects(elevationAt(-80, 33, { fetch: async () => ({ ok: false, status: 503 }) }), /HTTP 503/);
  const hang = (url, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))));
  await assert.rejects(elevationAt(-80, 33, { fetch: hang, timeout: 20 }), /aborted/);
});
