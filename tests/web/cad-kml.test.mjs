import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseKml } from '../../web/cad/kml.js';

const KML = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
<Document><name>Plans</name>
  <Placemark><name>Root pt</name><Point><coordinates>-79.9,32.7,0</coordinates></Point></Placemark>
  <Folder><name>Roads</name>
    <Placemark><name>Main St</name><description>CL</description>
      <LineString><coordinates>-79.9,32.7 -79.8,32.8</coordinates></LineString></Placemark>
    <Folder><name>Lots</name>
      <Placemark><Polygon>
        <outerBoundaryIs><LinearRing><coordinates>0,0 1,0 1,1 0,0</coordinates></LinearRing></outerBoundaryIs>
        <innerBoundaryIs><LinearRing><coordinates>.2,.2 .4,.2 .4,.4 .2,.2</coordinates></LinearRing></innerBoundaryIs>
      </Polygon></Placemark>
      <Placemark><MultiGeometry>
        <Point><coordinates>1,2</coordinates></Point>
        <LineString><coordinates>1,2
          3,4</coordinates></LineString>
      </MultiGeometry></Placemark>
    </Folder>
  </Folder>
  <Folder><name>Empty</name></Folder>
  <Placemark><gx:Track><gx:coord>-79 32 5</gx:coord><gx:coord>-78 33 5</gx:coord></gx:Track></Placemark>
</Document></kml>`;

test('parseKml keeps folders as layers, including empty ones', () => {
  const { layers } = parseKml(KML);
  assert.deepEqual(layers.map((l) => l.name), ['Plans', 'Roads', 'Roads / Lots', 'Empty']);
  assert.deepEqual(layers.map((l) => l.features.length), [2, 1, 3, 0]);
});

test('parseKml converts geometries and properties', () => {
  const { layers } = parseKml(KML);
  const [root, roads, lots] = layers;
  assert.deepEqual(root.features[0].geometry, { type: 'Point', coordinates: [-79.9, 32.7] });
  assert.equal(root.features[0].properties.name, 'Root pt');
  assert.deepEqual(root.features[1].geometry, { type: 'LineString', coordinates: [[-79, 32], [-78, 33]] });
  assert.equal(roads.features[0].properties.description, 'CL');
  assert.deepEqual(roads.features[0].geometry.coordinates, [[-79.9, 32.7], [-79.8, 32.8]]);
  const poly = lots.features[0].geometry;
  assert.equal(poly.type, 'Polygon');
  assert.equal(poly.coordinates.length, 2);
  assert.deepEqual(poly.coordinates[1][0], [0.2, 0.2]);
  assert.deepEqual(lots.features.slice(1).map((f) => f.geometry.type), ['Point', 'LineString']);
  assert.deepEqual(lots.features[2].geometry.coordinates, [[1, 2], [3, 4]]);
});

test('parseKml names root placemarks layer after the file when no document name', () => {
  const { layers } = parseKml(
    '<kml><Placemark><Point><coordinates>1,2</coordinates></Point></Placemark></kml>',
    'site.kml',
  );
  assert.deepEqual(layers.map((l) => l.name), ['site.kml']);
});
