// Surface geology along a section line: where the line crosses the merged
// surficial and bedrock polygons already loaded in the viewer (no requests).
// Pure functions, no DOM; web/section-ui.js draws the strips above the
// ground profile, on the same distance axis (profile.js distanceAxis).
//
// Distances are feet along the line in SC State Plane, like the profile.
// Crossings are found in longitude/latitude on each straight segment, which
// is how the map draws the line. A stretch no merged polygon covers is a gap
// ("no mapped unit"): it is never filled from a neighbouring unit.
import { CONFIDENCE_STOPS } from './merged.js';
import { distanceAxis } from './profile.js';
import { toStatePlane } from './stateplane.js';

export const NO_UNIT = 'no mapped unit';
const EPS = 1e-12;

function polygonsOf(geometry) {
  if (geometry?.type === 'Polygon') return [geometry.coordinates];
  if (geometry?.type === 'MultiPolygon') return geometry.coordinates;
  return [];
}

const boxes = new WeakMap();
function bboxOf(feature) {
  let b = boxes.get(feature);
  if (!b) {
    b = [Infinity, Infinity, -Infinity, -Infinity];
    for (const poly of polygonsOf(feature.geometry)) {
      for (const [x, y] of poly[0] ?? []) {
        if (x < b[0]) b[0] = x; if (y < b[1]) b[1] = y; if (x > b[2]) b[2] = x; if (y > b[3]) b[3] = y;
      }
    }
    boxes.set(feature, b);
  }
  return b;
}

// Even-odd ray casting over every ring of each polygon part (holes count out).
// A point on a vertical edge belongs to the polygon on its east side.
function inside(geometry, x, y) {
  for (const poly of polygonsOf(geometry)) {
    let c = false;
    for (const ring of poly) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
        const [xi, yi] = ring[i];
        const [xj, yj] = ring[j];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
      }
    }
    if (c) return true;
  }
  return false;
}

// Parameters t (0..1) where segment a->b crosses the edges of a geometry.
function crossings(a, b, geometry, out) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  for (const poly of polygonsOf(geometry)) {
    for (const ring of poly) {
      for (let i = 1; i < ring.length; i += 1) {
        const [x1, y1] = ring[i - 1];
        const [x2, y2] = ring[i];
        const ex = x2 - x1;
        const ey = y2 - y1;
        const den = dx * ey - dy * ex;
        if (Math.abs(den) < EPS) continue;  // parallel or collinear: no single crossing
        const t = ((x1 - a[0]) * ey - (y1 - a[1]) * ex) / den;
        const u = ((x1 - a[0]) * dy - (y1 - a[1]) * dx) / den;
        if (t > 0 && t < 1 && u >= -1e-12 && u <= 1 + 1e-12) out.push(t);
      }
    }
  }
}

const gapInterval = (from, to) => ({ from, to, mapped: false, label: NO_UNIT, symbol: null, name: null, color: null,
  conf: null, citation: null, key: null });

// Ordered intervals covering the whole line. `describe(props)` gives
// {key, symbol, name, citation}; `color(props)` the map color. Neighbouring
// pieces with the same key are merged.
export function intervalsAlong(coords, features, { describe, color }) {
  if (!coords || coords.length < 2) return [];
  const lb = [Math.min(...coords.map((c) => c[0])), Math.min(...coords.map((c) => c[1])),
    Math.max(...coords.map((c) => c[0])), Math.max(...coords.map((c) => c[1]))];
  const cand = (features ?? []).filter((f) => {
    const b = bboxOf(f);
    return b[0] <= lb[2] && lb[0] <= b[2] && b[1] <= lb[3] && lb[1] <= b[3];
  });
  const raw = [];
  let start = 0;
  for (let i = 1; i < coords.length; i += 1) {
    const a = coords[i - 1];
    const b = coords[i];
    const pa = toStatePlane(...a);
    const pb = toStatePlane(...b);
    const len = Math.hypot(pb.e - pa.e, pb.n - pa.n);
    const ts = [0, 1];
    const sb = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
    for (const f of cand) {
      const fb = bboxOf(f);
      if (fb[0] <= sb[2] && sb[0] <= fb[2] && fb[1] <= sb[3] && sb[1] <= fb[3]) crossings(a, b, f.geometry, ts);
    }
    ts.sort((x, y) => x - y);
    for (let k = 1; k < ts.length; k += 1) {
      const t0 = ts[k - 1];
      const t1 = ts[k];
      if (t1 - t0 < 1e-9) continue;
      const tm = (t0 + t1) / 2;
      const mx = a[0] + tm * (b[0] - a[0]);
      const my = a[1] + tm * (b[1] - a[1]);
      const hit = cand.find((f) => inside(f.geometry, mx, my)) ?? null;
      raw.push({ from: start + t0 * len, to: start + t1 * len, feature: hit });
    }
    start += len;
  }
  const out = [];
  for (const r of raw) {
    const p = r.feature?.properties;
    const d = p ? describe(p) : null;
    const key = d?.key ?? null;
    const last = out.at(-1);
    if (last && last.key === key && (key !== null || !last.mapped)) { last.to = r.to; continue; }
    out.push(p ? { from: r.from, to: r.to, mapped: true, label: [d.symbol, d.name].filter(Boolean).join(' '),
      symbol: d.symbol ?? null, name: d.name ?? null, color: color(p), conf: typeof p.conf === 'number' ? p.conf : null,
      citation: d.citation ?? null, key } : gapInterval(r.from, r.to));
  }
  if (out.length) { out[0].from = 0; out.at(-1).to = start; }
  return out;
}

const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
const toHex = (rgb) => `#${rgb.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;

// The color a polygon has on the map in the current color mode (merged-ui.js).
export function colorForProps(p, mode, legend) {
  if (mode === 'confidence') {
    const v = typeof p.conf === 'number' ? p.conf : 0;
    const stops = CONFIDENCE_STOPS;
    if (v <= stops[0][0]) return stops[0][1];
    for (let i = 1; i < stops.length; i += 1) {
      if (v <= stops[i][0]) {
        const f = (v - stops[i - 1][0]) / (stops[i][0] - stops[i - 1][0]);
        const a = hex(stops[i - 1][1]);
        const b = hex(stops[i][1]);
        return toHex(a.map((x, k) => x + f * (b[k] - x)));
      }
    }
    return stops.at(-1)[1];
  }
  const classes = (mode === 'material' ? legend?.material : legend?.age) ?? [];
  const prop = mode === 'material' ? p.material_class : p.age_class;
  return (classes.find((c) => c.id === prop) ?? classes.find((c) => c.id === 'Unknown') ?? { color: '#bdbdbd' }).color;
}

// Rectangles for one strip, on the profile's distance axis.
export function stripLayout(intervals, lengthFt, { width = 280 } = {}) {
  const axis = distanceAxis(lengthFt, width);
  return {
    plot: axis.plot,
    ticks: axis.ticks,
    rects: intervals.map((i) => ({ ...i, x: axis.px(i.from), w: axis.px(i.to) - axis.px(i.from) })),
  };
}
