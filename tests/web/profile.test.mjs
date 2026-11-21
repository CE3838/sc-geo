import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  DATUM, MAX_SAMPLES, MIN_SPACING_FT, cacheKey, createElevationCache, fetchProfile, profileChart, samplePoints,
} from '../../web/profile.js';
import { lengthFeet } from '../../web/section.js';

const A = [-79.96, 32.86];
const B = [-79.9, 32.86];   // about 18,400 ft east of A
const C = [-79.9, 32.9];

test('samples are evenly spaced along the line, end points included', () => {
  const s = samplePoints([A, B]);
  const L = lengthFeet([A, B]);
  assert.equal(s[0].d, 0);
  assert.ok(Math.abs(s.at(-1).d - L) < 1e-6);
  assert.ok(Math.abs(s[0].lng - A[0]) < 1e-9 && Math.abs(s.at(-1).lng - B[0]) < 1e-7);
  const gaps = s.slice(1).map((p, i) => p.d - s[i].d);
  assert.ok(gaps.every((g) => Math.abs(g - gaps[0]) < 1e-6));
  assert.ok(gaps[0] >= MIN_SPACING_FT);
});

test('the number of samples scales with length and is capped', () => {
  const short = samplePoints([A, [A[0] + 0.001, A[1]]]);   // about 300 ft
  assert.ok(short.length >= 2 && short.length <= Math.floor(310 / MIN_SPACING_FT) + 1);
  const long = samplePoints([A, B, C]);
  assert.equal(long.length, MAX_SAMPLES);
  const tiny = samplePoints([A, [A[0] + 0.00001, A[1]]]);  // about 3 ft
  assert.equal(tiny.length, 2);
  assert.deepEqual(samplePoints([A]), []);
});

test('samples follow a bent line through its corner', () => {
  const s = samplePoints([A, B, C], { maxSamples: 400 });
  const corner = s.find((p) => Math.abs(p.d - lengthFeet([A, B])) < 60);
  assert.ok(corner && Math.abs(corner.lng - B[0]) < 0.001 && Math.abs(corner.lat - B[1]) < 0.001);
});

test('cache keys round to about a metre', () => {
  assert.equal(cacheKey(-79.9600001, 32.8600004), cacheKey(-79.96, 32.86));
  assert.notEqual(cacheKey(-79.96, 32.86), cacheKey(-79.9601, 32.86));
});

function fakeStorage() {
  const data = new Map();
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)) };
}

const okFetch = (log) => async (lng, lat) => {
  log.push([lng, lat]);
  return { feet: Math.round(lat * 100) / 10, source_id: 'usgs-3dep-epqs' };
};

test('fetchProfile asks once per point, caches, and states the datum', async () => {
  const samples = samplePoints([A, B], { maxSamples: 6 });
  const storage = fakeStorage();
  const log = [];
  const cache = createElevationCache(storage);
  const p1 = await fetchProfile(samples, { elevationAt: okFetch(log), cache, delayMs: 0 });
  assert.equal(log.length, 6);
  assert.equal(p1.requests, 6);
  assert.deepEqual(p1.datum, DATUM);
  assert.equal(DATUM.vertical, 'NAVD88');
  assert.equal(DATUM.units, 'ft');
  assert.equal(p1.source, 'USGS 3DEP');
  assert.ok(p1.points.every((p) => typeof p.feet === 'number' && p.status === 'ok'));
  // Same line again, and a new page load (fresh cache on the same storage): no requests.
  const p2 = await fetchProfile(samples, { elevationAt: okFetch(log), cache, delayMs: 0 });
  const p3 = await fetchProfile(samples, { elevationAt: okFetch(log), cache: createElevationCache(storage), delayMs: 0 });
  assert.equal(log.length, 6);
  assert.equal(p2.requests + p3.requests, 0);
  assert.ok(p3.points.every((p) => p.status === 'cached'));
});

test('no more than `concurrency` requests run at once', async () => {
  let running = 0;
  let peak = 0;
  const slow = async () => {
    running += 1; peak = Math.max(peak, running);
    await new Promise((r) => setTimeout(r, 5));
    running -= 1;
    return { feet: 10 };
  };
  const samples = samplePoints([A, B], { maxSamples: 12 });
  await fetchProfile(samples, { elevationAt: slow, cache: createElevationCache(null), concurrency: 3, delayMs: 0 });
  assert.equal(peak, 3);
});

test('requests are spaced out by delayMs per worker', async () => {
  const times = [];
  const timed = async () => { times.push(Date.now()); return { feet: 1 }; };
  const samples = samplePoints([A, B], { maxSamples: 4 });
  await fetchProfile(samples, { elevationAt: timed, cache: createElevationCache(null), concurrency: 1, delayMs: 30 });
  const gaps = times.slice(1).map((t, i) => t - times[i]);
  assert.ok(gaps.every((g) => g >= 25), `gaps ${gaps}`);
});

test('a failed point stays a gap and is not cached; no data is a gap too', async () => {
  const samples = samplePoints([A, B], { maxSamples: 4 });
  let n = 0;
  const flaky = async () => {
    n += 1;
    if (n === 2) throw new Error('HTTP 503');
    if (n === 3) return null;  // the service has no data here
    return { feet: 5 };
  };
  const cache = createElevationCache(null);
  const p = await fetchProfile(samples, { elevationAt: flaky, cache, concurrency: 1, delayMs: 0 });
  assert.deepEqual(p.points.map((x) => x.status), ['ok', 'failed', 'nodata', 'ok']);
  assert.deepEqual(p.points.map((x) => x.feet), [5, null, null, 5]);
  assert.equal(p.failed, 1);
  // The failed point is asked again next time; the others come from the cache.
  const again = [];
  await fetchProfile(samples, { elevationAt: okFetch(again), cache, concurrency: 1, delayMs: 0 });
  assert.equal(again.length, 1);
});

test('aborting stops the batch: no further requests, and it rejects with AbortError', async () => {
  const ctrl = new AbortController();
  let calls = 0;
  const fetchOne = async (lng, lat, { signal }) => {
    calls += 1;
    if (calls === 2) ctrl.abort();
    if (signal?.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' });
    return { feet: 1 };
  };
  const samples = samplePoints([A, B], { maxSamples: 10 });
  await assert.rejects(fetchProfile(samples, { elevationAt: fetchOne, cache: createElevationCache(null), concurrency: 1,
    delayMs: 0, signal: ctrl.signal }), { name: 'AbortError' });
  assert.equal(calls, 2);
});

test('a broken localStorage does not stop the profile', async () => {
  const broken = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('quota'); } };
  const p = await fetchProfile(samplePoints([A, B], { maxSamples: 3 }),
    { elevationAt: async () => ({ feet: 2 }), cache: createElevationCache(broken), delayMs: 0 });
  assert.equal(p.points.length, 3);
});

test('profileChart: scales, gaps break the line, vertical exaggeration and labels', () => {
  const points = [
    { d: 0, feet: 10 }, { d: 1000, feet: 20 }, { d: 2000, feet: null }, { d: 3000, feet: 15 }, { d: 4000, feet: 12 },
  ];
  const c = profileChart(points, { width: 400, height: 200 });
  assert.equal(c.segments.length, 2);  // the gap at 2,000 ft splits the line
  assert.equal(c.segments[0].length, 2);
  assert.ok(c.path.startsWith('M') && c.path.split('M').length - 1 === 2);
  assert.equal(c.yLabel, 'Elevation, ft (NAVD88)');
  assert.equal(c.xLabel, 'Distance along the line, ft');
  const ve = (c.plot.h / (c.y.hi - c.y.lo)) / (c.plot.w / (c.x.hi - c.x.lo));
  assert.ok(Math.abs(c.exaggeration - ve) < 1e-9);
  assert.match(c.exaggerationText, /^Vertical exaggeration ×\d/);
  assert.equal(profileChart([{ d: 0, feet: null }], { width: 400, height: 200 }), null);
});
