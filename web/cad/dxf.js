// ASCII DXF -> layers. Layers from the LAYER table are kept even when empty.
// Supported entities: LINE, POINT, CIRCLE, ARC, ELLIPSE, LWPOLYLINE, POLYLINE,
// TEXT, MTEXT, INSERT and DIMENSION (block expansion), SOLID, TRACE, 3DFACE and
// SPLINE (control/fit points, marked approximate). Paper-space entities are
// skipped because they are not in drawing coordinates. Others are counted in
// `skipped`.
import { arcPoints, bulgePoints, ccwSweep, closeRing, ellipsePoints } from './geometry.js';

const INSUNITS = { 1: 'in', 2: 'ft', 6: 'm', 21: 'usft' };
const MAX_BLOCK_DEPTH = 8;

function readPairs(text) {
  const lines = text.split(/\r?\n/);
  const pairs = [];
  for (let i = 0; i + 1 < lines.length; i += 2) {
    const code = parseInt(lines[i], 10);
    if (Number.isNaN(code)) throw new Error(`Bad DXF group code on line ${i + 1}`);
    pairs.push([code, lines[i + 1].trim()]);
  }
  return pairs;
}

// Split pairs into entities: each starts at a code-0 pair.
function splitEntities(pairs, start, stopValue) {
  const ents = [];
  let i = start;
  while (i < pairs.length && !(pairs[i][0] === 0 && stopValue.includes(pairs[i][1]))) {
    const ent = { type: pairs[i][1], codes: [] };
    i++;
    while (i < pairs.length && pairs[i][0] !== 0) ent.codes.push(pairs[i++]);
    ents.push(ent);
  }
  return [ents, i];
}

const get = (e, code, dflt) => {
  const p = e.codes.find((c) => c[0] === code);
  return p ? p[1] : dflt;
};
const num = (e, code, dflt = 0) => {
  const v = get(e, code);
  return v === undefined ? dflt : Number(v);
};

function mtextPlain(s) {
  return s
    .replace(/\\P/g, '\n')
    .replace(/\\[A-Za-z][^;\\{}]*;/g, '')
    .replace(/\\[LlOoKk]/g, '')
    .replace(/[{}]/g, '')
    .trim();
}

// OCS -> WCS for the common mirrored case (extrusion 0,0,-1).
function ocs(e) {
  return num(e, 230, 1) < 0 ? ([x, y]) => [-x, y] : (p) => p;
}

function lwpolyline(e) {
  const verts = [];
  for (const [code, v] of e.codes) {
    if (code === 10) verts.push({ x: Number(v), y: 0, bulge: 0 });
    else if (code === 20 && verts.length) verts[verts.length - 1].y = Number(v);
    else if (code === 42 && verts.length) verts[verts.length - 1].bulge = Number(v);
  }
  return polylineGeometry(verts, (num(e, 70) & 1) === 1, ocs(e));
}

function polylineGeometry(verts, closed, toWcs) {
  if (verts.length < 2) return null;
  const pts = [];
  const n = verts.length;
  const segs = closed ? n : n - 1;
  for (let i = 0; i < n; i++) {
    const a = [verts[i].x, verts[i].y];
    pts.push(a);
    if (i < segs) {
      const b = verts[(i + 1) % n];
      pts.push(...bulgePoints(a, [b.x, b.y], verts[i].bulge));
    }
  }
  if (closed) pts.push(pts[0]);
  return { type: 'LineString', coordinates: pts.map(toWcs) };
}

function quad(e) {
  const p = [10, 11, 12, 13].map((c) => [num(e, c), num(e, c + 10)]);
  // SOLID and TRACE store corners in Z order.
  const ring = e.type === '3DFACE' ? p : [p[0], p[1], p[3], p[2]];
  const toWcs = e.type === '3DFACE' ? (q) => q : ocs(e);
  const uniq = ring.filter((q, i) => i === 0 || q[0] !== ring[i - 1][0] || q[1] !== ring[i - 1][1]);
  return { type: 'Polygon', coordinates: [closeRing(uniq.map(toWcs))] };
}

function spline(e) {
  const fit = [];
  const ctrl = [];
  for (const [code, v] of e.codes) {
    if (code === 10) ctrl.push([Number(v), 0]);
    else if (code === 20 && ctrl.length) ctrl[ctrl.length - 1][1] = Number(v);
    else if (code === 11) fit.push([Number(v), 0]);
    else if (code === 21 && fit.length) fit[fit.length - 1][1] = Number(v);
  }
  const pts = fit.length >= 2 ? fit : ctrl;
  return pts.length >= 2 ? { type: 'LineString', coordinates: pts } : null;
}

// Geometry for one simple entity, in its own coordinates.
function entityGeometry(e) {
  switch (e.type) {
    case 'LINE':
      return { type: 'LineString', coordinates: [[num(e, 10), num(e, 20)], [num(e, 11), num(e, 21)]] };
    case 'POINT':
      return { type: 'Point', coordinates: [num(e, 10), num(e, 20)] };
    case 'CIRCLE':
      return { type: 'LineString', coordinates: arcPoints(num(e, 10), num(e, 20), num(e, 40), 0, 360).map(ocs(e)) };
    case 'ARC': {
      const s = num(e, 50);
      return {
        type: 'LineString',
        coordinates: arcPoints(num(e, 10), num(e, 20), num(e, 40), s, ccwSweep(s, num(e, 51))).map(ocs(e)),
      };
    }
    case 'ELLIPSE':
      return {
        type: 'LineString',
        coordinates: ellipsePoints(num(e, 10), num(e, 20), num(e, 11), num(e, 21), num(e, 40, 1),
          num(e, 41, 0), num(e, 42, 2 * Math.PI)),
      };
    case 'LWPOLYLINE':
      return lwpolyline(e);
    case 'TEXT':
    case 'MTEXT':
      return { type: 'Point', coordinates: ocs(e)([num(e, 10), num(e, 20)]) };
    case 'SOLID':
    case 'TRACE':
    case '3DFACE':
      return quad(e);
    case 'SPLINE':
      return spline(e);
    default:
      return null;
  }
}

function entityText(e) {
  if (e.type === 'TEXT') return get(e, 1, '');
  if (e.type === 'MTEXT') {
    const parts = e.codes.filter(([c]) => c === 3 || c === 1).map(([, v]) => v);
    return mtextPlain(parts.join(''));
  }
  return undefined;
}

function transformGeometry(g, f) {
  const map = (c) => (typeof c[0] === 'number' ? f(c) : c.map(map));
  return { type: g.type, coordinates: map(g.coordinates) };
}

export function parseDxf(text) {
  if (text.startsWith('AutoCAD Binary DXF')) throw new Error('Binary DXF is not supported');
  const pairs = readPairs(text);
  const layers = new Map();
  const blocks = new Map();
  const skipped = {};
  let units = null;
  let entities = [];

  const layer = (name) => {
    if (!layers.has(name)) layers.set(name, { name, features: [] });
    return layers.get(name);
  };

  for (let i = 0; i < pairs.length; i++) {
    if (!(pairs[i][0] === 0 && pairs[i][1] === 'SECTION')) continue;
    const section = pairs[i + 1]?.[1];
    const [ents, end] = splitEntities(pairs, i + 2, ['ENDSEC']);
    i = end;
    if (section === 'HEADER') {
      // Header variables are code 9 names followed by values.
      const all = pairs.slice(0, end);
      const idx = all.findIndex(([c, v]) => c === 9 && v === '$INSUNITS');
      if (idx >= 0) units = INSUNITS[all[idx + 1][1]] ?? null;
    } else if (section === 'TABLES') {
      for (const e of ents) {
        if (e.type !== 'LAYER') continue;
        const name = get(e, 2);
        if (name === undefined) continue;
        const l = layer(name);
        if (num(e, 62, 1) < 0 || (num(e, 70) & 1) === 1) l.off = true;
      }
    } else if (section === 'BLOCKS') {
      let current = null;
      for (const e of ents) {
        if (e.type === 'BLOCK') {
          current = { name: get(e, 2), base: [num(e, 10), num(e, 20)], entities: [] };
        } else if (e.type === 'ENDBLK') {
          if (current) blocks.set(current.name, current);
          current = null;
        } else if (current) current.entities.push(e);
      }
    } else if (section === 'ENTITIES') {
      entities = ents;
    }
  }

  function emit(ents, xform, depth, inherited) {
    let k = 0;
    while (k < ents.length) {
      const e = ents[k++];
      if (num(e, 67) === 1) {
        skipped.paperSpace = (skipped.paperSpace ?? 0) + 1;
        continue;
      }
      let lname = get(e, 8, '0');
      if (inherited && lname === '0') lname = inherited.layer;
      const props = { layer: lname, entity: e.type };
      if (inherited) props.block = inherited.block;
      const handle = get(e, 5);
      if (handle) props.handle = handle;

      if (e.type === 'POLYLINE') {
        const verts = [];
        while (k < ents.length && ents[k].type === 'VERTEX') {
          const v = ents[k++];
          verts.push({ x: num(v, 10), y: num(v, 20), bulge: num(v, 42), flags: num(v, 70) });
        }
        if (k < ents.length && ents[k].type === 'SEQEND') k++;
        const flags = num(e, 70);
        if (flags & (16 | 64)) {
          skipped.MESH = (skipped.MESH ?? 0) + 1;
          continue;
        }
        const g = polylineGeometry(verts, (flags & 1) === 1, (flags & 8) ? (p) => p : ocs(e));
        if (g) layer(lname).features.push({ type: 'Feature', geometry: transformGeometry(g, xform), properties: props });
        continue;
      }
      if (e.type === 'INSERT' || e.type === 'DIMENSION') {
        const block = blocks.get(get(e, 2));
        if (!block || depth >= MAX_BLOCK_DEPTH) {
          skipped[e.type] = (skipped[e.type] ?? 0) + 1;
          continue;
        }
        let inner = xform;
        if (e.type === 'INSERT') {
          const [bx, by] = block.base;
          const sx = num(e, 41, 1);
          const sy = num(e, 42, 1);
          const rot = (num(e, 50) * Math.PI) / 180;
          const [ix, iy] = ocs(e)([num(e, 10), num(e, 20)]);
          const cos = Math.cos(rot);
          const sin = Math.sin(rot);
          inner = ([x, y]) => {
            const lx = (x - bx) * sx;
            const ly = (y - by) * sy;
            return xform([ix + lx * cos - ly * sin, iy + lx * sin + ly * cos]);
          };
        }
        emit(block.entities, inner, depth + 1, { layer: lname, block: block.name });
        continue;
      }
      const g = entityGeometry(e);
      if (!g) {
        skipped[e.type] = (skipped[e.type] ?? 0) + 1;
        continue;
      }
      const text = entityText(e);
      if (text !== undefined) props.text = text;
      if (e.type === 'SPLINE') props.approximate = true;
      layer(lname).features.push({ type: 'Feature', geometry: transformGeometry(g, xform), properties: props });
    }
  }

  emit(entities, (p) => p, 0, null);
  return { layers: [...layers.values()], units, skipped };
}
