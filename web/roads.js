// Roads with names and route numbers, read live from the US Census Bureau's
// TIGERweb service (TIGER/Line, public domain) for the area on screen; not
// copied here. Primary Roads (MTFCC S1100), Secondary Roads (S1200) and Local
// Roads (S1400 and smaller) each carry NAME (full street or route name),
// RTTYP (route type: I, U, S, C, M) and OID (the TIGER LINEARID).
// Pure helpers and layer specs; roads-ui.js puts them on the map.

export const TIGER_TRANSPORTATION = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer';
// Full-detail layers; the service also has generalized copies for small scales.
export const TIGER_PRIMARY_ROADS = `${TIGER_TRANSPORTATION}/2`;
export const TIGER_SECONDARY_ROADS = `${TIGER_TRANSPORTATION}/6`;
export const TIGER_LOCAL_ROADS = `${TIGER_TRANSPORTATION}/8`;
export const ROAD_ATTRIBUTION = 'Roads: US Census Bureau TIGER/Line (live)';
export const ROAD_FIELDS = ['OBJECTID', 'OID', 'NAME', 'MTFCC', 'RTTYP'];
export const ROAD_ORDER_BY = 'OBJECTID';

const ROUTES = "RTTYP IN ('U','S')";
// Local roads, ramps, service drives, alleys, private and 4WD roads; no walkways,
// stairways, parking lots, trails or internal census features.
const LOCAL_ROADS = "MTFCC IN ('S1400','S1500','S1630','S1640','S1730','S1740')";
const PRIMARY = { name: 'Primary Roads', url: TIGER_PRIMARY_ROADS };
const SECONDARY = { name: 'Secondary Roads', url: TIGER_SECONDARY_ROADS };
const LOCAL = { name: 'Local Roads', url: TIGER_LOCAL_ROADS };

// Detail by zoom: interstates at state scale, US and SC highways from z8,
// every road (with names) from z13. Each tier is its own map source; its
// features are queried per slippy tile at `tileZoom` and cached.
export const ROAD_TIERS = [
  {
    id: 'interstate', source: 'roads-state', minzoom: 0, maxzoom: 13, tileZoom: 6, maxTiles: 30,
    maxAllowableOffset: 0.002, precision: 4,
    layers: [{ ...PRIMARY, where: "RTTYP='I'" }],
  },
  {
    id: 'highway', source: 'roads-hwy', minzoom: 8, maxzoom: 13, tileZoom: 9, maxTiles: 30,
    maxAllowableOffset: 0.0005, precision: 5,
    layers: [{ ...PRIMARY, where: ROUTES }, { ...SECONDARY, where: ROUTES }],
  },
  {
    id: 'local', source: 'roads-local', minzoom: 13, maxzoom: 24, tileZoom: 13, maxTiles: 20,
    maxAllowableOffset: 0.00002, precision: 6,
    layers: [{ ...PRIMARY, where: '1=1' }, { ...SECONDARY, where: '1=1' }, { ...LOCAL, where: LOCAL_ROADS }],
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

// "RIVERS AV" -> "Rivers Ave". Mixed-case names (TIGER's) are kept as written.
export function streetName(raw) {
  const s = String(raw ?? '').trim().replace(/\s+/g, ' ');
  if (!s || /^(NO NAME|UNNAMED|UNKNOWN)$/i.test(s)) return null;
  if (/[a-z]/.test(s)) return s;
  return s.split(' ').map((w) => w.split('-').map(word).join('-')).join(' ');
}

const AUX = { BUS: 'Bus', BUSINESS: 'Bus', ALT: 'Alt', ALTERNATE: 'Alt', BYP: 'Byp', BYPASS: 'Byp', CON: 'Conn',
  CONN: 'Conn', CONNECTOR: 'Conn', SPR: 'Spur', SPUR: 'Spur', TRK: 'Truck', TRUCK: 'Truck' };
const ROUTE_NAME = {
  I: [/^(?:I|Interstate)[\s-]*(\d+)\b\s*(.*)$/i, 'interstate', (n) => `I-${n}`],
  U: [/^(?:US|U\.S\.)[\s-]*(?:Hwy|Highway|Rte|Route)?[\s-]*(\d+)\b\s*(.*)$/i, 'us', (n) => `US ${n}`],
  S: [/^(?:State|SC|S\.C\.)[\s-]*(?:Hwy|Highway|Rte|Route)[\s-]*(\d+)\b\s*(.*)$/i, 'sc', (n) => `SC ${n}`],
};

// { cls, ref } for a TIGER route name ("I- 26", "US Hwy 52 Spr", "State Hwy 61"), or null.
export function routeRef(name, rttyp) {
  const rule = ROUTE_NAME[String(rttyp ?? '').trim().toUpperCase()];
  const m = rule && rule[0].exec(String(name ?? '').trim().replace(/\s+/g, ' '));
  if (!m) return null;
  const aux = AUX[(m[2].split(' ')[0] ?? '').toUpperCase().replace(/\.$/, '')];
  return { cls: rule[1], ref: aux ? `${rule[2](Number(m[1]))} ${aux}` : rule[2](Number(m[1])) };
}

// MTFCC (feature class) for roads without a route number.
const BY_MTFCC = { S1100: 'secondary', S1200: 'secondary', S1630: 'ramp', S1740: 'private', S1500: 'private' };

// { cls, ref, name } for a TIGER road record.
export function classifyRoad(p) {
  const route = routeRef(p.NAME, p.RTTYP);
  if (route) return { ...route, name: null }; // the name only repeats the route number
  const rttyp = String(p.RTTYP ?? '').trim().toUpperCase();
  const cls = BY_MTFCC[p.MTFCC] ?? (['S', 'C'].includes(rttyp) ? 'secondary' : 'local');
  return { cls, ref: null, name: streetName(p.NAME) };
}

const CLASS_LABEL = {
  interstate: 'Interstate', us: 'U.S. highway', sc: 'S.C. highway', secondary: 'Secondary road',
  ramp: 'Ramp', local: 'Local road', private: 'Private road',
};
const RANK = { interstate: 7, us: 6, sc: 5, ramp: 4, secondary: 3, local: 2, private: 1 };

// GeoJSON feature from a service feature, with the small set of properties
// the map uses. `layer` (TIGERweb layer name) and `fid` (LINEARID) locate the record.
export function normalizeRoad(feature, layer) {
  const p = feature.properties ?? {};
  const { cls, ref, name } = classifyRoad(p);
  const fid = p.OID ?? p.OBJECTID ?? feature.id ?? null;
  return {
    type: 'Feature',
    properties: { cls, ref, name, rank: RANK[cls], layer, fid, key: `${layer}:${fid}` },
    geometry: feature.geometry,
  };
}

const CITE = 'US Census Bureau TIGER/Line';

export function describeRoad({ cls, ref, name, layer, fid }) {
  return {
    title: name ?? ref ?? 'Unnamed road',
    detail: [name ? ref : null, CLASS_LABEL[cls] ?? 'Road'].filter(Boolean).join(' · '),
    source: layer ? `${CITE}, TIGERweb ${layer}${fid != null ? ` (LINEARID ${fid})` : ''}` : CITE,
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
  // TIGER segments are short (about one per block or mile), too short at
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
