// Roads with names and route numbers, read live from SCDOT's public road
// inventory on ArcGIS Online for the area on screen (not copied here).
// Statewide_Highways is the state highway system (interstates, US and SC
// routes, state secondary "S-" roads, ramps); OTHER_ROADS holds county,
// city and private roads. Both carry ROUTE_TYPE, ROUTE_NUMB and STREET_NAM.
// Pure helpers and layer specs; roads-ui.js puts them on the map.

const ORG = 'https://services1.arcgis.com/VaY7cY9pvUYUP1Lf/arcgis/rest/services';
export const SCDOT_HIGHWAYS = `${ORG}/Statewide_Highways/FeatureServer/0`;
export const SCDOT_OTHER_ROADS = `${ORG}/OTHER_ROADS/FeatureServer/0`;
export const ROAD_ATTRIBUTION = 'Roads: SC Department of Transportation road inventory';
export const ROAD_FIELDS = ['FID', 'ROUTE_TYPE', 'ROUTE_NUMB', 'ROUTE_AUX', 'STREET_NAM', 'COUNTY_ID'];

// Detail by zoom: interstates at state scale, US and SC highways from z8,
// every road (with names) from z13. Each tier is its own map source; its
// features are queried per slippy tile at `tileZoom` and cached.
export const ROAD_TIERS = [
  {
    id: 'interstate', source: 'roads-state', minzoom: 0, maxzoom: 13, tileZoom: 6, maxTiles: 30,
    maxAllowableOffset: 0.002, precision: 4,
    layers: [{ name: 'Statewide_Highways', url: SCDOT_HIGHWAYS, where: "ROUTE_TYPE='I-'" }],
  },
  {
    id: 'highway', source: 'roads-hwy', minzoom: 8, maxzoom: 13, tileZoom: 9, maxTiles: 30,
    maxAllowableOffset: 0.0005, precision: 5,
    layers: [{ name: 'Statewide_Highways', url: SCDOT_HIGHWAYS, where: "ROUTE_TYPE IN ('US','SC')" }],
  },
  {
    id: 'local', source: 'roads-local', minzoom: 13, maxzoom: 24, tileZoom: 13, maxTiles: 20,
    maxAllowableOffset: 0.00002, precision: 6,
    layers: [
      { name: 'Statewide_Highways', url: SCDOT_HIGHWAYS, where: '1=1' },
      { name: 'OTHER_ROADS', url: SCDOT_OTHER_ROADS, where: '1=1' },
    ],
  },
];
export const ROAD_SOURCES = ROAD_TIERS.map((t) => t.source);

export function tiersForZoom(zoom) {
  return ROAD_TIERS.filter((t) => zoom >= t.minzoom && zoom < t.maxzoom);
}

// --- names and route numbers -----------------------------------------------------

const ABBREV = { AV: 'Ave', JR: 'Jr', SR: 'Sr' };
const UPPER = new Set(['N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW', 'US', 'SC', 'II', 'III', 'IV']);

function word(w) {
  if (UPPER.has(w)) return w;
  if (ABBREV[w]) return ABBREV[w];
  if (/\d/.test(w)) return w.replace(/(\d)([A-Z]+)$/, (_, d, s) => d + s.toLowerCase()); // 1ST -> 1st, I-26 stays
  if (/^MC[A-Z]{2,}/.test(w)) return `Mc${w[2]}${w.slice(3).toLowerCase()}`;
  return w[0] + w.slice(1).toLowerCase();
}

// "RIVERS AV" -> "Rivers Ave". Mixed-case names are kept as written.
export function streetName(raw) {
  const s = String(raw ?? '').trim().replace(/\s+/g, ' ');
  if (!s || /^(NO NAME|UNNAMED|UNKNOWN)$/i.test(s)) return null;
  if (/[a-z]/.test(s)) return s;
  return s.split(' ').map((w) => w.split('-').map(word).join('-')).join(' ');
}

const AUX = { BUS: 'Bus', BU1: 'Bus', BU2: 'Bus', ALT: 'Alt', BYP: 'Byp', CON: 'Conn', CO1: 'Conn', CO2: 'Conn',
  SPR: 'Spur', TRK: 'Truck' };
const RAMPS = new Set(['R-', 'RS', 'CD']);

// { cls, ref, name } for an SCDOT road segment.
export function classifyRoad(p) {
  const type = String(p.ROUTE_TYPE ?? '').trim();
  const num = Number(p.ROUTE_NUMB);
  const has = Number.isFinite(num) && num > 0;
  const aux = AUX[String(p.ROUTE_AUX ?? '').trim().toUpperCase()];
  let cls = 'local';
  let ref = null;
  if (type === 'I-' && has) { cls = 'interstate'; ref = `I-${num}`; }
  else if (type === 'US' && has) { cls = 'us'; ref = `US ${num}`; }
  else if (type === 'SC' && has) { cls = 'sc'; ref = `SC ${num}`; }
  else if (type === 'S-') { cls = 'secondary'; ref = has ? (p.COUNTY_ID ? `S-${p.COUNTY_ID}-${num}` : `S-${num}`) : null; }
  else if (type === 'D-') cls = 'secondary';
  else if (RAMPS.has(type)) cls = 'ramp';
  else if (type === 'PR') cls = 'private';
  if (ref && aux && ['interstate', 'us', 'sc'].includes(cls)) ref = `${ref} ${aux}`;
  let name = streetName(p.STREET_NAM);
  // "INTERSTATE 26", "HIGHWAY 78": the route number again, not a name.
  if (name && has && new RegExp(`^(interstate|highway|hwy|state highway|state road|us|sc)[ -]*${num}$`, 'i').test(name)) name = null;
  return { cls, ref, name };
}

const CLASS_LABEL = {
  interstate: 'Interstate', us: 'U.S. highway', sc: 'S.C. highway', secondary: 'State secondary road',
  ramp: 'Ramp', local: 'Local road', private: 'Private road',
};
const RANK = { interstate: 7, us: 6, sc: 5, ramp: 4, secondary: 3, local: 2, private: 1 };

// GeoJSON feature from a service feature, with the small set of properties
// the map uses. `layer` and `fid` locate the source record.
export function normalizeRoad(feature, layer) {
  const p = feature.properties ?? {};
  const { cls, ref, name } = classifyRoad(p);
  const fid = p.FID ?? p.OBJECTID ?? feature.id ?? null;
  return {
    type: 'Feature',
    properties: { cls, ref, name, rank: RANK[cls], layer, fid, key: `${layer}:${fid}` },
    geometry: feature.geometry,
  };
}

export function describeRoad({ cls, ref, name, layer, fid }) {
  return {
    title: name ?? ref ?? 'Unnamed road',
    detail: [name ? ref : null, CLASS_LABEL[cls] ?? 'Road'].filter(Boolean).join(' · '),
    source: layer ? `SCDOT road inventory (${layer}${fid != null ? ` FID ${fid}` : ''})` : 'SCDOT road inventory',
  };
}

// --- route shields (drawn on a canvas by roads-ui.js) ---------------------------------

// Shape, text and size (CSS px) of the shield for a route number.
export function shieldSpec(cls, ref) {
  if (!ref || !['interstate', 'us', 'sc'].includes(cls)) return null;
  const text = (/\d+/.exec(ref) ?? [''])[0];
  const width = Math.max(cls === 'interstate' ? 22 : 20, 10 + 7.5 * text.length);
  if (cls === 'interstate') return { shape: 'interstate', text, width, height: 22, fill: '#1c4fa1', band: '#c8102e', textColor: '#ffffff' };
  if (cls === 'us') return { shape: 'us', text, width, height: 22, fill: '#ffffff', stroke: '#1a1a1a', textColor: '#1a1a1a' };
  return { shape: 'sc', text, width, height: 20, fill: '#ffffff', stroke: '#1a1a1a', textColor: '#1a1a1a' };
}

// --- styling ----------------------------------------------------------------------------

const COLOR = ['match', ['get', 'cls'],
  'interstate', '#ff7043', 'us', '#ffca28', 'sc', '#fff176', 'ramp', '#ffab91',
  'secondary', '#ffffff', 'private', '#d7d7d7', '#f5f5f5'];

// Line width by class at a zoom; `extra` widens it for the casing.
function width(z, extra = 0) {
  const w = {
    5: { interstate: 1.1, us: 0.7, sc: 0.6, ramp: 0.5, secondary: 0.5, local: 0.4, private: 0.3 },
    9: { interstate: 2.2, us: 1.6, sc: 1.3, ramp: 0.8, secondary: 0.8, local: 0.6, private: 0.4 },
    13: { interstate: 4, us: 3.2, sc: 2.8, ramp: 1.8, secondary: 2, local: 1.6, private: 1 },
    17: { interstate: 11, us: 9, sc: 8, ramp: 5, secondary: 7, local: 6, private: 3.5 },
  }[z];
  return ['match', ['get', 'cls'], ...Object.entries(w).flatMap(([k, v]) => [k, v + extra]), w.local + extra];
}
const WIDTH = (extra) => ['interpolate', ['exponential', 1.5], ['zoom'], 5, width(5, extra), 9, width(9, extra),
  13, width(13, extra), 17, width(17, extra)];
const SORT = ['match', ['get', 'cls'], ...Object.entries(RANK).flat(), 0];

const ZOOMS = { 'roads-state': [0, 13], 'roads-hwy': [8, 13], 'roads-local': [13, 24] };

export function roadLayers() {
  const lines = [];
  for (const src of ROAD_SOURCES) {
    const [minzoom, maxzoom] = ZOOMS[src];
    const z = { minzoom, maxzoom };
    lines.push(
      { id: `${src}-casing`, type: 'line', source: src, ...z,
        layout: { 'line-join': 'round', 'line-cap': 'round', 'line-sort-key': SORT },
        paint: { 'line-color': '#111111', 'line-opacity': 0.55, 'line-width': WIDTH(1.6) } },
      { id: `${src}-line`, type: 'line', source: src, ...z,
        layout: { 'line-join': 'round', 'line-cap': 'round', 'line-sort-key': SORT },
        paint: { 'line-color': COLOR, 'line-width': WIDTH(0) } },
    );
  }
  // SCDOT segments are short (about one per block or mile), too short at
  // small scales to fit a shield along them, so those tiers place shields at
  // segment starts; collision padding, not spacing, keeps them apart.
  const shield = (id, source, minzoom, maxzoom, classes, padding, placement = 'point') => ({
    id, type: 'symbol', source, minzoom, maxzoom,
    filter: ['all', ['has', 'ref'], ['in', ['get', 'cls'], ['literal', classes]]],
    layout: {
      'symbol-placement': placement, 'symbol-spacing': 420, 'icon-image': ['concat', 'shield:', ['get', 'cls'], ':', ['get', 'ref']],
      'icon-rotation-alignment': 'viewport', 'icon-padding': padding, 'icon-size': ['interpolate', ['linear'], ['zoom'], 6, 0.75, 12, 1],
      'symbol-sort-key': ['-', 10, ['get', 'rank']],
    },
  });
  return [
    ...lines,
    {
      id: 'roads-names', type: 'symbol', source: 'roads-local', minzoom: 13, filter: ['has', 'name'],
      layout: {
        'symbol-placement': 'line', 'symbol-spacing': 320, 'text-field': ['get', 'name'], 'text-font': ['Noto Sans Medium'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 13, 10.5, 18, 14], 'text-max-angle': 30,
        'text-padding': 4, 'symbol-sort-key': ['-', 10, ['get', 'rank']],
      },
      paint: { 'text-color': '#1b1f23', 'text-halo-color': '#ffffff', 'text-halo-width': 1.6, 'text-halo-blur': 0.3 },
    },
    // Later layers are placed first: interstate shields win collisions.
    shield('roads-shields-hwy', 'roads-hwy', 9, 13, ['us', 'sc'], 40),
    shield('roads-shields-state', 'roads-state', 5, 13, ['interstate'], 40),
    shield('roads-shields-local', 'roads-local', 13, 24, ['interstate', 'us', 'sc'], 60, 'line'),
  ];
}

export const ROAD_LINE_LAYER_IDS = roadLayers().filter((l) => l.type === 'line').map((l) => l.id);
export const ROAD_LABEL_LAYER_IDS = roadLayers().filter((l) => l.type === 'symbol').map((l) => l.id);
export const ROAD_CLICK_LAYER_IDS = ROAD_LINE_LAYER_IDS.filter((id) => id.endsWith('-line'));
