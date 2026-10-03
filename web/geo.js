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

// NAIP-based aerial imagery (public domain), in order of preference. The first
// is the USGS NAIP ImageServer, rendered on demand per tile bbox; the fallback
// is USGS's cached orthoimagery basemap, which uses NAIP in South Carolina.
export const NAIP_SOURCES = [
  {
    id: 'usgs-naip',
    url:
      'https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage' +
      '?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=256,256&format=jpgpng&f=image',
    attribution: 'Imagery: USDA NAIP via USGS The National Map',
  },
  {
    id: 'usgs-imagery-basemap',
    url: 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Imagery: USGS The National Map orthoimagery (NAIP)',
  },
];

const HALF_WORLD = 20037508.342789244; // Web Mercator half-width in meters

// Slippy-map tile containing a lon/lat at zoom z.
export function tileForLngLat(lng, lat, z) {
  const n = 2 ** z;
  const rad = (lat * Math.PI) / 180;
  const x = Math.floor(((lng + 180) / 360) * n);
  const y = Math.floor(((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n);
  return { x, y, z };
}

// [west, south, east, north] of a tile in EPSG:3857 meters.
export function tileBbox3857({ x, y, z }) {
  const size = (2 * HALF_WORLD) / 2 ** z;
  const w = -HALF_WORLD + x * size;
  const n = HALF_WORLD - y * size;
  return [w, n - size, w + size, n];
}

// Fill a MapLibre raster tile template for one tile.
export function fillTile(template, tile) {
  return template
    .replace('{bbox-epsg-3857}', tileBbox3857(tile).join(','))
    .replace('{z}', tile.z)
    .replace('{x}', tile.x)
    .replace('{y}', tile.y);
}

// Switch imagery servers when a source keeps failing and has never loaded.
export function shouldFallBack({ errors, loaded }, threshold = 3) {
  return loaded === 0 && errors >= threshold;
}

// The CAD layer panel is hidden for now; add ?cad to the URL to show it.
export function cadEnabled(search) {
  return new URLSearchParams(search).has('cad');
}
