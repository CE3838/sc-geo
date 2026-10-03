import { SC_BOUNDS, formatCoords, streetViewUrl } from './geo.js';

// USDA NAIP aerial imagery (public domain) served by USGS The National Map.
const NAIP_EXPORT =
  'https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage' +
  '?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=256,256&format=jpgpng&f=image';

const map = new maplibregl.Map({
  container: 'map',
  bounds: SC_BOUNDS,
  fitBoundsOptions: { padding: 20 },
  style: {
    version: 8,
    sources: {
      naip: {
        type: 'raster',
        tiles: [NAIP_EXPORT],
        tileSize: 256,
        attribution: 'Imagery: USDA NAIP via USGS The National Map',
      },
    },
    layers: [{ id: 'naip', type: 'raster', source: 'naip' }],
  },
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
