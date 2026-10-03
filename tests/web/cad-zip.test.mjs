import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readZip } from '../../web/cad/zip.js';
import { makeZip } from './cad-helpers.mjs';

test('readZip lists entries and inflates deflate and stored data', async () => {
  const zip = makeZip([
    ['doc.kml', '<kml>deflated</kml>', 8],
    ['files/a.txt', 'stored', 0],
  ]);
  const entries = await readZip(zip);
  assert.deepEqual(entries.map((e) => e.name), ['doc.kml', 'files/a.txt']);
  const dec = new TextDecoder();
  assert.equal(dec.decode(await entries[0].bytes()), '<kml>deflated</kml>');
  assert.equal(dec.decode(await entries[1].bytes()), 'stored');
});

test('readZip rejects non-zip data', async () => {
  await assert.rejects(readZip(new Uint8Array([1, 2, 3])));
});
