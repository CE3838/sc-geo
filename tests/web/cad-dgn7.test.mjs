import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseDgn7, vaxToDouble } from '../../web/cad/dgn7.js';
import { envelope, fixture, near } from './cad-helpers.mjs';

test('vaxToDouble converts VAX D-float', () => {
  // 1.0 in VAX D: exponent 129, zero fraction -> word0 0x4080.
  assert.equal(vaxToDouble(new Uint8Array([0x80, 0x40, 0, 0, 0, 0, 0, 0]), 0), 1);
  assert.equal(vaxToDouble(new Uint8Array([0x80, 0xc0, 0, 0, 0, 0, 0, 0]), 0), -1);
  // 0.75: exponent 128, fraction .5 -> word0 0x4040.
  assert.equal(vaxToDouble(new Uint8Array([0x40, 0x40, 0, 0, 0, 0, 0, 0]), 0), 0.75);
  assert.equal(vaxToDouble(new Uint8Array(8), 0), 0);
});

// Expected values from GDAL autotest/ogr/ogr_dgn.py for smalltest.dgn.
test('smalltest.dgn (GDAL fixture) matches GDAL results', () => {
  const { layers, dimension } = parseDgn7(fixture('smalltest.dgn'));
  assert.equal(dimension, 2);
  const all = layers.flatMap((l) => l.features);

  const text = all[0];
  assert.equal(text.properties.type, 17);
  assert.equal(text.properties.level, 1);
  assert.equal(text.properties.text, 'Demo Text');
  assert.ok(near(text.geometry.coordinates[0], 0.7365, 1e-6));
  assert.ok(near(text.geometry.coordinates[1], 4.2198, 1e-6));

  const ellipse = all[1];
  assert.equal(ellipse.properties.type, 15);
  assert.equal(ellipse.properties.level, 2);
  assert.equal(ellipse.geometry.type, 'LineString');
  assert.ok(ellipse.geometry.coordinates.length >= 15);
  const [x0, y0, x1, y1] = envelope(ellipse.geometry.coordinates);
  // GDAL envelope: x 0.328593..9.68780, y -0.09611..9.26310
  assert.ok(near(x0, 0.3285935, 1e-3) && near(x1, 9.6878, 1e-3), `${x0} ${x1}`);
  assert.ok(near(y0, -0.096105, 1e-3) && near(y1, 9.2631, 1e-3), `${y0} ${y1}`);

  const shape = all[2];
  assert.equal(shape.properties.type, 6);
  assert.equal(shape.properties.level, 2);
  assert.equal(shape.properties.color, 83);
  assert.equal(shape.geometry.type, 'Polygon');
  const expected = [[4.5355, 3.317], [4.3832, 2.6517], [4.9441, 2.5235], [4.832, 3.3331], [4.5355, 3.317]];
  shape.geometry.coordinates[0].forEach(([x, y], i) => {
    assert.ok(near(x, expected[i][0], 1e-6) && near(y, expected[i][1], 1e-6), `${x},${y}`);
  });
});

test('smalltest.dgn layers are named by level', () => {
  const { layers } = parseDgn7(fixture('smalltest.dgn'));
  assert.ok(layers.length >= 2);
  assert.deepEqual(layers.slice(0, 2).map((l) => l.name), ['Level 1', 'Level 2']);
});

test('parseDgn7 rejects files without a DGN v7 TCB', () => {
  assert.throws(() => parseDgn7(new Uint8Array([0xd0, 0xcf, 0x11, 0xe0, 0, 0, 0, 0])));
});
