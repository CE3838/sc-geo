import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseLandXml } from '../../web/cad/landxml.js';
import { near } from './cad-helpers.mjs';

const LANDXML = `<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
  <Units><Imperial linearUnit="USSurveyFoot" areaUnit="squareFoot" volumeUnit="cubicYard"/></Units>
  <CoordinateSystem epsgCode="2273"/>
  <CgPoints name="Survey">
    <CgPoint name="1" code="IPF">100 200 10</CgPoint>
    <CgPoint name="2">110 200</CgPoint>
    <CgPoint name="3">110 210</CgPoint>
  </CgPoints>
  <Alignments>
    <Alignment name="CL Main" length="30">
      <CoordGeom>
        <Line><Start pntRef="1"/><End>100 210</End></Line>
        <Curve rot="cw" radius="10"><Start>100 210</Start><Center>100 220</Center><End>110 220</End></Curve>
        <Spiral><Start>110 220</Start><PI>115 220</PI><End>120 225</End></Spiral>
      </CoordGeom>
    </Alignment>
  </Alignments>
  <Parcels>
    <Parcel name="Lot 1"><CoordGeom>
      <Line><Start>0 0</Start><End>0 10</End></Line>
      <Line><Start>0 10</Start><End>10 10</End></Line>
      <Line><Start>10 10</Start><End>0 0</End></Line>
    </CoordGeom></Parcel>
  </Parcels>
  <Surfaces>
    <Surface name="EG"><Definition surfType="TIN">
      <Pnts><P id="1">0 0 1</P><P id="2">0 10 2</P><P id="3">10 0 3</P></Pnts>
      <Faces><F>1 2 3</F></Faces>
    </Definition></Surface>
  </Surfaces>
</LandXML>`;

test('parseLandXml reads units, EPSG and one layer per group', () => {
  const { layers, units, epsg } = parseLandXml(LANDXML);
  assert.equal(units, 'usft');
  assert.equal(epsg, 2273);
  assert.deepEqual(layers.map((l) => l.name),
    ['Points: Survey', 'Alignment: CL Main', 'Parcel: Lot 1', 'Surface: EG']);
});

test('parseLandXml swaps northing/easting to x/y and resolves pntRef', () => {
  const { layers } = parseLandXml(LANDXML);
  const pts = layers[0].features;
  assert.deepEqual(pts[0].geometry.coordinates, [200, 100]);
  assert.equal(pts[0].properties.name, '1');
  assert.equal(pts[0].properties.code, 'IPF');
  const cl = layers[1].features[0].geometry.coordinates;
  assert.deepEqual(cl[0], [200, 100]);
  assert.deepEqual(cl[cl.length - 1], [225, 120]);
});

test('parseLandXml strokes curves on the correct side', () => {
  const { layers } = parseLandXml(LANDXML);
  const cl = layers[1].features[0].geometry.coordinates;
  // Curve from (x210,y100) to (x220,y110) about center (x220,y100), radius 10.
  const curve = cl.filter(([x, y]) => x > 210 && x < 220);
  assert.ok(curve.length > 3);
  for (const [x, y] of curve) {
    assert.ok(near(Math.hypot(x - 220, y - 100), 10, 1e-6));
    assert.ok(y > 100, 'quarter circle should bow toward +y');
  }
  assert.equal(layers[1].features[0].properties.approximate, true);
});

test('parseLandXml closes parcels and builds TIN faces', () => {
  const { layers } = parseLandXml(LANDXML);
  const lot = layers[2].features[0].geometry;
  assert.equal(lot.type, 'Polygon');
  assert.deepEqual(lot.coordinates[0], [[0, 0], [10, 0], [10, 10], [0, 0]]);
  const tin = layers[3].features[0].geometry;
  assert.equal(tin.type, 'MultiPolygon');
  assert.deepEqual(tin.coordinates[0][0], [[0, 0], [10, 0], [0, 10], [0, 0]]);
});
