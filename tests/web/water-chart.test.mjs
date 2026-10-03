import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { chartModel, formatValue, nearestIndex, niceTicks, timeTicks } from '../../web/water-chart.js';
import { ogcAdapter } from '../../web/usgs-water.js';

const fixture = (name) => JSON.parse(readFileSync(new URL(`../fixtures/web/${name}.json`, import.meta.url)));
const DAY = 86400e3;

test('niceTicks: round steps covering the data', () => {
  const t = niceTicks(2.9, 3.62, 5);
  assert.ok(t.lo <= 2.9 && t.hi >= 3.62);
  assert.ok([0.1, 0.2, 0.25, 0.5].includes(t.step), `step ${t.step}`);
  assert.ok(t.ticks.length >= 3 && t.ticks.length <= 9);
  assert.ok(t.ticks.every((v, i) => i === 0 || Math.abs(v - t.ticks[i - 1] - t.step) < 1e-9));
  assert.deepEqual(niceTicks(0, 100, 5), { lo: 0, hi: 100, step: 25, ticks: [0, 25, 50, 75, 100] });
  assert.deepEqual(niceTicks(0, 100, 6).ticks, [0, 20, 40, 60, 80, 100]);
  assert.deepEqual(niceTicks(354.12, 354.12, 5).ticks.length > 1, true, 'a flat series still gets a range');
  // No floating-point noise in tick values.
  assert.ok(niceTicks(0.1, 0.7, 6).ticks.every((v) => String(v).length <= 4));
});

test('timeTicks: days for a week, months for a year (UTC for tests)', () => {
  const t1 = Date.parse('2026-10-03T21:00:00Z');
  const week = timeTicks(t1 - 7 * DAY, t1, { utc: true, maxTicks: 8 });
  assert.ok(week.length >= 4 && week.length <= 8);
  assert.ok(week.every((k) => new Date(k.t).getUTCHours() === 0), 'at midnight');
  assert.equal(week.at(-1).label, 'Oct 3');
  const year = timeTicks(t1 - 365 * DAY, t1, { utc: true, maxTicks: 7 });
  assert.ok(year.length >= 4 && year.length <= 7);
  assert.ok(year.every((k) => new Date(k.t).getUTCDate() === 1), 'on the first of a month');
  assert.ok(year.some((k) => /2026/.test(k.label)), 'January carries the year');
});

const congaree = () => ogcAdapter.parseSeries(fixture('usgs-continuous-02169500')).points;

test('chartModel: scales, path, min and max for gage height', () => {
  const points = congaree();
  const t1 = Date.parse('2026-10-03T21:00:00Z');
  const m = chartModel(points, { width: 360, height: 180, t0: t1 - 7 * DAY, t1, utc: true });
  assert.equal(m.empty, false);
  const left = m.margin.left;
  const bottom = 180 - m.margin.bottom;
  assert.equal(m.x(t1 - 7 * DAY), left);
  assert.equal(m.x(t1), 360 - m.margin.right);
  assert.equal(m.y(m.yLo), bottom, 'low values at the bottom');
  assert.equal(m.y(m.yHi), m.margin.top);
  assert.match(m.path, /^M[\d.]+ [\d.]+( L[\d.]+ [\d.]+)+$/);
  const values = points.map((p) => p.v);
  assert.equal(m.min.v, Math.min(...values));
  assert.equal(m.max.v, Math.max(...values));
  assert.ok(m.max.y < m.min.y, 'max drawn above min');
  assert.ok(m.yTicks.length >= 3);
  assert.ok(m.xTicks.length >= 3);
});

test('chartModel: depth to water is inverted (deeper drawn lower)', () => {
  const points = ogcAdapter.parseSeries(fixture('usgs-continuous-well-72019')).points;
  const t1 = Date.parse('2026-10-03T21:00:00Z');
  const m = chartModel(points, { width: 360, height: 180, t0: t1 - 7 * DAY, t1, invert: true, utc: true });
  assert.equal(m.inverted, true);
  assert.equal(m.y(m.yLo), m.margin.top, 'shallow at the top');
  assert.equal(m.y(m.yHi), 180 - m.margin.bottom, 'deep at the bottom');
  assert.ok(m.max.y > m.min.y, 'the deepest reading is lowest');
});

test('chartModel breaks the line over data gaps and ignores missing values', () => {
  const t = Date.parse('2026-10-01T00:00:00Z');
  const points = [0, 1, 2, 3, 30, 31, 32].map((h, i) => ({ t: t + h * 3600e3, v: i === 2 ? null : i }));
  const m = chartModel(points, { width: 300, height: 150, t0: t, t1: t + 33 * 3600e3 });
  assert.equal((m.path.match(/M/g) ?? []).length, 3, 'a break at the null and at the 27-hour gap');
});

test('chartModel with no values is empty', () => {
  const m = chartModel([{ t: 0, v: null }], { width: 300, height: 150, t0: 0, t1: DAY });
  assert.equal(m.empty, true);
});

test('nearestIndex finds the closest point by time', () => {
  const pts = [{ t: 0 }, { t: 10 }, { t: 20 }, { t: 40 }];
  assert.equal(nearestIndex(pts, -5), 0);
  assert.equal(nearestIndex(pts, 14), 1);
  assert.equal(nearestIndex(pts, 16), 2);
  assert.equal(nearestIndex(pts, 100), 3);
  assert.equal(nearestIndex([], 5), -1);
});

test('formatValue: sensible precision with units', () => {
  assert.equal(formatValue(2.9, 'ft'), '2.90 ft');
  assert.equal(formatValue(2290, 'ft^3/s'), '2,290 ft³/s');
  assert.equal(formatValue(-4290, 'ft^3/s'), '-4,290 ft³/s');
  assert.equal(formatValue(null, 'ft'), '–');
});
