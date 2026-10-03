// South Carolina State Plane, NAD83 (SPCS zone 3900; EPSG:2273 in
// international feet). Lambert Conformal Conic with two standard parallels
// on GRS80 (Snyder 1987, eqs. 15-1 to 15-11; inverse 7-9, 14-4, 15-11).
// NAD83 is treated as WGS84 (about a meter apart), as in model/gisio.py.

const A = 6378137.0;
const F = 1 / 298.257222101;
const E2 = F * (2 - F);
const E = Math.sqrt(E2);
const DEG = Math.PI / 180;
const FOOT = 0.3048; // international foot, meters

const LAT1 = (34 + 50 / 60) * DEG;
const LAT2 = (32 + 30 / 60) * DEG;
const LAT0 = (31 + 50 / 60) * DEG;
const LON0 = -81;
const FALSE_EASTING = 609600; // meters (2,000,000 ft)
const FALSE_NORTHING = 0;

const m = (p) => Math.cos(p) / Math.sqrt(1 - E2 * Math.sin(p) ** 2);
const t = (p) => Math.tan(Math.PI / 4 - p / 2) / ((1 - E * Math.sin(p)) / (1 + E * Math.sin(p))) ** (E / 2);

const N = (Math.log(m(LAT1)) - Math.log(m(LAT2))) / (Math.log(t(LAT1)) - Math.log(t(LAT2)));
const BIG_F = m(LAT1) / (N * t(LAT1) ** N);
const RHO0 = A * BIG_F * t(LAT0) ** N;

// Longitude/latitude (degrees) to State Plane easting/northing in feet.
export function toStatePlane(lng, lat) {
  const rho = A * BIG_F * t(lat * DEG) ** N;
  const theta = N * (lng - LON0) * DEG;
  const x = FALSE_EASTING + rho * Math.sin(theta);
  const y = FALSE_NORTHING + RHO0 - rho * Math.cos(theta);
  return { e: x / FOOT, n: y / FOOT };
}

// State Plane feet back to longitude/latitude (degrees).
export function fromStatePlane(eFeet, nFeet) {
  const dx = eFeet * FOOT - FALSE_EASTING;
  const dy = RHO0 - (nFeet * FOOT - FALSE_NORTHING);
  const rho = Math.sign(N) * Math.hypot(dx, dy);
  const theta = Math.atan2(Math.sign(N) * dx, Math.sign(N) * dy);
  const tt = (rho / (A * BIG_F)) ** (1 / N);
  let phi = Math.PI / 2 - 2 * Math.atan(tt);
  for (let i = 0; i < 20; i += 1) {
    const es = E * Math.sin(phi);
    const next = Math.PI / 2 - 2 * Math.atan(tt * ((1 - es) / (1 + es)) ** (E / 2));
    const done = Math.abs(next - phi) < 1e-15;
    phi = next;
    if (done) break;
  }
  return { lng: theta / N / DEG + LON0, lat: phi / DEG };
}

const FEET = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

// "N 375,157 ft · E 2,319,332 ft", or '' for a point that is not a number.
export function formatStatePlane(lng, lat) {
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return '';
  const { e, n } = toStatePlane(lng, lat);
  return `N ${FEET.format(n)} ft · E ${FEET.format(e)} ft`;
}
