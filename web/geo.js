// Pure helpers for the viewer. Kept free of DOM and MapLibre so they can be
// tested with `node --test`.

// South Carolina, [[west, south], [east, north]] in lon/lat.
export const SC_BOUNDS = [[-83.36, 32.03], [-78.54, 35.22]];

export function formatCoords(lng, lat) {
  const ns = lat >= 0 ? 'N' : 'S';
  const ew = lng >= 0 ? 'E' : 'W';
  return `${Math.abs(lat).toFixed(6)}° ${ns}, ${Math.abs(lng).toFixed(6)}° ${ew}`;
}

// Google Maps URL that opens Street View at the nearest panorama.
export function streetViewUrl(lng, lat) {
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    throw new RangeError('lng and lat must be finite numbers');
  }
  const params = new URLSearchParams({
    api: '1',
    map_action: 'pano',
    viewpoint: `${lat.toFixed(6)},${lng.toFixed(6)}`,
  });
  return `https://www.google.com/maps/@?${params}`;
}
