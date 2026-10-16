// Shared helpers live in one module each; older import paths keep working.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as arcgis from '../../web/arcgis.js';
import * as geo from '../../web/geo.js';
import * as water from '../../web/usgs-water.js';
import * as roadsUi from '../../web/roads-ui.js';

test('fetchJson and FETCH_TIMEOUT_MS come from arcgis.js; roads-ui.js re-exports them', () => {
  assert.equal(typeof arcgis.fetchJson, 'function');
  assert.equal(roadsUi.fetchJson, arcgis.fetchJson);
  assert.equal(roadsUi.FETCH_TIMEOUT_MS, arcgis.FETCH_TIMEOUT_MS);
});

test('one debounce, with cancel, shared by the live layers and the water layer', () => {
  assert.equal(water.debounce, arcgis.debounce);
  const timers = [];
  const clock = { setTimeout: (fn) => { timers.push(fn); return timers.length; }, clearTimeout: (id) => { timers[id - 1] = null; } };
  const seen = [];
  const d = water.debounce((x) => seen.push(x), 10, clock);
  d(1); d.cancel();
  timers.forEach((fn) => fn?.());
  assert.deepEqual(seen, []);
});

test('viewBox lives in geo.js (roads-ui.js re-exports it) and clips the view to a limit', () => {
  assert.equal(roadsUi.viewBox, geo.viewBox);
  const map = (w, s, e, n) => ({ getBounds: () => ({ getWest: () => w, getSouth: () => s, getEast: () => e, getNorth: () => n }) });
  assert.deepEqual(geo.viewBox(map(-90, 30, -80, 33)), [-83.4, 31.7, -80, 33]);
  assert.equal(geo.viewBox(map(-100, 40, -95, 45)), null);
});
