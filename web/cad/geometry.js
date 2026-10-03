// Stroking helpers shared by the CAD parsers. Curves become polylines with at
// most ~2 degrees per segment.

const DEG = Math.PI / 180;

function steps(sweepDeg) {
  return Math.max(4, Math.ceil(Math.abs(sweepDeg) / 2));
}

// Circular arc from startDeg sweeping sweepDeg (positive = counterclockwise).
export function arcPoints(cx, cy, r, startDeg, sweepDeg) {
  const n = steps(sweepDeg);
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const a = (startDeg + (sweepDeg * i) / n) * DEG;
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return pts;
}

// Counterclockwise sweep from start to end angle, in (0, 360].
export function ccwSweep(startDeg, endDeg) {
  let s = (endDeg - startDeg) % 360;
  if (s <= 0) s += 360;
  return s;
}

// Ellipse with major-axis vector (mx, my) and minor/major ratio, from
// parameter t0 to t1 (radians, counterclockwise).
export function ellipsePoints(cx, cy, mx, my, ratio, t0, t1) {
  let sweep = t1 - t0;
  while (sweep <= 0) sweep += 2 * Math.PI;
  const n = steps(sweep / DEG);
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const t = t0 + (sweep * i) / n;
    const c = Math.cos(t);
    const s = Math.sin(t) * ratio;
    pts.push([cx + c * mx - s * my, cy + c * my + s * mx]);
  }
  return pts;
}

// Points strictly between p1 and p2 along a DXF bulge arc
// (bulge = tan(sweep/4), positive = counterclockwise).
export function bulgePoints([x1, y1], [x2, y2], bulge) {
  if (!bulge) return [];
  const sweep = 4 * Math.atan(bulge);
  const chord = Math.hypot(x2 - x1, y2 - y1);
  if (chord === 0) return [];
  const r = chord / (2 * Math.sin(Math.abs(sweep) / 2));
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const d = Math.sqrt(Math.max(0, r * r - (chord / 2) ** 2));
  // Unit normal pointing left of p1->p2; center is left for CCW arcs < 180.
  const nx = -(y2 - y1) / chord;
  const ny = (x2 - x1) / chord;
  const side = (Math.abs(sweep) < Math.PI ? 1 : -1) * Math.sign(sweep);
  const cx = mx + side * d * nx;
  const cy = my + side * d * ny;
  const start = Math.atan2(y1 - cy, x1 - cx) / DEG;
  return arcPoints(cx, cy, r, start, sweep / DEG).slice(1, -1);
}

export function closeRing(pts) {
  const [a, b] = [pts[0], pts[pts.length - 1]];
  return a[0] === b[0] && a[1] === b[1] ? pts : [...pts, a];
}
