// Section lines: a named polyline of two or more points, drawn on the map for
// a cross section. Pure (no DOM, no map, no network) so it can be tested with
// `node --test`; web/section-ui.js draws and edits it. Lengths are measured in
// SC State Plane feet (NAD83, international feet), as in the status bar.
import { formatCoords } from './geo.js';
import { formatStatePlane, toStatePlane } from './stateplane.js';

export const STORAGE_KEY = 'sc-geo:sections';
const DECIMALS = 1e7; // 7 decimal places of a degree: about a centimetre

const round = (v) => Math.round(v * DECIMALS) / DECIMALS;
const point = ([lng, lat]) => [round(lng), round(lat)];
const validPoint = (p) => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])
  && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90;
const FEET = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const MILES = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const FT_PER_MILE = 5280;

// A new, empty line. `existing` (saved lines) picks a default name not yet used.
export function newLine({ id, name = null, existing = [], now = null } = {}) {
  let n = existing.length + 1;
  const used = new Set(existing.map((l) => l.name));
  while (used.has(`Section ${n}`)) n += 1;
  return { id, name: name || `Section ${n}`, coords: [], created: now, updated: now };
}

const withCoords = (line, coords) => ({ ...line, coords });

export function addVertex(line, lngLat) {
  return withCoords(line, [...line.coords, point(lngLat)]);
}

export function moveVertex(line, i, lngLat) {
  if (i < 0 || i >= line.coords.length) return line;
  return withCoords(line, line.coords.map((c, j) => (j === i ? point(lngLat) : c)));
}

export function deleteVertex(line, i) {
  if (i < 0 || i >= line.coords.length) return line;
  return withCoords(line, line.coords.filter((_, j) => j !== i));
}

export const canFinish = (line) => (line?.coords?.length ?? 0) >= 2;

// Index of the screen point (`{x, y}`, vertices projected to pixels) nearest
// `at` within `tolerance` pixels, or -1.
export function hitVertex(points, at, tolerance = 8) {
  let best = -1;
  let bestD = tolerance;
  points.forEach((p, i) => {
    const d = Math.hypot(p.x - at.x, p.y - at.y);
    if (d <= bestD) { best = i; bestD = d; }
  });
  return best;
}

// Length along the line, in SC State Plane feet.
export function lengthFeet(coords) {
  let total = 0;
  for (let i = 1; i < coords.length; i += 1) {
    const a = toStatePlane(...coords[i - 1]);
    const b = toStatePlane(...coords[i]);
    total += Math.hypot(b.e - a.e, b.n - a.n);
  }
  return total;
}

// "18,432 ft (3.49 mi)"; miles only from a tenth of a mile.
export function formatLength(feet) {
  const ft = `${FEET.format(feet)} ft`;
  return feet >= FT_PER_MILE / 10 ? `${ft} (${MILES.format(feet / FT_PER_MILE)} mi)` : ft;
}

// One row per vertex: number, State Plane, lat/lon, distance along the line.
export function vertexRows(coords) {
  return coords.map((c, i) => ({
    label: String(i + 1),
    stateplane: formatStatePlane(c[0], c[1]),
    latlon: formatCoords(c[0], c[1]),
    along: `${FEET.format(lengthFeet(coords.slice(0, i + 1)))} ft`,
  }));
}

export function toGeoJSON(line) {
  return {
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: line.coords.map(point) },
    properties: {
      name: line.name,
      length_ft: Math.round(lengthFeet(line.coords)),
      length_basis: 'SC State Plane (NAD83), international feet',
      created: line.created ?? null,
      updated: line.updated ?? null,
      crs: 'WGS84 / NAD83 longitude, latitude (degrees)',
    },
  };
}

function lineString(obj) {
  if (obj?.type === 'FeatureCollection') {
    const f = (obj.features ?? []).find((x) => x?.geometry?.type === 'LineString');
    if (!f) throw new Error('No LineString in the GeoJSON file');
    return { geometry: f.geometry, properties: f.properties ?? {} };
  }
  if (obj?.type === 'Feature') return { geometry: obj.geometry, properties: obj.properties ?? {} };
  return { geometry: obj, properties: {} };
}

// A line from GeoJSON text or an object (Feature, FeatureCollection or a bare
// LineString). Throws an Error with a message for the user on bad input.
export function fromGeoJSON(input, { id, name = null, now = null } = {}) {
  let obj = input;
  if (typeof input === 'string') {
    try { obj = JSON.parse(input); } catch { throw new Error('Not a GeoJSON file'); }
  }
  const { geometry, properties } = lineString(obj);
  if (geometry?.type !== 'LineString') throw new Error('The GeoJSON file holds no LineString');
  const coords = geometry.coordinates ?? [];
  if (!Array.isArray(coords) || coords.length < 2) throw new Error('A section line needs at least two points');
  if (!coords.every(validPoint)) throw new Error('A point has an invalid longitude or latitude');
  return { id, name: name || String(properties.name || '').trim() || 'Imported section', coords: coords.map(point),
    created: now, updated: now };
}

const validLine = (l) => l && typeof l.id === 'string' && typeof l.name === 'string' && Array.isArray(l.coords)
  && l.coords.length >= 2 && l.coords.every(validPoint);

// Saved lines in localStorage (`storage`), with an in-memory copy so the
// viewer works when storage is missing, blocked or full.
export function createStore(storage) {
  let persistent = Boolean(storage);
  let lines = [];
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    lines = Array.isArray(parsed) ? parsed.filter(validLine) : [];
  } catch {
    persistent = false;
    lines = [];
  }
  const flush = () => {
    if (!storage) return;
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(lines));
      persistent = true;
    } catch {
      persistent = false;
    }
  };
  const copy = (l) => (l ? { ...l, coords: l.coords.map((c) => [...c]) } : null);
  return {
    get persistent() { return persistent; },
    list: () => lines.map(copy),
    get: (id) => copy(lines.find((l) => l.id === id)),
    save(line) {
      const clean = copy(line);
      const i = lines.findIndex((l) => l.id === clean.id);
      if (i >= 0) lines[i] = clean; else lines.push(clean);
      flush();
    },
    rename(id, name) {
      const l = lines.find((x) => x.id === id);
      const trimmed = String(name ?? '').trim();
      if (!l || !trimmed) return;
      l.name = trimmed;
      flush();
    },
    remove(id) {
      lines = lines.filter((l) => l.id !== id);
      flush();
    },
  };
}
