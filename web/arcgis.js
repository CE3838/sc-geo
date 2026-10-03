// Live queries against public ArcGIS REST layers (FeatureServer or
// MapServer), for layers that are read from their owners for the area on
// screen instead of copied into this repo (roads, parcels). Pure helpers,
// free of DOM and MapLibre, so they can be tested with `node --test`.

const round6 = (v) => Number(v.toFixed(6));

// Query URL for features intersecting a lon/lat box [west, south, east, north].
export function queryUrl(layerUrl, {
  bbox, where = '1=1', outFields = ['*'], offset = null, count = null, format = 'geojson',
  maxAllowableOffset = null, precision = null, orderBy = null,
}) {
  const params = new URLSearchParams({
    where,
    geometry: bbox.map(round6).join(','),
    geometryType: 'esriGeometryEnvelope',
    inSR: '4326',
    spatialRel: 'esriSpatialRelIntersects',
    outFields: outFields.join(','),
    returnGeometry: 'true',
    outSR: '4326',
  });
  if (maxAllowableOffset != null) params.set('maxAllowableOffset', String(maxAllowableOffset));
  if (precision != null) params.set('geometryPrecision', String(precision));
  if (orderBy) params.set('orderByFields', orderBy);
  if (offset != null) params.set('resultOffset', String(offset));
  if (count != null) params.set('resultRecordCount', String(count));
  params.set('f', format);
  return `${layerUrl.replace(/\/+$/, '')}/query?${params}`;
}

// --- slippy tiles, used as query cells so results can be cached ----------------

const clampLat = (lat) => Math.max(-85.0511, Math.min(85.0511, lat));

function tileXY(lng, lat, z) {
  const n = 2 ** z;
  const rad = (clampLat(lat) * Math.PI) / 180;
  const x = Math.floor(((lng + 180) / 360) * n);
  const y = Math.floor(((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n);
  return [Math.min(n - 1, Math.max(0, x)), Math.min(n - 1, Math.max(0, y))];
}

export function tilesForBounds([w, s, e, n], z) {
  const [x0, y0] = tileXY(w, n, z);
  const [x1, y1] = tileXY(e, s, z);
  const tiles = [];
  for (let x = x0; x <= x1; x += 1) for (let y = y0; y <= y1; y += 1) tiles.push({ x, y, z });
  return tiles;
}

const lat = (y, z) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / 2 ** z))) * 180) / Math.PI;

// [west, south, east, north] of a tile in degrees.
export function tileBounds({ x, y, z }) {
  const n = 2 ** z;
  return [(x / n) * 360 - 180, lat(y + 1, z), ((x + 1) / n) * 360 - 180, lat(y, z)];
}

// --- responses -------------------------------------------------------------------

// Signed area: negative for clockwise rings (esri JSON outer rings).
function ringArea(ring) {
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    a += (ring[j][0] - ring[i][0]) * (ring[j][1] + ring[i][1]);
  }
  return a / 2;
}

function esriGeometry(g) {
  if (!g) return null;
  if (g.rings) {
    const polys = [];
    for (const ring of g.rings) {
      // Clockwise rings start a polygon; counter-clockwise rings are holes of the last one.
      if (ringArea(ring) <= 0 || !polys.length) polys.push([ring]);
      else polys[polys.length - 1].push(ring);
    }
    return polys.length === 1 ? { type: 'Polygon', coordinates: polys[0] } : { type: 'MultiPolygon', coordinates: polys };
  }
  if (g.paths) {
    return g.paths.length === 1 ? { type: 'LineString', coordinates: g.paths[0] } : { type: 'MultiLineString', coordinates: g.paths };
  }
  if (Number.isFinite(g.x) && Number.isFinite(g.y)) return { type: 'Point', coordinates: [g.x, g.y] };
  return null;
}

// esri JSON query result to a GeoJSON FeatureCollection.
export function esriToGeoJSON(json, oidField = json?.objectIdFieldName) {
  return {
    type: 'FeatureCollection',
    features: (json?.features ?? []).map((f) => {
      const props = { ...(f.attributes ?? {}) };
      const id = oidField ? props[oidField] : undefined;
      return { type: 'Feature', ...(id != null ? { id } : {}), properties: props, geometry: esriGeometry(f.geometry) };
    }),
  };
}

// { features (GeoJSON), exceeded } from a query response; throws on a service error.
export function parseQueryResponse(json) {
  if (!json || typeof json !== 'object') throw new Error('unexpected response from the service');
  if (json.error) throw new Error(`service error ${json.error.code ?? ''}: ${json.error.message ?? 'unknown'}`.trim());
  if (json.type === 'FeatureCollection') {
    return {
      features: json.features ?? [],
      exceeded: Boolean(json.properties?.exceededTransferLimit || json.exceededTransferLimit),
    };
  }
  if (Array.isArray(json.features)) {
    return { features: esriToGeoJSON(json).features, exceeded: Boolean(json.exceededTransferLimit) };
  }
  throw new Error('unexpected response from the service');
}

// All pages of a query: `makeUrl(offset)` builds each page's URL and
// `fetchJson(url)` fetches it. Stops when the service says there is no more
// or after `maxPages` (then `truncated` is true).
export async function fetchAllPages(fetchJson, makeUrl, { pageSize, maxPages = 10 } = {}) {
  const features = [];
  for (let page = 0, offset = 0; page < maxPages; page += 1) {
    const { features: got, exceeded } = parseQueryResponse(await fetchJson(makeUrl(offset)));
    features.push(...got);
    if (!exceeded || !got.length) return { features, truncated: false };
    offset += pageSize ?? got.length;
  }
  return { features, truncated: true };
}

// --- caching and pacing ------------------------------------------------------------

// Small LRU cache (Map keeps insertion order; reading moves a key to the end).
export class TileCache {
  constructor(max = 200) {
    this.max = max;
    this.map = new Map();
  }

  get size() { return this.map.size; }

  has(key) { return this.map.has(key); }

  get(key) {
    if (!this.map.has(key)) return undefined;
    const v = this.map.get(key);
    this.map.delete(key);
    this.map.set(key, v);
    return v;
  }

  set(key, value) {
    this.map.delete(key);
    this.map.set(key, value);
    while (this.map.size > this.max) this.map.delete(this.map.keys().next().value);
  }
}

// Call `fn` once calls stop for `ms`; timers can be injected for tests.
export function debounce(fn, ms, clock = globalThis) {
  let timer = null;
  const debounced = (...args) => {
    if (timer !== null) clock.clearTimeout(timer);
    timer = clock.setTimeout(() => { timer = null; fn(...args); }, ms);
  };
  debounced.cancel = () => {
    if (timer !== null) clock.clearTimeout(timer);
    timer = null;
  };
  return debounced;
}

const featureKey = (f) => f.id ?? f.properties?.OBJECTID ?? f.properties?.FID ?? f.properties?.objectid ?? null;

// The features for the tiles covering a box, fetched once per tile with
// `fetchTile(tile)` and cached. A tile that fails is reported in `errors`
// and fetched again next time. Features crossing tiles are kept once.
export class LiveTiles {
  constructor({ tileZoom, fetchTile, maxTiles = 24, cacheSize = 200, keyOf = featureKey }) {
    this.tileZoom = tileZoom;
    this.fetchTile = fetchTile;
    this.maxTiles = maxTiles;
    this.keyOf = keyOf;
    this.cache = new TileCache(cacheSize);
    this.inflight = new Map();
  }

  tile(t) {
    const key = `${t.z}/${t.x}/${t.y}`;
    if (this.cache.has(key)) return Promise.resolve(this.cache.get(key));
    if (!this.inflight.has(key)) {
      const p = Promise.resolve()
        .then(() => this.fetchTile(t))
        .then((features) => { this.cache.set(key, features); return features; })
        .finally(() => this.inflight.delete(key));
      this.inflight.set(key, p);
    }
    return this.inflight.get(key);
  }

  async update(bbox) {
    const tiles = tilesForBounds(bbox, this.tileZoom);
    if (tiles.length > this.maxTiles) return { features: [], errors: [], tooMany: true, truncated: false };
    const results = await Promise.allSettled(tiles.map((t) => this.tile(t)));
    const seen = new Set();
    const features = [];
    const errors = [];
    let truncated = false;
    for (const r of results) {
      if (r.status === 'rejected') {
        errors.push(r.reason?.message ?? String(r.reason));
        continue;
      }
      if (r.value.truncated) truncated = true;
      for (const f of r.value) {
        const k = this.keyOf(f);
        if (k != null) {
          if (seen.has(k)) continue;
          seen.add(k);
        }
        features.push(f);
      }
    }
    return { features, errors, tooMany: false, truncated };
  }
}
