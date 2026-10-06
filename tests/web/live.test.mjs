import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { LIVE_ON_AT_START } from '../../web/live.js';

const web = (f) => readFileSync(new URL(`../../web/${f}`, import.meta.url), 'utf8');

test('layers that query other sites live start off, so a page view sends them no requests', () => {
  assert.deepEqual(LIVE_ON_AT_START, { roads: false, parcels: false, water: false });
  for (const [file, key] of [['roads-ui.js', 'roads'], ['parcels-ui.js', 'parcels'], ['water-ui.js', 'water']]) {
    const src = web(file);
    assert.match(src, new RegExp(`let on = LIVE_ON_AT_START\\.${key};`), file);
    assert.match(src, new RegExp(`checked: LIVE_ON_AT_START\\.${key}`), file);
  }
});

test('the viewer says the data is provided as is, without warranty', () => {
  assert.match(web('index.html'), /without warranty/i);
});

test('the viewer smoke check turns each live layer on, the way a user would, before checking it', () => {
  const smoke = readFileSync(new URL('../../scripts/viewer_smoke.mjs', import.meta.url), 'utf8');
  const firstCheck = { roads: 'roads render with interstates', parcels: 'Charleston parcels', water: 'water stations around' };
  for (const [key, startsOn] of Object.entries(LIVE_ON_AT_START)) {
    if (startsOn) continue;
    const on = smoke.indexOf(`turnOn('${key}')`);
    assert.ok(on > 0, `smoke turns ${key} on`);
    assert.ok(on < smoke.indexOf(firstCheck[key]), `smoke turns ${key} on before checking it`);
  }
});

test('live requests give up after a timeout instead of loading forever', async () => {
  const { fetchJson, FETCH_TIMEOUT_MS } = await import('../../web/roads-ui.js');
  assert.ok(FETCH_TIMEOUT_MS >= 10000 && FETCH_TIMEOUT_MS <= 60000);
  // A server that never answers: the request is aborted by its signal.
  const hang = (url, { signal }) => new Promise((_, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason));
  });
  await assert.rejects(fetchJson('https://example.test/q', { timeoutMs: 50, fetchImpl: hang }));
  // A normal answer still works, and HTTP errors still throw.
  const ok = async () => ({ ok: true, json: async () => ({ a: 1 }) });
  assert.deepEqual(await fetchJson('https://example.test/q', { fetchImpl: ok }), { a: 1 });
  const bad = async () => ({ ok: false, status: 503 });
  await assert.rejects(fetchJson('https://example.test/q', { fetchImpl: bad }), /HTTP 503/);
});
