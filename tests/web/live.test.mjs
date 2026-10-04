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
