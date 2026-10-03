// Ground elevation at a point from the USGS Elevation Point Query Service
// (EPQS), which samples the 3D Elevation Program (3DEP) bare-earth DEM;
// in South Carolina that DEM is built from lidar. Elevations are in feet
// (NAVD88).

export const EPQS_CITATION = 'USGS 3DEP';
export const EPQS_SOURCE = 'U.S. Geological Survey, 3D Elevation Program, via the Elevation Point Query Service';

export function epqsUrl(lng, lat) {
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) throw new RangeError('lng and lat must be finite numbers');
  const params = new URLSearchParams({
    x: lng.toFixed(6), y: lat.toFixed(6), wkid: '4326', units: 'Feet', includeDate: 'false',
  });
  return `https://epqs.nationalmap.gov/v1/json?${params}`;
}

// Feet, or null when the service has no data there (it answers -1000000).
export function parseElevation(json) {
  const raw = json?.value;
  if (raw === null || raw === undefined || raw === '') return null;
  const v = Number(raw);
  if (!Number.isFinite(v) || v <= -1000) return null;
  return v;
}

export function formatElevation(feet) {
  return feet === null ? 'Elevation unavailable' : `${feet.toFixed(1)} ft (NAVD88)`;
}

// Elevation in feet with provenance, or null; rejects on network errors or
// after `timeout` ms.
export async function elevationAt(lng, lat, { fetch: fetchFn = globalThis.fetch, signal, timeout = 10000 } = {}) {
  const url = epqsUrl(lng, lat);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  const onAbort = () => ctrl.abort();
  signal?.addEventListener('abort', onAbort);
  try {
    const r = await fetchFn(url, { signal: ctrl.signal });
    if (!r.ok) throw new Error(`EPQS: HTTP ${r.status}`);
    const feet = parseElevation(await r.json());
    return feet === null ? null : {
      feet, source_id: 'usgs-3dep-epqs', locator: url, extraction_method: 'gis_import', confidence: 1.0,
    };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}
