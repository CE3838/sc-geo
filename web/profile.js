// Ground profile along a section line from USGS 3DEP (the Elevation Point
// Query Service the click callout uses, web/elevation.js). Pure logic, no DOM:
// sampling, a cache, a gentle batch fetch and the chart geometry;
// web/section-ui.js draws it.
//
// Traffic: nothing is fetched until the user asks for a profile; samples are
// capped (MAX_SAMPLES) and no closer than MIN_SPACING_FT; at most
// CONCURRENCY requests run at once, each worker pausing DELAY_MS between
// requests; every elevation is cached per rounded coordinate (memory and
// localStorage), so a profile asked for again sends nothing. A point the
// service fails on stays a gap and is asked again next time; nothing is
// interpolated or invented.
import { EPQS_CITATION, elevationAt as epqsElevationAt } from './elevation.js';
import { niceTicks } from './water-chart.js';
import { fromStatePlane, toStatePlane } from './stateplane.js';

export const MAX_SAMPLES = 100;
export const MIN_SPACING_FT = 30;
export const CONCURRENCY = 3;
export const DELAY_MS = 150;
export const CACHE_KEY = 'sc-geo:elevations';
export const CACHE_MAX = 5000;
export const DATUM = Object.freeze({
  vertical: 'NAVD88',
  units: 'ft',
  label: 'Elevation, ft (NAVD88)',
  note: 'Bare-earth elevations in feet (NAVD88) as returned by the USGS Elevation Point Query Service (3DEP).',
});

const KEY_DECIMALS = 5; // about a metre

export function cacheKey(lng, lat) {
  return `${lng.toFixed(KEY_DECIMALS)},${lat.toFixed(KEY_DECIMALS)}`;
}

// Evenly spaced samples along the line (`d`: feet along it, SC State Plane),
// both ends included: one every MIN_SPACING_FT or more, at most `maxSamples`.
export function samplePoints(coords, { maxSamples = MAX_SAMPLES, minSpacingFt = MIN_SPACING_FT } = {}) {
  if (!coords || coords.length < 2) return [];
  const plane = coords.map(([lng, lat]) => toStatePlane(lng, lat));
  const cum = [0];
  for (let i = 1; i < plane.length; i += 1) {
    cum.push(cum[i - 1] + Math.hypot(plane[i].e - plane[i - 1].e, plane[i].n - plane[i - 1].n));
  }
  const total = cum.at(-1);
  const count = Math.max(2, Math.min(maxSamples, Math.floor(total / minSpacingFt) + 1));
  const out = [];
  let seg = 1;
  for (let k = 0; k < count; k += 1) {
    const d = k === count - 1 ? total : (total * k) / (count - 1);
    if (k === 0) { out.push({ d: 0, lng: coords[0][0], lat: coords[0][1] }); continue; }
    if (k === count - 1) { out.push({ d: total, lng: coords.at(-1)[0], lat: coords.at(-1)[1] }); continue; }
    while (seg < cum.length - 1 && cum[seg] < d) seg += 1;
    const len = cum[seg] - cum[seg - 1];
    const f = len > 0 ? (d - cum[seg - 1]) / len : 0;
    const e = plane[seg - 1].e + f * (plane[seg].e - plane[seg - 1].e);
    const n = plane[seg - 1].n + f * (plane[seg].n - plane[seg - 1].n);
    const { lng, lat } = fromStatePlane(e, n);
    out.push({ d, lng, lat });
  }
  return out;
}

// Elevations by rounded coordinate: feet, or null where the service has no
// data. Kept in memory and, when allowed, in localStorage (`storage`).
export function createElevationCache(storage, { key = CACHE_KEY, max = CACHE_MAX } = {}) {
  let map = new Map();
  try {
    const raw = storage?.getItem(key);
    const obj = raw ? JSON.parse(raw) : {};
    if (obj && typeof obj === 'object') {
      for (const [k, v] of Object.entries(obj)) if (v === null || Number.isFinite(v)) map.set(k, v);
    }
  } catch { map = new Map(); }
  return {
    get: (k) => map.get(k),
    set(k, v) {
      map.delete(k);
      map.set(k, v);
      while (map.size > max) map.delete(map.keys().next().value);
    },
    flush() {
      if (!storage) return;
      try { storage.setItem(key, JSON.stringify(Object.fromEntries(map))); } catch { /* blocked or full: memory only */ }
    },
    get size() { return map.size; },
  };
}

const abortError = () => Object.assign(new Error('Profile stopped'), { name: 'AbortError' });

function sleep(ms, signal) {
  if (!ms) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve(); }, ms);
    function onAbort() { clearTimeout(t); reject(abortError()); }
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

// Elevation at every sample. Points: {d, lng, lat, feet, status}, status
// 'ok' | 'cached' | 'nodata' (the service has no data there) | 'failed'
// (request failed: a gap, not cached). Rejects with an AbortError when
// `signal` aborts; elevations already received stay cached.
export async function fetchProfile(samples, {
  elevationAt = epqsElevationAt, cache, concurrency = CONCURRENCY, delayMs = DELAY_MS, signal, onProgress,
} = {}) {
  const points = samples.map((s) => ({ ...s, feet: null, status: 'pending' }));
  const todo = [];
  points.forEach((p, i) => {
    const hit = cache?.get(cacheKey(p.lng, p.lat));
    if (hit === undefined) todo.push(i);
    else Object.assign(p, { feet: hit, status: hit === null ? 'nodata' : 'cached' });
  });
  let requests = 0;
  let next = 0;
  let done = points.length - todo.length;
  const report = () => onProgress?.({ done, total: points.length });

  async function worker() {
    while (next < todo.length) {
      if (signal?.aborted) throw abortError();
      const p = points[todo[next++]];
      requests += 1;
      try {
        const r = await elevationAt(p.lng, p.lat, { signal });
        const feet = r && Number.isFinite(r.feet) ? r.feet : null;
        Object.assign(p, { feet, status: feet === null ? 'nodata' : 'ok' });
        cache?.set(cacheKey(p.lng, p.lat), feet);
      } catch (err) {
        if (signal?.aborted) throw abortError();
        Object.assign(p, { feet: null, status: 'failed', error: err.message });
      }
      done += 1;
      report();
      if (next < todo.length) await sleep(delayMs, signal);
    }
  }

  report();
  try {
    await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, todo.length)) }, worker));
  } finally {
    cache?.flush();
  }
  return {
    points, datum: DATUM, source: EPQS_CITATION, requests,
    failed: points.filter((p) => p.status === 'failed').length,
  };
}

// Chart geometry (pixels) for an SVG: axes, ticks, the profile path with
// gaps, and the vertical exaggeration. null when no point has an elevation.
export function profileChart(points, { width = 280, height = 160, margin = { l: 44, r: 18, t: 8, b: 30 } } = {}) {
  const valid = points.filter((p) => Number.isFinite(p.feet));
  if (!valid.length) return null;
  const plot = { x: margin.l, y: margin.t, w: width - margin.l - margin.r, h: height - margin.t - margin.b };
  const maxD = Math.max(...points.map((p) => p.d));
  const x = niceTicks(0, maxD || 1, 4);
  const y = niceTicks(Math.min(...valid.map((p) => p.feet)), Math.max(...valid.map((p) => p.feet)), 4);
  const px = (d) => plot.x + ((d - x.lo) / (x.hi - x.lo)) * plot.w;
  const py = (f) => plot.y + plot.h - ((f - y.lo) / (y.hi - y.lo)) * plot.h;
  const segments = [];
  let cur = [];
  for (const p of points) {
    if (Number.isFinite(p.feet)) cur.push([px(p.d), py(p.feet)]);
    else if (cur.length) { segments.push(cur); cur = []; }
  }
  if (cur.length) segments.push(cur);
  const path = segments.map((s) => s.map(([a, b], i) => `${i ? 'L' : 'M'}${a.toFixed(1)} ${b.toFixed(1)}`).join(' ')).join(' ');
  const exaggeration = (plot.h / (y.hi - y.lo)) / (plot.w / (x.hi - x.lo));
  const ve = exaggeration >= 10 ? Math.round(exaggeration).toLocaleString('en-US') : exaggeration.toFixed(1);
  return {
    width, height, plot, x, y, segments, path, exaggeration,
    exaggerationText: `Vertical exaggeration ×${ve}`,
    xTicks: x.ticks.map((v) => ({ v, pos: px(v), label: v.toLocaleString('en-US') })),
    yTicks: y.ticks.map((v) => ({ v, pos: py(v), label: v.toLocaleString('en-US') })),
    xLabel: 'Distance along the line, ft',
    yLabel: DATUM.label,
    gaps: points.filter((p) => !Number.isFinite(p.feet)).map((p) => ({ d: p.d, pos: px(p.d), status: p.status })),
  };
}
