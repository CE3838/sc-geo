import {
  DETAIL_MINZOOM, IMAGERY_BOUNDS, MAX_BOUNDS, NAIP_SOURCES, SC_BOUNDS,
  cadEnabled, formatCoords, hiDpiUrl, shouldFallBack, streetViewUrl,
} from './geo.js';
import { setupGeology } from './geology-ui.js';
import { setupLayerPanel } from './layers.js';

const BACKGROUND = '#1b1f23';
// A touch more contrast; NAIP tends to look flat on screen.
const RASTER_PAINT = { 'raster-contrast': 0.1, 'raster-fade-duration': 150 };
// The cached imagery is dark and dull at state scale: lift shadows and add
// a little color there, easing back to neutral by street scale.
const OVERVIEW_PAINT = {
  ...RASTER_PAINT,
  'raster-brightness-min': ['interpolate', ['linear'], ['zoom'], 6, 0.12, 13, 0],
  'raster-saturation': ['interpolate', ['linear'], ['zoom'], 6, 0.25, 13, 0],
  'raster-contrast': ['interpolate', ['linear'], ['zoom'], 6, 0.2, 13, 0.1],
};
const OVERVIEW = NAIP_SOURCES.find((s) => s.id === 'usgs-imagery-basemap');

const map = new maplibregl.Map({
  container: 'map',
  bounds: SC_BOUNDS,
  fitBoundsOptions: { padding: 20 },
  maxBounds: MAX_BOUNDS,
  minZoom: 5,
  style: {
    version: 8,
    sources: {
      overview: {
        type: 'raster',
        tiles: [OVERVIEW.url],
        tileSize: 256,
        maxzoom: 16,
        bounds: IMAGERY_BOUNDS.flat(),
        attribution: OVERVIEW.attribution,
      },
      region: { type: 'geojson', data: 'data/sc-region.geojson' },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': BACKGROUND } },
      // Cached imagery: fast at state scale, and shown under NAIP while it loads.
      { id: 'overview', type: 'raster', source: 'overview', maxzoom: DETAIL_MINZOOM + 2, paint: OVERVIEW_PAINT },
      // Neighboring states are hidden so South Carolina stands alone.
      {
        id: 'mask', type: 'fill', source: 'region',
        filter: ['==', ['get', 'role'], 'mask'],
        paint: { 'fill-color': BACKGROUND, 'fill-antialias': false },
      },
      {
        id: 'sc-outline-casing', type: 'line', source: 'region',
        filter: ['==', ['get', 'role'], 'state'],
        paint: { 'line-color': '#000', 'line-width': 4, 'line-opacity': 0.4 },
      },
      {
        id: 'sc-outline', type: 'line', source: 'region',
        filter: ['==', ['get', 'role'], 'state'],
        paint: { 'line-color': '#fff', 'line-width': 1.5 },
      },
    ],
  },
});

// Live NAIP from DETAIL_MINZOOM up; fall back to the next server if it keeps failing.
let sourceIndex = 0;
let stats = { errors: 0, loaded: 0 };

function useImagery(index) {
  const src = NAIP_SOURCES[index];
  if (map.getLayer('naip')) map.removeLayer('naip');
  if (map.getSource('naip')) map.removeSource('naip');
  map.addSource('naip', {
    type: 'raster',
    tiles: [hiDpiUrl(src.url, window.devicePixelRatio)],
    tileSize: 256,
    bounds: IMAGERY_BOUNDS.flat(),
    attribution: src.attribution,
  });
  // Above the cached imagery; below geology, the mask, outline and CAD layers.
  const above = map.getLayer('geology-fill') ? 'geology-fill' : 'mask';
  map.addLayer({ id: 'naip', type: 'raster', source: 'naip', minzoom: DETAIL_MINZOOM, paint: RASTER_PAINT }, above);
  sourceIndex = index;
  stats = { errors: 0, loaded: 0 };
}

map.on('load', () => useImagery(0));

map.on('data', (e) => {
  if (e.sourceId === 'naip' && e.tile) stats.loaded += 1;
});

map.on('error', (e) => {
  if (e.sourceId !== 'naip') return;
  stats.errors += 1;
  if (!shouldFallBack(stats)) return;
  if (sourceIndex + 1 < NAIP_SOURCES.length) {
    console.warn(`NAIP server "${NAIP_SOURCES[sourceIndex].id}" failed; trying the next one.`);
    useImagery(sourceIndex + 1);
  } else {
    document.getElementById('imagery-notice').hidden = false;
  }
});

map.addControl(new maplibregl.NavigationControl(), 'top-right');
map.addControl(new maplibregl.ScaleControl({ unit: 'imperial' }), 'bottom-left');

const geology = setupGeology(map, document.getElementById('panels'));
const cad = cadEnabled(window.location.search) ? setupLayerPanel(map) : null;
// Handle for debugging and the viewer smoke test (scripts/viewer_smoke.mjs).
window.scGeo = { map, cad, geology };
const popup = new maplibregl.Popup({ closeOnClick: false, maxWidth: '280px' });

const FEATURE_FIELDS = ['text', 'name', 'description', 'code', 'entity', 'type', 'level', 'block'];

function featureInfo(feature) {
  const box = document.createElement('div');
  box.className = 'feature-info';
  const title = document.createElement('div');
  title.className = 'feature-layer';
  title.textContent = feature.properties.layer ?? 'CAD feature';
  box.append(title);
  for (const key of FEATURE_FIELDS) {
    const value = feature.properties[key];
    if (value === undefined || value === '' || String(value) === title.textContent) continue;
    const row = document.createElement('div');
    row.textContent = `${key}: ${value}`;
    box.append(row);
  }
  return box;
}

map.on('click', (e) => {
  const { lng, lat } = e.lngLat;

  const content = document.createElement('div');
  content.className = 'click-popup';

  const coords = document.createElement('div');
  coords.className = 'coords';
  coords.textContent = formatCoords(lng, lat);

  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = 'Open Street View';
  button.addEventListener('click', () => {
    window.open(streetViewUrl(lng, lat), '_blank', 'noopener');
  });

  const [hit] = cad ? cad.featuresAt(e.point) : [];
  const unit = hit ? null : geology.unitAt(e.point);
  if (hit) content.append(featureInfo(hit));
  else if (unit) content.append(geology.describe(unit));
  content.append(coords, button);
  popup.setLngLat(e.lngLat).setDOMContent(content).addTo(map);
});
