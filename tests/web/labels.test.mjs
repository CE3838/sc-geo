import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

const web = new URL('../../web/', import.meta.url);

test('the header and page title name the South Carolina Geology Viewer', () => {
  const html = readFileSync(new URL('index.html', web), 'utf8');
  assert.match(html, /<title>South Carolina Geology Viewer<\/title>/);
  assert.match(html, /<h1 class="app-title">South Carolina Geology Viewer<\/h1>/);
  assert.match(html, /<span class="app-subtitle">South Carolina Geology · Public Data<\/span>/);
});

test('Layers panel names capitalize each word after the first (except "and")', () => {
  const labels = [];
  for (const f of readdirSync(web).filter((n) => n.endsWith('.js'))) {
    const src = readFileSync(new URL(f, web), 'utf8');
    for (const m of src.matchAll(/addLayer\(\{ id: '[^']+', label: '([^']+)'/g)) labels.push(m[1]);
    if (f === 'app.js') for (const m of src.matchAll(/id: 'imagery', label: '([^']+)'/g)) labels.push(m[1]);
  }
  assert.ok(labels.length >= 6, labels.join('; '));
  for (const label of labels) {
    for (const word of label.replace(/\(([^)]*)\)/g, '$1').split(/\s+/)) {
      if (word === 'and') continue;
      assert.match(word, /^[A-Z0-9]/, `"${word}" in "${label}"`);
    }
  }
});
