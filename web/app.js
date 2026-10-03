import { NAIP_SOURCES, SC_BOUNDS, formatCoords, shouldFallBack, streetViewUrl } from './geo.js';

const map = new maplibregl.Map({
  container: 'map',
  bounds: SC_BOUNDS,
  fitBoundsOptions: { padding: 20 },
  style: { version: 8, sources: {}, layers: [] },
});

// Load NAIP from the first server; fall back to the next if it keeps failing.
let sourceIndex = 0;
let stats = { errors: 0, loaded: 0 };

function useImagery(index) {
  const src = NAIP_SOURCES[index];
  if (map.getLayer('naip')) map.removeLayer('naip');
  if (map.getSource('naip')) map.removeSource('naip');
  map.addSource('naip', {
    type: 'raster',
    tiles: [src.url],
    tileSize: 256,
    attribution: src.attribution,
  });
  map.addLayer({ id: 'naip', type: 'raster', source: 'naip' });
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

const popup = new maplibregl.Popup({ closeOnClick: false, maxWidth: '260px' });

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

  content.append(coords, button);
  popup.setLngLat(e.lngLat).setDOMContent(content).addTo(map);
});
