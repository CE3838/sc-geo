// The About page: linked from the header, static, and in step with web/card.js
// and web/merged.js (tests/test_about_page.py checks the Python side).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { confidenceLevel, confidenceWhy } from '../../web/card.js';
import { CONFIDENCE_STOPS } from '../../web/merged.js';

const read = (name) => readFileSync(new URL(`../../web/${name}`, import.meta.url), 'utf8');
const index = read('index.html');
const about = read('about.html');

const header = (html) => /<header class="app-header">([\s\S]*?)<\/header>/.exec(html)?.[1] ?? '';
const tabs = (html) => [...header(html).matchAll(/<a class="app-tab"([^>]*)>([^<]*)<\/a>/g)]
  .map(([, attrs, text]) => ({ text, href: /href="([^"]+)"/.exec(attrs)?.[1], current: /aria-current="page"/.test(attrs) }));

function synced(html) {
  const out = {};
  for (const [, , key, text] of html.matchAll(/<(\w+)[^>]*\bdata-sync="([^"]+)"[^>]*>([\s\S]*?)<\/\1>/g)) {
    out[key] = text.replace(/<[^>]+>/g, '').trim();
  }
  return out;
}

test('the map header has Map and About tabs; About opens about.html', () => {
  assert.deepEqual(tabs(index), [
    { text: 'Map', href: 'index.html', current: true },
    { text: 'About', href: 'about.html', current: false },
  ]);
  assert.match(header(index), /id="panels-toggle"/, 'the Layers drawer button stays in the header');
});

test('the About page has the same header with About current and a way back to the map', () => {
  assert.deepEqual(tabs(about), [
    { text: 'Map', href: 'index.html', current: false },
    { text: 'About', href: 'about.html', current: true },
  ]);
  assert.match(about, /<meta name="viewport" content="width=device-width, initial-scale=1">/);
});

test('the About page is static: no scripts, no requests beyond its own stylesheets', () => {
  assert.doesNotMatch(about, /<script/i);
  const local = [...about.matchAll(/<link[^>]+href="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(local, ['style.css', 'about.css']);
  assert.doesNotMatch(about, /<img|<iframe/i);
});

test('every section in the table of contents exists', () => {
  const toc = [...about.matchAll(/<nav class="about-toc"[\s\S]*?<\/nav>/g)][0][0];
  const ids = [...toc.matchAll(/href="#([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(ids, ['map', 'confidence', 'inferred', 'documents', 'surfaces', 'sources']);
  for (const id of ids) assert.match(about, new RegExp(`<section id="${id}">`));
});

test('the High / Medium / Low thresholds on the page are the ones card.js uses', () => {
  const s = synced(about);
  const high = Number(s['level.high']);
  const medium = Number(s['level.medium']);
  assert.equal(confidenceLevel(high).level, 'High');
  assert.equal(confidenceLevel(high - 0.001).level, 'Medium');
  assert.equal(confidenceLevel(medium).level, 'Medium');
  assert.equal(confidenceLevel(medium - 0.001).level, 'Low');
});

test('the confidence colors on the page are the map stops', () => {
  const s = synced(about);
  assert.deepEqual([s['color.low'], s['color.mid'], s['color.high']].map(Number), CONFIDENCE_STOPS.map(([v]) => v));
});

test('the card why rows use the factors the page states', () => {
  const s = synced(about);
  const lone = confidenceWhy({ conf: 0.5, conf_base: 0.95, agreement: null, research_support: true,
    identity_confidence: 'certain' }, { scale: 24000 });
  assert.equal(lone[2].value, `× ${s['agree.lone']}`);
  assert.equal(lone[3].value, `+ ${s['geolex.bonus']}`);
  assert.equal(lone[1].value, `× ${s['identity.certain']}`);
  // The worked example as the card shows it.
  const ex = confidenceWhy({ conf: Number(s['ex1.value']), conf_base: Number(s['ex1.base']),
    agreement: Number(s['ex1.agreement']), n_sources: Number(s['ex1.sources']), research_support: true,
    identity_confidence: 'certain' }, { scale: 24000 });
  assert.deepEqual(ex.map((w) => w.value), [
    s['scale.24000'], `× ${s['identity.certain']}`, `× ${s['ex1.factor_card']}`, `+ ${s['geolex.bonus']}`, s['ex1.card'],
  ]);
  assert.match(ex[2].label, new RegExp(`${s['ex1.agree_pct']} agree`));
});
