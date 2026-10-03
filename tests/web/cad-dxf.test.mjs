import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseDxf } from '../../web/cad/dxf.js';
import { envelope, fixture, near } from './cad-helpers.mjs';

const dxf = (...lines) => lines.join('\n');

function endpoints(geom) {
  const c = geom.coordinates;
  return [c[0], c[c.length - 1]];
}
function hasEndpoint(geom, x, y, tol) {
  return endpoints(geom).some(([px, py]) => near(px, x, tol) && near(py, y, tol));
}
function envArea(geom) {
  const [x0, y0, x1, y1] = envelope(geom.coordinates);
  return (x1 - x0) * (y1 - y0);
}

// Expected values from GDAL autotest/ogr/ogr_dxf.py for assorted.dxf.
test('assorted.dxf (GDAL fixture) matches GDAL results', () => {
  const text = new TextDecoder().decode(fixture('assorted.dxf'));
  const { layers } = parseDxf(text);
  const feats = layers.find((l) => l.name === '0').features;
  const [ellipse, partial, point, line, mtext, arc] = feats;

  assert.equal(ellipse.geometry.type, 'LineString');
  assert.ok(near(envArea(ellipse.geometry), 1596.12, 0.5), envArea(ellipse.geometry));
  assert.ok(hasEndpoint(ellipse.geometry, 73.25, 139.75, 0.001));

  assert.ok(near(envArea(partial.geometry), 311.864, 0.5), envArea(partial.geometry));
  assert.ok(hasEndpoint(partial.geometry, 61.133, 103.592, 0.01));

  assert.deepEqual(point.geometry, { type: 'Point', coordinates: [83.5, 160] });
  assert.deepEqual(line.geometry.coordinates, [[97, 159.5], [108.5, 132.25]]);

  assert.deepEqual(mtext.geometry.coordinates, [84, 126]);
  assert.equal(mtext.properties.text, 'Test');

  assert.ok(near(envArea(arc.geometry), 445.748, 0.5), envArea(arc.geometry));
  assert.ok(hasEndpoint(arc.geometry, 115.258, 107.791, 0.01));
});

test('assorted.dxf skips paper space, counts dimensions, expands blocks', () => {
  const text = new TextDecoder().decode(fixture('assorted.dxf'));
  const { layers, skipped } = parseDxf(text);
  const feats = layers.find((l) => l.name === '0').features;
  assert.equal(skipped.paperSpace, 1);
  // The paper-space LINE (100.5157, 111.6689) must not be present.
  assert.ok(!feats.some((f) => f.geometry.type === 'LineString' &&
    near(f.geometry.coordinates[0][0], 100.5157455, 1e-6)));
  // Dimensions without a graphics block are counted, not drawn.
  assert.equal(skipped.DIMENSION, 3);
  // The STAR block (5 LINEs, 2 MTEXTs) is inserted once.
  assert.equal(feats.filter((f) => f.properties.block === 'STAR').length, 7);
});

const SMALL = dxf(
  '0', 'SECTION', '2', 'HEADER', '9', '$INSUNITS', '70', '2', '0', 'ENDSEC',
  '0', 'SECTION', '2', 'TABLES', '0', 'TABLE', '2', 'LAYER',
  '0', 'LAYER', '2', 'ROADS', '70', '0', '62', '1',
  '0', 'LAYER', '2', 'EMPTY', '70', '0', '62', '-3',
  '0', 'ENDTAB', '0', 'ENDSEC',
  '0', 'SECTION', '2', 'BLOCKS',
  '0', 'BLOCK', '8', '0', '2', 'MARK', '10', '1', '20', '1',
  '0', 'LINE', '8', '0', '10', '1', '20', '1', '11', '2', '21', '1',
  '0', 'ENDBLK', '0', 'ENDSEC',
  '0', 'SECTION', '2', 'ENTITIES',
  '0', 'LWPOLYLINE', '8', 'ROADS', '90', '3', '70', '1',
  '10', '0', '20', '0', '42', '1', '10', '2', '20', '0', '10', '2', '20', '5',
  '0', 'POLYLINE', '8', 'ROADS', '66', '1', '70', '0',
  '0', 'VERTEX', '8', 'ROADS', '10', '5', '20', '5',
  '0', 'VERTEX', '8', 'ROADS', '10', '6', '20', '7',
  '0', 'SEQEND',
  '0', 'CIRCLE', '8', 'NEW', '10', '10', '20', '10', '40', '2',
  '0', 'ARC', '8', 'NEW', '10', '0', '20', '0', '40', '1', '50', '0', '51', '90', '230', '-1',
  '0', 'TEXT', '8', 'NEW', '10', '3', '20', '4', '1', 'STA 1+00',
  '0', 'INSERT', '8', 'ROADS', '2', 'MARK', '10', '10', '20', '20', '41', '2', '42', '2', '50', '90',
  '0', 'HATCH', '8', 'NEW',
  '0', 'ENDSEC', '0', 'EOF',
);

test('parseDxf keeps table layers in order, including empty ones', () => {
  const { layers, units } = parseDxf(SMALL);
  assert.deepEqual(layers.map((l) => l.name), ['ROADS', 'EMPTY', 'NEW']);
  assert.equal(layers[1].features.length, 0);
  assert.equal(layers[1].off, true);
  assert.equal(units, 'ft');
});

test('parseDxf handles bulges, closed polylines, POLYLINE/VERTEX and INSERT', () => {
  const { layers } = parseDxf(SMALL);
  const [lw, pl, ins] = layers[0].features;
  // Closed LWPOLYLINE: first segment is a semicircle bulging below y=0.
  const c = lw.geometry.coordinates;
  assert.deepEqual(c[0], [0, 0]);
  assert.deepEqual(c[c.length - 1], [0, 0]);
  const minY = Math.min(...c.map((p) => p[1]));
  assert.ok(near(minY, -1, 1e-3), `minY=${minY}`);
  assert.ok(c.some((p) => near(p[0], 2, 1e-9) && near(p[1], 5, 1e-9)));
  assert.deepEqual(pl.geometry.coordinates, [[5, 5], [6, 7]]);
  // Block line (1,1)-(2,1), base (1,1), scale 2, rotate 90, at (10,20).
  assert.ok(near(ins.geometry.coordinates[0][0], 10) && near(ins.geometry.coordinates[0][1], 20));
  assert.ok(near(ins.geometry.coordinates[1][0], 10) && near(ins.geometry.coordinates[1][1], 22));
  assert.equal(ins.properties.block, 'MARK');
});

test('parseDxf strokes circles and mirrors OCS arcs with -Z extrusion', () => {
  const { layers, skipped } = parseDxf(SMALL);
  const [circle, arc, text] = layers[2].features;
  const [x0, y0, x1, y1] = envelope(circle.geometry.coordinates);
  assert.ok(near(x0, 8, 1e-3) && near(x1, 12, 1e-3) && near(y0, 8, 1e-3) && near(y1, 12, 1e-3));
  // OCS arc 0..90 deg mirrored in x lies in the second quadrant.
  assert.ok(arc.geometry.coordinates.every(([x, y]) => x <= 1e-9 && y >= -1e-9));
  assert.deepEqual(text.geometry.coordinates, [3, 4]);
  assert.equal(text.properties.text, 'STA 1+00');
  assert.equal(skipped.HATCH, 1);
});
