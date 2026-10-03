import {
  DETAIL_MINZOOM, IMAGERY_BOUNDS, MAX_BOUNDS, NAIP_SOURCES, SC_BOUNDS,
  firstPopupItem, formatCoords, hiDpiUrl, shouldFallBack, streetViewUrl,
} from './geo.js';
import { setupGeology } from './geology-ui.js';
import { setupMergedGeology } from './merged-ui.js';

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
  // Above the cached imagery; below geology, the mask, outline and add-on layers.
  const above = ['merged-bedrock-fill', 'geology-fill', 'mask'].find((id) => map.getLayer(id));
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

// Merged geology if the build produced it; otherwise the SGMC layer.
const panels = document.getElementById('panels');
let geology = { unitAt: () => null, describe: () => null };
setupMergedGeology(map, panels)
  .then((g) => { geology = g; window.scGeo.geology = g; })
  .catch((err) => {
    console.warn('Merged geology not available, using SGMC:', err.message);
    geology = setupGeology(map, panels);
    window.scGeo.geology = geology;
  });
// Handle for debugging, the viewer smoke test (scripts/viewer_smoke.mjs) and
// add-ons. popupItems: functions (click event) => DOM node or null; the click
// popup shows the first non-null item instead of the geology description.
window.scGeo = { map, geology, popupItems: [] };
const popup = new maplibregl.Popup({ closeOnClick: false, maxWidth: '280px' });

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

  const item = firstPopupItem(window.scGeo.popupItems, e);
  const unit = item ? null : geology.unitAt(e.point);
  if (item) content.append(item);
  else if (unit) content.append(geology.describe(unit));
  content.append(coords, button);
  popup.setLngLat(e.lngLat).setDOMContent(content).addTo(map);
});
