import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CadStore } from '../../web/cad/store.js';

const result = (name, layerNames) => ({
  name,
  format: 'kml',
  status: 'imported',
  crs: 'lnglat',
  warnings: [],
  layers: layerNames.map((n) => ({ name: n, geojson: { type: 'FeatureCollection', features: [] } })),
});

test('addFile assigns ids, colors and visibility', () => {
  const s = new CadStore();
  const f = s.addFile(result('a.kml', ['L1', 'L2']));
  assert.equal(s.files.length, 1);
  assert.equal(f.layers.length, 2);
  assert.notEqual(f.layers[0].id, f.layers[1].id);
  assert.ok(f.layers.every((l) => l.visible && /^#[0-9a-f]{6}$/.test(l.color)));
});

test('layers can be toggled and deleted; files can be deleted', () => {
  const s = new CadStore();
  const events = [];
  s.subscribe((e) => events.push(e.type));
  const f = s.addFile(result('a.kml', ['L1', 'L2']));
  const g = s.addFile(result('b.kml', ['M1']));
  s.setLayerVisible(f.id, f.layers[0].id, false);
  assert.equal(s.getLayer(f.layers[0].id).visible, false);
  s.removeLayer(f.id, f.layers[1].id);
  assert.deepEqual(s.files[0].layers.map((l) => l.name), ['L1']);
  s.removeFile(g.id);
  assert.deepEqual(s.files.map((x) => x.name), ['a.kml']);
  assert.deepEqual(events, ['add', 'add', 'visibility', 'remove-layer', 'remove-file']);
  assert.throws(() => s.setLayerVisible(f.id, 'nope', true));
});

test('listed-only files are kept with no layers', () => {
  const s = new CadStore();
  const f = s.addFile({ name: 'x.dgn', format: 'dgn8', status: 'listed', reason: 'r', layers: [], warnings: [] });
  assert.equal(f.status, 'listed');
  assert.deepEqual(f.layers, []);
});
