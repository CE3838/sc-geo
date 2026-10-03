// KML -> layers. Each Folder becomes a layer named by its path; placemarks
// directly under the Document go in a layer named after the Document (or the
// file). Empty folders are kept as empty layers. Coordinates are WGS84.
import { child, children, parseXml, textOf } from './xml.js';

function coords(el) {
  return textOf(el)
    .split(/\s+/)
    .filter(Boolean)
    .map((t) => t.split(',').slice(0, 2).map(Number));
}

function geometries(el) {
  switch (el.name) {
    case 'Point':
      return [{ type: 'Point', coordinates: coords(child(el, 'coordinates'))[0] }];
    case 'LineString':
    case 'LinearRing':
      return [{ type: 'LineString', coordinates: coords(child(el, 'coordinates')) }];
    case 'Polygon': {
      const ring = (b) => coords(child(child(b, 'LinearRing') ?? b, 'coordinates'));
      const outer = child(el, 'outerBoundaryIs');
      if (!outer) return [];
      return [{
        type: 'Polygon',
        coordinates: [ring(outer), ...children(el, 'innerBoundaryIs').map(ring)],
      }];
    }
    case 'MultiGeometry':
    case 'MultiTrack':
      return el.children.flatMap(geometries);
    case 'Track':
      return [{
        type: 'LineString',
        coordinates: children(el, 'coord').map((c) => textOf(c).split(/\s+/).slice(0, 2).map(Number)),
      }];
    default:
      return [];
  }
}

function placemarkFeatures(pm) {
  const properties = {};
  const name = textOf(child(pm, 'name'));
  const description = textOf(child(pm, 'description'));
  if (name) properties.name = name;
  if (description) properties.description = description;
  return pm.children
    .flatMap(geometries)
    .filter((g) => g.coordinates && g.coordinates.length && !g.coordinates.flat(2).some(Number.isNaN))
    .map((geometry) => ({ type: 'Feature', geometry, properties: { ...properties } }));
}

export function parseKml(text, fileName = 'KML') {
  const root = parseXml(text);
  const doc = child(root, 'Document') ?? root;
  const layers = [];

  function walk(container, path) {
    const features = children(container, 'Placemark').flatMap(placemarkFeatures);
    const folders = children(container, 'Folder');
    if (path || features.length) {
      const docName = textOf(child(container, 'name')) || fileName;
      layers.push({ name: path || docName, features });
    }
    for (const f of folders) {
      const name = textOf(child(f, 'name')) || 'Folder';
      walk(f, path ? `${path} / ${name}` : name);
    }
    // Nested Documents behave like folders.
    for (const d of children(container, 'Document')) walk(d, path || textOf(child(d, 'name')) || fileName);
  }

  walk(doc, '');
  return { layers };
}
