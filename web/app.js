import {
  DETAIL_MINZOOM, IMAGERY_BOUNDS, MAX_BOUNDS, NAIP_SOURCES, SC_BOUNDS,
  firstPopupItem, formatCoords, formatScale, hiDpiUrl, onStyleReady, scaleDenominator, shouldFallBack, streetViewUrl,
} from './geo.js';
import { setupGeology } from './geology-ui.js';
import { setupMergedGeology } from './merged-ui.js';
import { setupFaults } from './faults-ui.js';
import { setupWater } from './water-ui.js';
import { createSidebar } from './sidebar.js';
import { setupCard } from './card-ui.js';
import { confidenceLevel } from './card.js';
import { formatStatePlane } from './stateplane.js';
import { EPQS_CITATION, EPQS_SOURCE, elevationAt, formatElevation } from './elevation.js';
import { el } from './dom.js';

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
  // Collapsed to an (i) button so the credits do not cover the map bottom.
  attributionControl: { compact: true },
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

// --- layout: sidebar drawer (phones), property card --------------------------

const panels = document.getElementById('panels');
const sidebar = createSidebar(panels);
const toggle = document.getElementById('panels-toggle');
const phone = window.matchMedia('(max-width: 700px)');
function setDrawer(open) {
  panels.classList.toggle('open', open);
  toggle.setAttribute('aria-expanded', String(open));
}
toggle.addEventListener('click', () => setDrawer(!panels.classList.contains('open')));
setDrawer(false);

const card = setupCard(document.getElementById('card'), {
  // The card takes room from the map on wide screens; keep the map sized.
  onToggle: () => { if (!phone.matches) map.resize(); },
});

// --- imagery ------------------------------------------------------------------

// Live NAIP from DETAIL_MINZOOM up; fall back to the next server if it keeps failing.
let sourceIndex = 0;
let stats = { errors: 0, loaded: 0 };
let imageryOn = true;

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
  map.addLayer({ id: 'naip', type: 'raster', source: 'naip', minzoom: DETAIL_MINZOOM, paint: RASTER_PAINT,
    layout: { visibility: imageryOn ? 'visible' : 'none' } }, above);
  sourceIndex = index;
  stats = { errors: 0, loaded: 0 };
}

onStyleReady(map, () => useImagery(0));

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

sidebar.addLayer({
  id: 'imagery', label: 'Aerial imagery (NAIP)', order: 90,
  onChange: (on) => {
    imageryOn = on;
    for (const id of ['overview', 'naip']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
    }
  },
});

map.addControl(new maplibregl.NavigationControl(), 'top-right');
map.addControl(new maplibregl.ScaleControl({ unit: 'imperial' }), 'bottom-left');

// --- geology and faults --------------------------------------------------------

// Merged geology if the build produced it; otherwise the SGMC layer.
let geology = { unitAt: () => null, describe: () => null, card: () => null };
setupMergedGeology(map, sidebar)
  .then((g) => { geology = g; window.scGeo.geology = g; })
  .catch((err) => {
    console.warn('Merged geology not available, using SGMC:', err.message);
    geology = setupGeology(map, sidebar);
    window.scGeo.geology = geology;
  });
const faults = setupFaults(map, sidebar);
// USGS water monitoring stations; a click on one opens its chart instead of the callout.
const water = setupWater(map, sidebar, { phone });

// Catalog records with footprints (merge/references.py), loaded on first use.
let references = null;
function loadReferences() {
  references ??= fetch('data/geology/references.json')
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
    .then((d) => d.records ?? [])
    .catch((err) => { console.warn('References not available:', err.message); return []; });
  return references;
}

// Handle for debugging, the viewer smoke test (scripts/viewer_smoke.mjs) and
// add-ons. popupItems: functions (click event) => DOM node or null; the click
// popup shows the first non-null item instead of the geology summary.
window.scGeo = { map, geology, popupItems: [] };

// --- status bar: cursor position and scale ------------------------------------

const statusSp = document.getElementById('status-sp');
const statusSpLabel = document.getElementById('status-sp-label');
const statusLl = document.getElementById('status-ll');
const statusScale = document.getElementById('status-scale');
function showPosition({ lng, lat }, label = 'SC State Plane') {
  statusSpLabel.textContent = label;
  statusSp.textContent = formatStatePlane(lng, lat);
  statusLl.textContent = formatCoords(lng, lat);
}
function showScale() {
  statusScale.textContent = formatScale(scaleDenominator(map.getZoom(), map.getCenter().lat));
}
const hover = window.matchMedia('(hover: hover)');
map.on('mousemove', (e) => { if (hover.matches) showPosition(e.lngLat); });
// Without a mouse, show the map center.
map.on('move', () => { if (!hover.matches) showPosition(map.getCenter(), 'Center (SC State Plane)'); });
map.on('move', showScale);
onStyleReady(map, () => {
  showScale();
  showPosition(map.getCenter(), hover.matches ? 'SC State Plane' : 'Center (SC State Plane)');
});

// --- click callout ---------------------------------------------------------------

const popup = new maplibregl.Popup({ closeOnClick: false, maxWidth: '300px' });
let elevationCtrl = null;

function openCard(feature, lng, lat) {
  const model = feature ? geology.card(feature, lng, lat, []) : null;
  card.open(model, { lng, lat });
  // On phones the card is a bottom sheet; the callout would sit on top of it.
  if (phone.matches) { setDrawer(false); popup.remove(); }
  // Fill in the key references once the list has loaded.
  if (feature) {
    loadReferences().then((records) => {
      if (records.length && card.isOpen) card.open(geology.card(feature, lng, lat, records), { lng, lat });
    });
  }
}

function geologySummary(feature, lng, lat) {
  const m = geology.card?.(feature, lng, lat, []);
  if (!m) return geology.describe(feature);
  const level = m.confidence && confidenceLevel(m.confidence.value);
  return el('div', { class: 'feature-info' },
    el('div', { class: 'feature-layer' }, m.title, m.group && el('span', { class: 'card-group' }, ` (${m.group})`)),
    el('div', { class: 'callout-sub' }, [m.age, m.ma].filter(Boolean).join(' · ') || m.subtitle),
    level && el('span', { class: `badge badge-${level.level.toLowerCase()}` }, level.text));
}

map.on('click', (e) => {
  const { lng, lat } = e.lngLat;
  if (phone.matches) setDrawer(false);

  const item = firstPopupItem(window.scGeo.popupItems, e);
  if (!item && water.openAt(e)) {
    popup.remove();
    if (phone.matches) card.close();
    return;
  }
  const unit = geology.unitAt(e.point);
  const fault = faults.faultAt(e.point);

  const elevation = el('dd', { class: 'callout-elev' }, 'Loading…');
  const content = el('div', { class: 'click-popup callout' },
    el('div', { class: 'callout-title' }, 'Clicked point'),
    item ?? (unit && geologySummary(unit, lng, lat)),
    !item && fault && faults.describe(fault),
    el('dl', { class: 'callout-coords' },
      el('dt', {}, 'Lat/lon'), el('dd', { class: 'coords' }, formatCoords(lng, lat)),
      el('dt', {}, 'State Plane'), el('dd', {}, formatStatePlane(lng, lat)),
      el('dt', {}, 'Ground'), elevation),
    el('div', { class: 'callout-actions' },
      el('button', { type: 'button', class: 'btn btn-primary callout-card', onclick: () => openCard(unit, lng, lat) }, 'Card'),
      el('button', { type: 'button', class: 'btn', onclick: () => window.open(streetViewUrl(lng, lat), '_blank', 'noopener') },
        'Open Street View')));
  popup.setLngLat(e.lngLat).setDOMContent(content).addTo(map);
  if (card.isOpen) openCard(unit, lng, lat);

  elevationCtrl?.abort();
  const ctrl = new AbortController();
  elevationCtrl = ctrl;
  elevationAt(lng, lat, { signal: ctrl.signal })
    .then((r) => {
      if (ctrl.signal.aborted) return;
      elevation.replaceChildren(formatElevation(r ? r.feet : null),
        r && ' ', r && el('span', { class: 'geo-cite', title: `${EPQS_SOURCE} (${r.locator})` }, EPQS_CITATION));
    })
    .catch(() => { if (!ctrl.signal.aborted) elevation.textContent = 'Elevation unavailable'; });
});
