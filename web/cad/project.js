// Coordinate conversion for CAD imports. Consultant drawings in South Carolina
// are normally in SC State Plane (NAD83, Lambert Conformal Conic). NAD83 is
// treated as WGS84 here; the ~1 m datum shift does not matter for display.

const DEG = Math.PI / 180;

// NAD83 / South Carolina (EPSG:32133), GRS80 ellipsoid, meters.
export const SC_SPCS = {
  a: 6378137,
  e2: 0.0066943800229,
  lat1: 34 + 50 / 60,
  lat2: 32.5,
  lat0: 31 + 50 / 60,
  lon0: -81,
  fe: 609600,
  fn: 0,
};

export const CRS_OPTIONS = {
  'sc-ft': { label: 'SC State Plane NAD83, international feet', toMeters: 0.3048 },
  'sc-usft': { label: 'SC State Plane NAD83, US survey feet', toMeters: 1200 / 3937 },
  'sc-m': { label: 'SC State Plane NAD83, meters', toMeters: 1 },
  lnglat: { label: 'Longitude/latitude (WGS84)' },
};

// EPSG codes for South Carolina State Plane that LandXML files may name.
export const EPSG_TO_CRS = {
  2273: 'sc-ft', 3361: 'sc-ft', 6570: 'sc-ft',
  32133: 'sc-m', 3360: 'sc-m', 6569: 'sc-m',
  4326: 'lnglat', 4269: 'lnglat',
};

function lccConstants({ a, e2, lat1, lat2, lat0 }) {
  const e = Math.sqrt(e2);
  const m = (p) => Math.cos(p) / Math.sqrt(1 - e2 * Math.sin(p) ** 2);
  const t = (p) => Math.tan(Math.PI / 4 - p / 2) / ((1 - e * Math.sin(p)) / (1 + e * Math.sin(p))) ** (e / 2);
  const [p1, p2, p0] = [lat1 * DEG, lat2 * DEG, lat0 * DEG];
  const n = p1 === p2 ? Math.sin(p1) : (Math.log(m(p1)) - Math.log(m(p2))) / (Math.log(t(p1)) - Math.log(t(p2)));
  const F = m(p1) / (n * t(p1) ** n);
  const rho0 = a * F * t(p0) ** n;
  return { e, n, F, rho0, t };
}

// Lambert Conformal Conic (2SP) forward, after Snyder (1987) eqs. 15-1 to 15-10.
export function lccForward(lng, lat, params) {
  const { n, F, rho0, t } = lccConstants(params);
  const rho = params.a * F * t(lat * DEG) ** n;
  const theta = n * (lng - params.lon0) * DEG;
  return [params.fe + rho * Math.sin(theta), params.fn + rho0 - rho * Math.cos(theta)];
}

export function lccInverse(x, y, params) {
  const { e, n, F, rho0 } = lccConstants(params);
  const dx = x - params.fe;
  const dy = rho0 - (y - params.fn);
  const rho = Math.sign(n) * Math.hypot(dx, dy);
  const theta = Math.atan2(Math.sign(n) * dx, Math.sign(n) * dy);
  const tt = (rho / (params.a * F)) ** (1 / n);
  let phi = Math.PI / 2 - 2 * Math.atan(tt);
  for (let i = 0; i < 15; i++) {
    const es = e * Math.sin(phi);
    const next = Math.PI / 2 - 2 * Math.atan(tt * ((1 - es) / (1 + es)) ** (e / 2));
    if (Math.abs(next - phi) < 1e-14) {
      phi = next;
      break;
    }
    phi = next;
  }
  return [theta / n / DEG + params.lon0, phi / DEG];
}

// Returns (x, y) => [lng, lat] for a CRS_OPTIONS key.
export function makeProjector(crs) {
  const opt = CRS_OPTIONS[crs];
  if (!opt) throw new Error(`Unknown coordinate system: ${crs}`);
  if (crs === 'lnglat') return (x, y) => [x, y];
  return (x, y) => lccInverse(x * opt.toMeters, y * opt.toMeters, SC_SPCS);
}

// Generous lon/lat box around South Carolina.
export const SC_LNGLAT_BOX = [-84.5, 31.5, -78, 35.5];

export function inBox([x, y], [w, s, e, n] = SC_LNGLAT_BOX) {
  return x >= w && x <= e && y >= s && y <= n;
}
