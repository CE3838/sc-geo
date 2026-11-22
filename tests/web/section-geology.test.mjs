import { test } from 'node:test';
import assert from 'node:assert/strict';
import { colorForProps, intervalsAlong, stripLayout } from '../../web/section-geology.js';
import { lengthFeet } from '../../web/section.js';
import { distanceAxis } from '../../web/profile.js';

// A line along latitude 32.86 from -80.00 to -79.90; polygons are squares in degrees.
const W = -80.0;
const E = -79.9;
const LAT = 32.86;
const LINE = [[W, LAT], [E, LAT]];
const L = lengthFeet(LINE);

const ring = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
const sq = (x0, x1, y0 = 32.8, y1 = 32.9) => ({ type: 'Polygon', coordinates: [ring(x0, y0, x1, y1)] });
const feat = (geometry, unit, extra = {}) => ({ type: 'Feature', geometry,
  properties: { unit, map_unit: unit.split('|')[1], conf: 0.7, source: unit.split('|')[0], ...extra } });
const describe = (p) => ({ key: p.unit, symbol: p.map_unit, name: `Unit ${p.map_unit}`, citation: 'Author, 2001' });
const color = (p) => `#${p.map_unit === 'Qa' ? 'aaa' : 'bbb'}`;
const run = (features, line = LINE) => intervalsAlong(line, features, { describe, color });
const frac = (x) => (x - W) / (E - W);  // share of the line west of longitude x (nearly linear here)
const near = (a, b, tol = L * 0.002) => assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);

test('a line crossing two polygons gives two ordered intervals that cover it', () => {
  const out = run([feat(sq(-80.1, -79.95), 'm|Qa'), feat(sq(-79.95, -79.8), 'm|Qb')]);
  assert.deepEqual(out.map((i) => i.symbol), ['Qa', 'Qb']);
  assert.equal(out[0].from, 0);
  near(out[0].to, L * frac(-79.95));
  assert.equal(out[1].from, out[0].to);
  assert.ok(Math.abs(out[1].to - L) < 1e-6);
  assert.equal(out[0].name, 'Unit Qa');
  assert.equal(out[0].color, '#aaa');
  assert.equal(out[0].conf, 0.7);
  assert.equal(out[0].citation, 'Author, 2001');
});

test('stretches no polygon covers are gaps, never filled', () => {
  const out = run([feat(sq(-79.98, -79.96), 'm|Qa')]);
  assert.deepEqual(out.map((i) => i.symbol ?? null), [null, 'Qa', null]);
  const gap = out[0];
  assert.equal(gap.mapped, false);
  assert.equal(gap.label, 'no mapped unit');
  assert.equal(gap.color, null);
  near(out[1].from, L * frac(-79.98));
  near(out[1].to, L * frac(-79.96));
  assert.deepEqual(run([]), [{ from: 0, to: L, mapped: false, label: 'no mapped unit', symbol: null, name: null,
    color: null, conf: null, citation: null, key: null }]);
});

test('a hole in a polygon is a gap (or the unit inside the hole)', () => {
  const holed = { type: 'Polygon', coordinates: [ring(-80.1, 32.8, -79.8, 32.9), ring(-79.97, 32.85, -79.93, 32.87)] };
  const out = run([feat(holed, 'm|Qa')]);
  assert.deepEqual(out.map((i) => i.symbol ?? null), ['Qa', null, 'Qa']);
  near(out[1].from, L * frac(-79.97));
  near(out[1].to, L * frac(-79.93));
  const island = feat(sq(-79.97, -79.93, 32.85, 32.87), 'm|Qb');
  assert.deepEqual(run([feat(holed, 'm|Qa'), island]).map((i) => i.symbol), ['Qa', 'Qb', 'Qa']);
});

test('the parts of a multipolygon each count; pieces of one unit side by side merge', () => {
  const multi = { type: 'MultiPolygon', coordinates: [[ring(-80.1, 32.8, -79.97, 32.9)], [ring(-79.93, 32.8, -79.8, 32.9)]] };
  assert.deepEqual(run([feat(multi, 'm|Qa')]).map((i) => i.symbol ?? null), ['Qa', null, 'Qa']);
  // Two polygons of the same unit meeting at -79.95 make one interval.
  const out = run([feat(sq(-80.1, -79.95), 'm|Qa'), feat(sq(-79.95, -79.8), 'm|Qa')]);
  assert.equal(out.length, 1);
  assert.equal(out[0].symbol, 'Qa');
});

test('a line vertex on a boundary, and a bent line, keep distances exact', () => {
  const bent = [[W, LAT], [-79.95, LAT], [-79.95, 32.88], [E, 32.88]];
  const out = run([feat(sq(-80.1, -79.95), 'm|Qa'), feat(sq(-79.95, -79.8), 'm|Qb')], bent);
  // The vertical leg runs along the shared boundary; the turn is at a vertex on it.
  const total = lengthFeet(bent);
  assert.equal(out[0].from, 0);
  assert.ok(Math.abs(out.at(-1).to - total) < 1e-6);
  assert.ok(out.every((i, k) => k === 0 || Math.abs(i.from - out[k - 1].to) < 1e-9));
  near(out[0].to, lengthFeet(bent.slice(0, 2)), 1);
  assert.equal(out.at(-1).symbol, 'Qb');
});

test('features far from the line are skipped', () => {
  const far = feat(sq(-81.5, -81.4, 34.0, 34.1), 'm|Qz');
  assert.deepEqual(run([far]).map((i) => i.mapped), [false]);
});

test('colorForProps follows the map legend for each color mode', () => {
  const legend = { age: [{ id: 'Holocene', color: '#111111' }, { id: 'Unknown', color: '#999999' }],
    material: [{ id: 'Sand', color: '#222222' }, { id: 'Unknown', color: '#888888' }] };
  const p = { age_class: 'Holocene', material_class: 'Clay', conf: 0.9 };
  assert.equal(colorForProps(p, 'age', legend), '#111111');
  assert.equal(colorForProps(p, 'material', legend), '#888888');  // unknown class
  assert.equal(colorForProps(p, 'confidence', legend), '#1a9850');
  assert.equal(colorForProps({ conf: 0.3 }, 'confidence', legend), '#d73027');
  assert.match(colorForProps({ conf: 0.45 }, 'confidence', legend), /^#[0-9a-f]{6}$/);
});

test('stripLayout places intervals on the same distance axis as the profile', () => {
  const intervals = run([feat(sq(-79.98, -79.96), 'm|Qa')]);
  const s = stripLayout(intervals, L, { width: 262 });
  const axis = distanceAxis(L, 262);
  assert.equal(s.plot.x, axis.plot.x);
  assert.equal(s.plot.w, axis.plot.w);
  assert.ok(Math.abs(s.rects[1].x - axis.px(intervals[1].from)) < 1e-9);
  assert.ok(Math.abs(s.rects[1].x + s.rects[1].w - axis.px(intervals[1].to)) < 1e-9);
  assert.equal(s.rects[0].mapped, false);
});
