// Scales, ticks and the line path for the water-level chart (water-ui.js
// draws it as SVG). Pure functions, no DOM, so they can be tested.

// Round a float to the precision of a step so tick labels carry no noise.
function clean(v, step) {
  const digits = Math.max(0, -Math.floor(Math.log10(step)) + 1);
  return Number(v.toFixed(Math.min(digits, 12)));
}

// About `count` round ticks (1, 2, 2.5 or 5 times a power of ten) that cover
// [min, max]. A flat series is widened so it still has a range.
export function niceTicks(min, max, count = 5) {
  let lo = min;
  let hi = max;
  if (hi - lo < 1e-9) {
    const pad = Math.abs(lo) > 1 ? Math.abs(lo) * 0.001 + 0.5 : 0.5;
    lo -= pad;
    hi += pad;
  }
  const raw = (hi - lo) / Math.max(1, count - 1);
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw * 0.999);
  const start = Math.floor(lo / step + 1e-9) * step;
  const end = Math.ceil(hi / step - 1e-9) * step;
  const ticks = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(clean(v, step));
  return { lo: clean(start, step), hi: clean(end, step), step: clean(step, step), ticks };
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAY = 86400e3;

// Date ticks between t0 and t1: whole days (every 1, 2, 7 or 14) for short
// ranges, the first of every 1, 2 or 3 months for long ones. Local time
// unless `utc`.
export function timeTicks(t0, t1, { maxTicks = 6, utc = false } = {}) {
  const get = (d, part) => d[`get${utc ? 'UTC' : ''}${part}`]();
  const make = (y, m, day) => (utc ? Date.UTC(y, m, day) : new Date(y, m, day).getTime());
  const span = t1 - t0;
  const ticks = [];
  if (span <= 120 * DAY) {
    const every = [1, 2, 7, 14, 28].find((n) => span / (n * DAY) <= maxTicks) ?? 28;
    // Count back from the latest midnight so the newest day is labeled.
    const last = new Date(t1);
    const y = get(last, 'FullYear');
    const m = get(last, 'Month');
    for (let day = get(last, 'Date'), t = make(y, m, day); t >= t0; day -= every, t = make(y, m, day)) {
      const d = new Date(t);
      ticks.unshift({ t, label: `${MONTHS[get(d, 'Month')]} ${get(d, 'Date')}` });
    }
    return ticks;
  }
  const months = span / (30.44 * DAY);
  const every = [1, 2, 3, 6].find((n) => months / n <= maxTicks) ?? 12;
  const first = new Date(t0);
  let y = get(first, 'FullYear'); let m = get(first, 'Month') + 1;
  for (let t = make(y, m, 1); t <= t1; t = make(y, m += every, 1)) {
    const d = new Date(t);
    const month = get(d, 'Month');
    ticks.push({ t, label: month === 0 ? `Jan ${get(d, 'FullYear')}` : MONTHS[month] });
  }
  return ticks;
}

function median(values) {
  const s = [...values].sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : 0;
}

const fmt = (v) => v.toFixed(1);

// Layout for points [{t, v}] between t0 and t1 in a width x height box.
// `invert` draws larger values lower (depth to water: deeper is down).
export function chartModel(points, {
  width, height, t0, t1, invert = false, utc = false,
  margin = { top: 18, right: 12, bottom: 24, left: 44 },
} = {}) {
  const valid = points.filter((p) => p.v !== null && Number.isFinite(p.v));
  const base = { margin, width, height, inverted: invert };
  if (!valid.length) return { ...base, empty: true, path: '', xTicks: [], yTicks: [] };

  let min = valid[0];
  let max = valid[0];
  for (const p of valid) {
    if (p.v < min.v) min = p;
    if (p.v > max.v) max = p;
  }
  const yt = niceTicks(min.v, max.v, 5);
  const left = margin.left;
  const right = width - margin.right;
  const top = margin.top;
  const bottom = height - margin.bottom;
  const x = (t) => left + ((t - t0) / (t1 - t0)) * (right - left);
  const frac = (v) => (v - yt.lo) / (yt.hi - yt.lo);
  const y = (v) => (invert ? top + frac(v) * (bottom - top) : bottom - frac(v) * (bottom - top));

  // Break the line at missing values and at gaps much longer than usual.
  const steps = [];
  for (let i = 1; i < points.length; i += 1) steps.push(points[i].t - points[i - 1].t);
  const gap = Math.max(3 * median(steps), 2 * 3600e3);
  let path = '';
  let pen = false;
  let prevT = null;
  for (const p of points) {
    if (p.v === null || !Number.isFinite(p.v)) { pen = false; continue; }
    if (pen && prevT !== null && p.t - prevT > gap) pen = false;
    path += `${path ? ' ' : ''}${pen ? 'L' : 'M'}${fmt(x(p.t))} ${fmt(y(p.v))}`;
    pen = true;
    prevT = p.t;
  }

  const at = (p) => ({ ...p, x: x(p.t), y: y(p.v) });
  return {
    ...base, empty: false, x, y, yLo: yt.lo, yHi: yt.hi, path,
    min: at(min), max: at(max),
    yTicks: yt.ticks.map((v) => ({ v, y: y(v), label: String(v) })),
    xTicks: timeTicks(t0, t1, { maxTicks: Math.max(3, Math.floor((right - left) / 60)), utc })
      .map((k) => ({ ...k, x: x(k.t) })),
  };
}

// Index of the point nearest in time to t (points sorted by t), or -1.
export function nearestIndex(points, t) {
  if (!points.length) return -1;
  let lo = 0;
  let hi = points.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid].t <= t) lo = mid; else hi = mid;
  }
  return Math.abs(points[hi].t - t) < Math.abs(points[lo].t - t) ? hi : lo;
}

const UNITS = { 'ft^3/s': 'ft³/s', 'm^3/s': 'm³/s' };
export function formatValue(v, unit) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '–';
  const digits = Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 100 ? 1 : 2;
  const text = v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return unit ? `${text} ${UNITS[unit] ?? unit}` : text;
}
