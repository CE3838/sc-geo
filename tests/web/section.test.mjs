import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  addVertex, canFinish, createStore, deleteVertex, formatLength, fromGeoJSON, hitVertex, lengthFeet, moveVertex,
  newLine, toGeoJSON, vertexRows,
} from '../../web/section.js';
import { toStatePlane } from '../../web/stateplane.js';

const A = [-79.96, 32.86];
const B = [-79.9, 32.86];
const C = [-79.9, 32.9];

test('newLine starts empty with a default name and an id', () => {
  const l = newLine({ id: 'x1', name: null, existing: [{ name: 'Section 1' }] });
  assert.deepEqual(l.coords, []);
  assert.equal(l.id, 'x1');
  assert.equal(l.name, 'Section 2');
});

test('vertices are added, moved and deleted without changing the input line', () => {
  const l0 = newLine({ id: 'a' });
  const l1 = addVertex(addVertex(l0, A), B);
  assert.deepEqual(l0.coords, []);
  assert.deepEqual(l1.coords, [A, B]);
  const l2 = moveVertex(l1, 1, C);
  assert.deepEqual(l2.coords, [A, C]);
  assert.deepEqual(l1.coords, [A, B]);
  const l3 = deleteVertex(l2, 0);
  assert.deepEqual(l3.coords, [C]);
  assert.deepEqual(moveVertex(l3, 5, A).coords, [C]);  // out of range: unchanged
  assert.equal(canFinish(l3), false);
  assert.equal(canFinish(l2), true);
});

test('coordinates are kept to 7 decimal places (about a centimetre)', () => {
  const l = addVertex(newLine({ id: 'a' }), [-79.123456789, 32.987654321]);
  assert.deepEqual(l.coords[0], [-79.1234568, 32.9876543]);
});

test('hitVertex finds the nearest vertex within the pixel tolerance', () => {
  const pts = [{ x: 10, y: 10 }, { x: 100, y: 100 }, { x: 104, y: 100 }];
  assert.equal(hitVertex(pts, { x: 103, y: 101 }, 8), 2);
  assert.equal(hitVertex(pts, { x: 12, y: 13 }, 8), 0);
  assert.equal(hitVertex(pts, { x: 50, y: 50 }, 8), -1);
  assert.equal(hitVertex([], { x: 0, y: 0 }, 8), -1);
});

test('length is measured in SC State Plane feet, matching the status bar', () => {
  const p = [A, B, C].map(([lng, lat]) => toStatePlane(lng, lat));
  const expected = Math.hypot(p[1].e - p[0].e, p[1].n - p[0].n) + Math.hypot(p[2].e - p[1].e, p[2].n - p[1].n);
  assert.ok(Math.abs(lengthFeet([A, B, C]) - expected) < 1e-6);
  assert.equal(lengthFeet([A]), 0);
  // About 5.6 km east-west at 32.86 N.
  assert.ok(lengthFeet([A, B]) > 18000 && lengthFeet([A, B]) < 19000);
  assert.equal(formatLength(18432.4), '18,432 ft (3.49 mi)');
  assert.equal(formatLength(250), '250 ft');
});

test('vertexRows give State Plane, lat/lon and distance along the line', () => {
  const rows = vertexRows([A, B]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].label, '1');
  assert.equal(rows[0].along, '0 ft');
  assert.equal(rows[0].stateplane, 'N 375,157 ft · E 2,319,332 ft');
  assert.match(rows[0].latlon, /32\.86/);
  assert.equal(rows[1].along, `${Math.round(lengthFeet([A, B])).toLocaleString('en-US')} ft`);
});

test('GeoJSON export and import round-trip the name and vertices', () => {
  const line = { id: 's1', name: 'A–A′ across the river', coords: [A, B, C], created: '2026-11-20T00:00:00Z' };
  const gj = toGeoJSON(line);
  assert.equal(gj.type, 'Feature');
  assert.equal(gj.geometry.type, 'LineString');
  assert.deepEqual(gj.geometry.coordinates, [A, B, C]);
  assert.equal(gj.properties.name, 'A–A′ across the river');
  assert.equal(gj.properties.length_ft, Math.round(lengthFeet([A, B, C])));
  assert.match(gj.properties.length_basis, /State Plane/);
  const back = fromGeoJSON(JSON.stringify(gj), { id: 'new' });
  assert.equal(back.name, line.name);
  assert.deepEqual(back.coords, [A, B, C]);
  assert.equal(back.id, 'new');
});

test('import accepts a FeatureCollection or a bare LineString and rejects bad input', () => {
  const fc = { type: 'FeatureCollection', features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: A }, properties: {} },
    { type: 'Feature', geometry: { type: 'LineString', coordinates: [A, B] }, properties: { name: 'From file' } }] };
  assert.equal(fromGeoJSON(fc, { id: 'i' }).name, 'From file');
  assert.equal(fromGeoJSON({ type: 'LineString', coordinates: [A, B] }, { id: 'i', name: 'Imported' }).name, 'Imported');
  assert.throws(() => fromGeoJSON('not json', { id: 'i' }), /GeoJSON/);
  assert.throws(() => fromGeoJSON({ type: 'LineString', coordinates: [A] }, { id: 'i' }), /two/);
  assert.throws(() => fromGeoJSON({ type: 'LineString', coordinates: [A, [200, 0]] }, { id: 'i' }), /longitude/);
  assert.throws(() => fromGeoJSON({ type: 'Point', coordinates: A }, { id: 'i' }), /LineString/);
});

function fakeStorage() {
  const data = new Map();
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k), data };
}

test('store saves, lists, renames and deletes lines in localStorage', () => {
  const storage = fakeStorage();
  const store = createStore(storage);
  assert.equal(store.persistent, true);
  store.save({ id: 'a', name: 'First', coords: [A, B] });
  store.save({ id: 'b', name: 'Second', coords: [B, C] });
  assert.deepEqual(store.list().map((l) => l.name), ['First', 'Second']);
  store.save({ id: 'a', name: 'First', coords: [A, C] });  // update in place
  assert.deepEqual(store.get('a').coords, [A, C]);
  store.rename('b', '  Renamed  ');
  assert.equal(store.get('b').name, 'Renamed');
  store.rename('b', '   ');  // blank names are ignored
  assert.equal(store.get('b').name, 'Renamed');
  store.remove('a');
  assert.deepEqual(store.list().map((l) => l.id), ['b']);
  // Another store on the same storage sees the saved lines.
  assert.deepEqual(createStore(storage).list().map((l) => l.id), ['b']);
});

test('store works in memory when storage is missing, throws or holds junk', () => {
  const throwing = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('quota'); }, removeItem() {} };
  for (const storage of [null, throwing]) {
    const store = createStore(storage);
    store.save({ id: 'a', name: 'Kept in memory', coords: [A, B] });
    assert.equal(store.get('a').name, 'Kept in memory');
    assert.equal(store.persistent, false);
  }
  const junk = fakeStorage();
  junk.setItem('sc-geo:sections', '{not json');
  assert.deepEqual(createStore(junk).list(), []);
  junk.setItem('sc-geo:sections', JSON.stringify([{ id: 'x', name: 'bad', coords: [[999, 0], A] }, { id: 'y' }]));
  assert.deepEqual(createStore(junk).list(), []);
});
