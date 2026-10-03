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

// USDA NAIP aerial imagery (public domain), in order of preference. Both are
// ArcGIS ImageServers rendered on demand for each map tile's bbox.
const EXPORT_PARAMS =
  'exportImage?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=256,256&format=jpgpng&f=image';

export const NAIP_SOURCES = [
  {
    id: 'usgs',
    url: `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/${EXPORT_PARAMS}`,
    attribution: 'Imagery: USDA NAIP via USGS The National Map',
  },
  {
    id: 'usda',
    url: `https://gis.apfo.usda.gov/arcgis/rest/services/NAIP/USDA_CONUS_PRIME/ImageServer/${EXPORT_PARAMS}`,
    attribution: 'Imagery: USDA NAIP via USDA FPAC',
  },
];

export function fillBbox(template, bbox) {
  return template.replace('{bbox-epsg-3857}', bbox.join(','));
}

// [west, south, east, north] lon/lat -> EPSG:3857 meters.
export function mercatorBbox([w, s, e, n]) {
  const R = 6378137;
  const x = (lng) => (R * lng * Math.PI) / 180;
  const y = (lat) => R * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  return [x(w), y(s), x(e), y(n)];
}

// Switch imagery servers when a source keeps failing and has never loaded.
export function shouldFallBack({ errors, loaded }, threshold = 3) {
  return loaded === 0 && errors >= threshold;
}
