import { test } from 'node:test';
import assert from 'node:assert/strict';
import { detectFormat, importCadFile, ACCEPT } from '../../web/cad/import.js';
import { SC_SPCS, lccForward } from '../../web/cad/project.js';
import { fixture, makeZip, near } from './cad-helpers.mjs';

const enc = (s) => new TextEncoder().encode(s);
const OLE = new Uint8Array([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1, 0, 0]);

test('ACCEPT lists every supported extension', () => {
  for (const ext of ['.xml', '.landxml', '.dwg', '.dxf', '.dgn', '.kml', '.kmz']) {
    assert.ok(ACCEPT.split(',').includes(ext), ext);
  }
});

test('detectFormat uses content, not just the extension', () => {
  assert.equal(detectFormat('a.dgn', fixture('smalltest.dgn')), 'dgn7');
  assert.equal(detectFormat('a.dgn', OLE), 'dgn8');
  assert.equal(detectFormat('a.dwg', enc('AC1027xxxx')), 'dwg');
  assert.equal(detectFormat('a.dxf', enc('  0\nSECTION\n')), 'dxf');
  assert.equal(detectFormat('a.dxf', enc('AutoCAD Binary DXF\r\n\x1a\0')), 'dxf-binary');
  assert.equal(detectFormat('a.kml', enc('<kml/>')), 'kml');
  assert.equal(detectFormat('a.kmz', makeZip([['doc.kml', '<kml/>']])), 'kmz');
  assert.equal(detectFormat('a.xml', enc('<?xml version="1.0"?><LandXML/>')), 'landxml');
  assert.equal(detectFormat('a.xml', enc('<other/>')), 'unknown');
  assert.equal(detectFormat('a.txt', enc('hi')), 'unknown');
});

test('DGN v8 and DWG are listed by name only', async () => {
  for (const [name, bytes] of [['plan.dgn', OLE], ['plan.dwg', enc('AC1032....')]]) {
    const r = await importCadFile({ name, bytes });
    assert.equal(r.status, 'listed');
    assert.equal(r.name, name);
    assert.deepEqual(r.layers, []);
    assert.ok(r.reason.length > 10);
  }
});

test('unknown files are rejected with an error', async () => {
  await assert.rejects(importCadFile({ name: 'x.txt', bytes: enc('hi') }));
});

test('KMZ imports the root KML as WGS84', async () => {
  const kml = '<kml><Document><name>D</name><Placemark><Point><coordinates>-79.9,32.7</coordinates></Point></Placemark></Document></kml>';
  const r = await importCadFile({ name: 'site.kmz', bytes: makeZip([['files/x.png', 'png'], ['doc.kml', kml]]) });
  assert.equal(r.status, 'imported');
  assert.equal(r.crs, 'lnglat');
  assert.deepEqual(r.layers[0].geojson.features[0].geometry.coordinates, [-79.9, 32.7]);
  assert.deepEqual(r.warnings, []);
});

const scDxf = (x, y, extra = []) => [
  '0', 'SECTION', '2', 'HEADER', ...extra, '0', 'ENDSEC',
  '0', 'SECTION', '2', 'ENTITIES',
  '0', 'POINT', '8', 'PTS', '10', String(x), '20', String(y),
  '0', 'ENDSEC', '0', 'EOF'].join('\n');

test('DXF in SC State Plane feet is projected to lon/lat', async () => {
  const [mx, my] = lccForward(-79.93, 32.78, SC_SPCS);
  const r = await importCadFile({ name: 'p.dxf', bytes: enc(scDxf(mx / 0.3048, my / 0.3048)) });
  assert.equal(r.crs, 'sc-ft');
  const [lng, lat] = r.layers[0].geojson.features[0].geometry.coordinates;
  assert.ok(near(lng, -79.93, 1e-8) && near(lat, 32.78, 1e-8));
  assert.deepEqual(r.warnings, []);
  assert.equal(r.layers[0].geojson.features[0].properties.layer, 'PTS');
});

test('DXF $INSUNITS meters selects SC State Plane meters', async () => {
  const [mx, my] = lccForward(-79.93, 32.78, SC_SPCS);
  const r = await importCadFile({ name: 'm.dxf', bytes: enc(scDxf(mx, my, ['9', '$INSUNITS', '70', '6'])) });
  assert.equal(r.crs, 'sc-m');
  assert.ok(near(r.layers[0].geojson.features[0].geometry.coordinates[0], -79.93, 1e-8));
});

test('coordinates that are already lon/lat in SC are detected', async () => {
  const r = await importCadFile({ name: 'g.dxf', bytes: enc(scDxf(-79.9, 32.7)) });
  assert.equal(r.crs, 'lnglat');
});

test('an explicit CRS overrides detection, and off-state results warn', async () => {
  const r = await importCadFile({ name: 'g.dxf', bytes: enc(scDxf(-79.9, 32.7)), crs: 'sc-ft' });
  assert.equal(r.crs, 'sc-ft');
  assert.equal(r.warnings.length, 1);
  assert.match(r.warnings[0], /outside South Carolina/);
});

test('DGN v7 imports with one layer per level', async () => {
  const r = await importCadFile({ name: 'smalltest.dgn', bytes: fixture('smalltest.dgn'), crs: 'sc-m' });
  assert.equal(r.status, 'imported');
  assert.equal(r.format, 'dgn7');
  assert.deepEqual(r.layers.slice(0, 2).map((l) => l.name), ['Level 1', 'Level 2']);
});

test('lon/lat detection also samples polygon and multipolygon coordinates', async () => {
  const kmlLike = ['0', 'SECTION', '2', 'ENTITIES',
    '0', 'SOLID', '8', 'S', '10', '-79.9', '20', '32.7', '11', '-79.8', '21', '32.7',
    '12', '-79.9', '22', '32.8', '13', '-79.8', '23', '32.8', '0', 'ENDSEC', '0', 'EOF'].join('\n');
  const r = await importCadFile({ name: 's.dxf', bytes: new TextEncoder().encode(kmlLike) });
  assert.equal(r.crs, 'lnglat');
  assert.equal(r.layers[0].geojson.features[0].geometry.type, 'Polygon');
});
