import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  IMAGERY_SWITCH_AFTER, IMAGERY_TILE_URL, IMAGERY_TIMEOUT_MS, createImageryLoader, parseTileUrl,
} from '../../web/imagery.js';
import { NAIP_SOURCES } from '../../web/geo.js';

const [PREFERRED, FALLBACK] = NAIP_SOURCES;

// Manual clock: timers run only when the test advances time.
function fakeClock() {
  let now = 0;
  let seq = 0;
  const timers = new Map();
  return {
    setTimeout(fn, ms) { const id = ++seq; timers.set(id, { fn, at: now + ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    pending: () => timers.size,
    async advance(ms) {
      now += ms;
      for (const [id, t] of [...timers].sort((a, b) => a[1].at - b[1].at)) {
        if (t.at <= now && timers.has(id)) { timers.delete(id); t.fn(); }
      }
      await flush();
    },
  };
}

const flush = () => new Promise((r) => setImmediate(r));

const image = (bytes = 2000) => ({
  ok: true, status: 200, headers: { get: () => 'image/jpeg' },
  arrayBuffer: async () => new ArrayBuffer(bytes),
});

// Fake fetch: each host answers per `behavior(url)`: 'image', 'error', 'hang', or a Response-like.
// Hung requests settle only when their signal aborts, like a real fetch.
function fakeFetch(behavior) {
  const calls = [];
  const fn = (url, { signal } = {}) => {
    const call = { url, signal, aborted: false };
    calls.push(call);
    return new Promise((resolve, reject) => {
      const onAbort = () => { call.aborted = true; reject(Object.assign(new Error('aborted'), { name: 'AbortError' })); };
      if (signal?.aborted) return onAbort();
      signal?.addEventListener('abort', onAbort);
      const b = behavior(url);
      if (b === 'image') resolve(image());
      else if (b === 'error') reject(new TypeError('Failed to fetch'));
      else if (b === 'hang') { /* never answers */ } else resolve(b);
    });
  };
  fn.calls = calls;
  fn.to = (src) => calls.filter((c) => c.url.startsWith(src.url.split('?')[0].replace(/\{.*$/, '')));
  return fn;
}

const hosts = (pref, fall) => (url) => (url.includes('imagery.nationalmap.gov') ? pref : fall);

function setup(behavior, opts = {}) {
  const clock = fakeClock();
  const fetch = fakeFetch(behavior);
  const events = [];
  const loader = createImageryLoader(NAIP_SOURCES, {
    fetch, setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout,
    onChange: (info) => events.push(info), ...opts,
  });
  return { clock, fetch, loader, events };
}

const params = (z, x, y) => ({ url: `naip://tile/${z}/${x}/${y}`, type: 'image' });

test('the timeout and switch thresholds are the documented defaults', () => {
  assert.equal(IMAGERY_TIMEOUT_MS, 8000);
  assert.equal(IMAGERY_SWITCH_AFTER, 3);
  assert.match(IMAGERY_TILE_URL, /^naip:\/\/.*\{z\}.*\{x\}.*\{y\}/);
  assert.deepEqual(parseTileUrl('naip://tile/16/18217/26445'), { z: 16, x: 18217, y: 26445 });
  assert.equal(parseTileUrl('https://example.com/16/1/2'), null);
});

test('a working preferred server serves the tile with one request and no fallback', async () => {
  const { clock, fetch, loader, events } = setup(hosts('image', 'image'));
  const res = await loader.load(params(16, 18217, 26445), new AbortController());
  assert.ok(res.data instanceof ArrayBuffer);
  assert.equal(fetch.calls.length, 1);
  assert.match(fetch.calls[0].url, /imagery\.nationalmap\.gov.*exportImage\?bbox=/);
  assert.equal(clock.pending(), 0, 'timer cleared');
  assert.equal(loader.state().active, PREFERRED.id);
  assert.equal(loader.attribution(), PREFERRED.attribution);
  assert.deepEqual(events.map((e) => e.servedBy), [PREFERRED.id]);
});

test('a hung preferred request times out and that tile comes from the fallback', async () => {
  const { clock, fetch, loader } = setup(hosts('hang', 'image'));
  const p = loader.load(params(16, 18217, 26445), new AbortController());
  await clock.advance(IMAGERY_TIMEOUT_MS - 1);
  assert.equal(fetch.calls.length, 1, 'still waiting on the preferred server');
  await clock.advance(1);
  const res = await p;
  assert.ok(res.data instanceof ArrayBuffer);
  assert.equal(fetch.calls.length, 2);
  assert.ok(fetch.calls[0].aborted, 'the hung request is aborted, not left open');
  assert.equal(fetch.calls[1].url, 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/16/26445/18217');
  assert.equal(loader.state().failures, 1);
  assert.equal(loader.state().active, PREFERRED.id, 'one timeout does not switch the layer');
});

test('an error, a bad status or a non-image answer also falls back at once', async () => {
  for (const bad of ['error', { ok: false, status: 503, headers: { get: () => 'text/html' }, arrayBuffer: async () => new ArrayBuffer(10) },
    { ok: true, status: 200, headers: { get: () => 'application/json' }, arrayBuffer: async () => new ArrayBuffer(10) }]) {
    const { fetch, loader } = setup(hosts(bad, 'image'));
    const res = await loader.load(params(15, 1, 2), new AbortController());
    assert.ok(res.data instanceof ArrayBuffer);
    assert.equal(fetch.calls.length, 2);
    assert.match(fetch.calls[1].url, /basemap\.nationalmap\.gov/);
  }
});

test(`after ${IMAGERY_SWITCH_AFTER} failures in a row the layer switches to the fallback for the session`, async () => {
  const { clock, fetch, loader, events } = setup(hosts('hang', 'image'));
  for (let i = 0; i < IMAGERY_SWITCH_AFTER; i += 1) {
    const p = loader.load(params(16, i, 0), new AbortController());
    await clock.advance(IMAGERY_TIMEOUT_MS);
    await p;
  }
  assert.equal(loader.state().active, FALLBACK.id);
  assert.ok(events.some((e) => e.switchedTo === FALLBACK.id));
  const before = fetch.to(PREFERRED).length;
  assert.equal(before, IMAGERY_SWITCH_AFTER, 'one request per tile to the dead server, no retries');
  for (let i = 0; i < 5; i += 1) await loader.load(params(16, 10 + i, 0), new AbortController());
  assert.equal(fetch.to(PREFERRED).length, before, 'the dead server is not asked again');
  assert.equal(fetch.to(FALLBACK).length, IMAGERY_SWITCH_AFTER + 5, 'one request per tile to the fallback');
  assert.equal(clock.pending(), 0);
});

test('a success resets the count: only failures in a row switch the layer', async () => {
  let n = 0;
  const { loader } = setup((url) => (url.includes('imagery.nationalmap.gov') ? ((n += 1) % 3 === 0 ? 'image' : 'error') : 'image'));
  for (let i = 0; i < 9; i += 1) await loader.load(params(14, i, 0), new AbortController());
  assert.equal(loader.state().active, PREFERRED.id);
});

test('requests still waiting on the dead server move to the fallback when the layer switches', async () => {
  const { clock, fetch, loader } = setup(hosts('hang', 'image'));
  // Many tiles start together (a new view); the first ones time out first.
  const early = [0, 1, 2].map((i) => loader.load(params(16, i, 0), new AbortController()));
  await clock.advance(1000);
  const late = [3, 4, 5, 6].map((i) => loader.load(params(16, i, 0), new AbortController()));
  await clock.advance(IMAGERY_TIMEOUT_MS - 1000);
  await Promise.all(early);
  // The late ones did not wait out their own timeouts.
  const res = await Promise.all(late);
  assert.equal(res.length, 4);
  assert.equal(fetch.to(PREFERRED).length, 7, 'each tile asked the preferred server once');
  assert.equal(fetch.to(FALLBACK).length, 7, 'each tile asked the fallback once');
  assert.ok(fetch.to(PREFERRED).every((c) => c.aborted));
  assert.equal(clock.pending(), 0);
});

test('a tile the map cancels is aborted, not counted and not fetched from the fallback', async () => {
  const { clock, fetch, loader } = setup(hosts('hang', 'image'));
  const ctl = new AbortController();
  const p = loader.load(params(16, 1, 1), ctl);
  ctl.abort();
  await assert.rejects(p, (err) => err.message === 'AbortError');
  await clock.advance(IMAGERY_TIMEOUT_MS * 2);
  assert.equal(fetch.calls.length, 1);
  assert.ok(fetch.calls[0].aborted);
  assert.equal(loader.state().failures, 0);
  assert.equal(clock.pending(), 0);
});

test('when every server fails the tile errors (the viewer then shows its notice)', async () => {
  const { clock, fetch, loader } = setup(hosts('hang', 'hang'));
  const p = loader.load(params(16, 1, 1), new AbortController());
  const done = assert.rejects(p, /imagery/i);
  await clock.advance(IMAGERY_TIMEOUT_MS);
  await clock.advance(IMAGERY_TIMEOUT_MS);
  await done;
  assert.equal(fetch.calls.length, 2);
  // The last server is never switched off: there is nothing after it.
  for (let i = 0; i < 4; i += 1) {
    const q = assert.rejects(loader.load(params(16, 2 + i, 1), new AbortController()));
    await clock.advance(IMAGERY_TIMEOUT_MS);
    await clock.advance(IMAGERY_TIMEOUT_MS);
    await q;
  }
  assert.equal(loader.state().active, FALLBACK.id);
});

test('attribution names every server that served tiles, the fallback included', async () => {
  const { loader, events } = setup(hosts('error', 'image'));
  assert.equal(loader.attribution(), PREFERRED.attribution, 'before any tile: the server that will be asked');
  await loader.load(params(16, 1, 1), new AbortController());
  assert.equal(loader.attribution(), FALLBACK.attribution);
  assert.deepEqual(events.map((e) => e.attribution), [FALLBACK.attribution]);

  let first = true;
  const mixed = setup((url) => {
    if (!url.includes('imagery.nationalmap.gov')) return 'image';
    const b = first ? 'image' : 'error';
    first = false;
    return b;
  });
  await mixed.loader.load(params(16, 1, 1), new AbortController());
  await mixed.loader.load(params(16, 2, 1), new AbortController());
  assert.equal(mixed.loader.attribution(), `${PREFERRED.attribution}; ${FALLBACK.attribution}`);
  assert.equal(mixed.events.length, 2, 'a change only when a new server serves its first tile');
  await mixed.loader.load(params(16, 3, 1), new AbortController());
  assert.equal(mixed.events.length, 2);
});

test('high-density screens ask the rendering server for 512 px images; cached tiles are unchanged', async () => {
  const { fetch, loader } = setup(hosts('error', 'image'), { pixelRatio: 2 });
  await loader.load(params(16, 1, 1), new AbortController());
  assert.match(fetch.calls[0].url, /size=512,512/);
  assert.match(fetch.calls[1].url, /\/tile\/16\/1\/1$/);
});
