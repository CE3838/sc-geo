// LandXML -> layers. Coordinates in LandXML are "northing easting [elevation]";
// they are returned as [easting, northing]. Layers: one per CgPoints group,
// Alignment, Parcel, PlanFeature and Surface (TIN faces as a MultiPolygon).
// Spirals are drawn through their PI and marked approximate.
import { arcPoints, closeRing } from './geometry.js';
import { child, children, descendants, parseXml, textOf } from './xml.js';

const LINEAR_UNITS = {
  USSurveyFoot: 'usft',
  foot: 'ft',
  internationalFoot: 'ft',
  meter: 'm',
  metre: 'm',
};

const ne = (s) => {
  const [n, e] = s.trim().split(/\s+/).map(Number);
  return [e, n];
};

export function parseLandXml(text) {
  const root = parseXml(text);
  if (root.name !== 'LandXML') throw new Error('Not a LandXML file');
  const unitsEl = child(root, 'Units');
  const unitEl = unitsEl && (child(unitsEl, 'Imperial') ?? child(unitsEl, 'Metric'));
  const units = unitEl ? LINEAR_UNITS[unitEl.attrs.linearUnit] ?? null : null;
  const csEl = child(root, 'CoordinateSystem');
  const epsg = csEl?.attrs.epsgCode ? Number(csEl.attrs.epsgCode) : null;

  const named = new Map();
  for (const p of descendants(root, 'CgPoint')) {
    if (p.attrs.name && textOf(p)) named.set(p.attrs.name, ne(textOf(p)));
  }
  const pointOf = (el) => {
    if (!el) return null;
    if (el.attrs.pntRef) return named.get(el.attrs.pntRef) ?? null;
    return textOf(el) ? ne(textOf(el)) : null;
  };

  // CoordGeom -> { pts, approximate }
  function coordGeom(cg) {
    const pts = [];
    let approximate = false;
    const push = (list) => {
      for (const p of list) {
        const last = pts[pts.length - 1];
        if (!last || Math.hypot(last[0] - p[0], last[1] - p[1]) > 1e-9) pts.push(p);
      }
    };
    for (const g of cg.children) {
      const start = pointOf(child(g, 'Start'));
      const end = pointOf(child(g, 'End'));
      if (!start || !end) continue;
      if (g.name === 'Line') push([start, end]);
      else if (g.name === 'Curve') {
        const c = pointOf(child(g, 'Center'));
        if (!c) {
          push([start, end]);
          continue;
        }
        const r = Math.hypot(start[0] - c[0], start[1] - c[1]);
        const a0 = (Math.atan2(start[1] - c[1], start[0] - c[0]) * 180) / Math.PI;
        const a1 = (Math.atan2(end[1] - c[1], end[0] - c[0]) * 180) / Math.PI;
        let sweep = a1 - a0;
        if (g.attrs.rot === 'cw') {
          while (sweep >= 0) sweep -= 360;
        } else {
          while (sweep <= 0) sweep += 360;
        }
        push(arcPoints(c[0], c[1], r, a0, sweep));
      } else if (g.name === 'Spiral') {
        const pi = pointOf(child(g, 'PI'));
        push(pi ? [start, pi, end] : [start, end]);
        approximate = true;
      } else if (g.name === 'IrregularLine') {
        const list = textOf(child(g, 'PntList2D') ?? child(g, 'PntList3D'))
          .split(/\s+/).filter(Boolean).map(Number);
        const step = child(g, 'PntList3D') ? 3 : 2;
        const own = [];
        for (let i = 0; i + 1 < list.length; i += step) own.push([list[i + 1], list[i]]);
        push(own.length ? own : [start, end]);
      }
    }
    return { pts, approximate };
  }

  const layers = [];
  const feature = (geometry, properties) => ({ type: 'Feature', geometry, properties });

  for (const group of descendants(root, 'CgPoints')) {
    const features = children(group, 'CgPoint')
      .filter((p) => textOf(p))
      .map((p) => {
        const props = {};
        for (const k of ['name', 'code', 'desc']) if (p.attrs[k]) props[k] = p.attrs[k];
        return feature({ type: 'Point', coordinates: ne(textOf(p)) }, props);
      });
    layers.push({ name: `Points: ${group.attrs.name || 'CgPoints'}`, features });
  }

  const linear = (tag, label, closed) => {
    for (const el of descendants(root, tag)) {
      const name = el.attrs.name || label;
      const features = [];
      for (const cg of children(el, 'CoordGeom')) {
        const { pts, approximate } = coordGeom(cg);
        if (pts.length < 2) continue;
        const props = { name };
        if (approximate) props.approximate = true;
        const geometry = closed && pts.length >= 3
          ? { type: 'Polygon', coordinates: [closeRing(pts)] }
          : { type: 'LineString', coordinates: pts };
        features.push(feature(geometry, props));
      }
      layers.push({ name: `${label}: ${name}`, features });
    }
  };
  linear('Alignment', 'Alignment', false);
  linear('Parcel', 'Parcel', true);
  linear('PlanFeature', 'PlanFeature', false);

  for (const s of descendants(root, 'Surface')) {
    const def = child(s, 'Definition');
    const features = [];
    if (def) {
      const pnts = new Map(children(child(def, 'Pnts') ?? { children: [] }, 'P').map((p) => [p.attrs.id, ne(textOf(p))]));
      const polys = [];
      for (const f of children(child(def, 'Faces') ?? { children: [] }, 'F')) {
        if (f.attrs.i === '1') continue; // invisible face
        const ring = textOf(f).split(/\s+/).map((id) => pnts.get(id));
        if (ring.length >= 3 && ring.every(Boolean)) polys.push([closeRing(ring)]);
      }
      if (polys.length) features.push(feature({ type: 'MultiPolygon', coordinates: polys }, { name: s.attrs.name || 'Surface' }));
    }
    layers.push({ name: `Surface: ${s.attrs.name || 'Surface'}`, features });
  }

  return { layers, units, epsg };
}
