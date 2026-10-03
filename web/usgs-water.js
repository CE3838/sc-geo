// USGS water monitoring stations and their recent readings, live from the
// USGS Water Data APIs (no key; CORS open). Everything that knows the API's
// URLs and JSON shapes is in `ogcAdapter`, so another service (such as the
// legacy NWIS Instantaneous Values service, which USGS is retiring) can be
// swapped in with the same methods. The rest turns readings into a common
// station model, caches areas already loaded and is free of DOM and MapLibre
// so it can be tested with `node --test`.

export const OGC_BASE = 'https://api.waterdata.usgs.gov/ogcapi/v1';
export const WATER_DATA_CITATION = 'USGS Water Data';
export const WATER_DATA_SOURCE = 'U.S. Geological Survey, Water Data APIs (api.waterdata.usgs.gov)';

// Water-level parameters (and discharge, secondary). Labels follow the USGS
// parameter-codes collection, shortened.
export const WATER_PARAMS = {
  '00065': { label: 'Gage height', kind: 'level' },
  '63160': { label: 'Water level above NAVD88', kind: 'level' },
  '62614': { label: 'Lake or reservoir elevation above NGVD29', kind: 'level' },
  '62615': { label: 'Lake or reservoir elevation above NAVD88', kind: 'level' },
  '62619': { label: 'Estuary or ocean water elevation above NGVD29', kind: 'level' },
  '62620': { label: 'Estuary or ocean water elevation above NAVD88', kind: 'level' },
  '72279': { label: 'Tidal elevation (NOS-averaged, NAVD88)', kind: 'level' },
  '72019': { label: 'Depth to water below land surface', kind: 'depth', invert: true },
  '62610': { label: 'Groundwater level above NGVD29', kind: 'level' },
  '62611': { label: 'Groundwater level above NAVD88', kind: 'level' },
  '00060': { label: 'Discharge', kind: 'discharge' },
};
export const PARAM_CODES = Object.keys(WATER_PARAMS);

// Which reading leads for each kind of station.
export const PRIORITY = {
  stream: ['00065', '63160', '62620', '00060'],
  lake: ['62615', '62614', '63160', '00065', '00060'],
  tidal: ['62620', '63160', '62619', '72279', '00065', '00060'],
  well: ['72019', '62611', '62610'],
};

export const STATION_TYPES = {
  stream: 'Stream gage',
  lake: 'Lake or reservoir',
  well: 'Groundwater well',
  tidal: 'Tidal or estuary',
};

export const STATUS_TEXT = {
  current: 'Reading in the last 3 hours',
  delayed: 'Last reading 3 hours to 3 days old',
  stale: 'Last reading more than 3 days old',
  issue: 'No value (equipment, ice, maintenance…)',
};

// Qualifier codes: the OGC API's words and the legacy service's short codes.
const QUALIFIERS = {
  ICE: 'Ice affected', Ice: 'Ice affected',
  EQUIP: 'Equipment malfunction', Eqp: 'Equipment malfunction',
  MAINT: 'Maintenance', Mnt: 'Maintenance',
  ESTIMATED: 'Estimated', e: 'Estimated',
  P: 'Provisional', PROVISIONAL: 'Provisional', A: 'Approved',
  BACKWATER: 'Backwater', Bkw: 'Backwater',
  DISCONTINUED: 'Discontinued', Dis: 'Discontinued',
  SEASONAL: 'Seasonal', Ssn: 'Seasonal',
  DRY: 'Dry', Dry: 'Dry',
  ZEROFLOW: 'Zero flow', ZFl: 'Zero flow',
  FLOOD: 'Flood damage', Fld: 'Flood damage',
  RATINGDEV: 'Rating being developed', Rat: 'Rating being developed',
  UNAVAIL: 'Unavailable',
  TIDE: 'Tidally affected',
  REGULATED: 'Regulated',
  DEBRIS: 'Debris',
  LESSTHAN: 'Less than value shown', '<': 'Less than value shown',
  BLWMIN: 'Below minimum',
  DIFFDATUM: 'Different datum',
};

export function qualifierLabels(codes) {
  return (codes ?? []).map((code) => ({ code, text: QUALIFIERS[code] ?? code }));
}

const ID_RE = /^[A-Za-z0-9]+-[A-Za-z0-9]+$/;
function checkId(id) {
  if (!ID_RE.test(id)) throw new RangeError(`bad monitoring location id: ${id}`);
  return id;
}

export function stationPageUrl(id) {
  return `https://waterdata.usgs.gov/monitoring-location/${checkId(id)}/`;
}

const round = (v) => Number(v.toFixed(5));
function bboxParam(bbox) {
  const [w, s, e, n] = bbox;
  if (![w, s, e, n].every(Number.isFinite) || w >= e || s >= n) throw new RangeError(`bad bbox: ${bbox}`);
  return [w, s, e, n].map(round).join(',');
}

const num = (v) => (v === null || v === undefined || v === '' ? null : (Number.isFinite(Number(v)) ? Number(v) : null));
const quals = (q) => (Array.isArray(q) ? q : q ? String(q).split(/[ ,]+/).filter(Boolean) : []);
// Daily values are dates; place them at midday UTC.
const timeOf = (s) => Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(s) ? `${s}T12:00:00Z` : s);

const LATEST_PROPS = ['monitoring_location_id', 'parameter_code', 'time', 'value', 'unit_of_measure', 'approval_status', 'qualifier'];
const SERIES_PROPS = ['time', 'value', 'unit_of_measure', 'approval_status', 'qualifier'];
const LOCATION_PROPS = ['monitoring_location_number', 'monitoring_location_name', 'site_type_code', 'site_type',
  'state_name', 'altitude', 'vertical_datum'];
export const RANGES = {
  '7d': { label: '7 days', days: 7, collection: 'continuous', time: 'P7D' },
  '30d': { label: '30 days', days: 30, collection: 'continuous', time: 'P30D' },
  '1y': { label: '1 year', days: 365, collection: 'daily', time: 'P1Y', statistic: '00003' },
};

function query(collection, params) {
  return `${OGC_BASE}/collections/${collection}/items?${new URLSearchParams({ f: 'json', ...params })}`;
}

export const ogcAdapter = {
  name: 'USGS Water Data OGC API',
  // Latest reading of each water time series in a bbox, from the last 30 days.
  latestUrl(bbox, { limit = 2000 } = {}) {
    return query('latest-continuous', {
      bbox: bboxParam(bbox), parameter_code: PARAM_CODES.join(','), time: 'P30D',
      limit: String(limit), properties: LATEST_PROPS.join(','),
    });
  },
  locationsUrl(ids) {
    return query('monitoring-locations', { id: ids.map(checkId).join(','), limit: String(ids.length),
      properties: LOCATION_PROPS.join(',') });
  },
  seriesUrl(id, param, range) {
    const r = RANGES[range];
    if (!r) throw new RangeError(`bad range: ${range}`);
    if (!/^\d{5}$/.test(param)) throw new RangeError(`bad parameter code: ${param}`);
    const params = { monitoring_location_id: checkId(id), parameter_code: param, time: r.time };
    if (r.statistic) params.statistic_id = r.statistic;
    return query(r.collection, { ...params, limit: '10000', properties: SERIES_PROPS.join(','), skipGeometry: 'true' });
  },
  nextUrl(json) {
    const href = json?.links?.find((l) => l.rel === 'next')?.href;
    return href && href.startsWith('https://api.waterdata.usgs.gov/') ? href : null;
  },
  parseLatest(json) {
    return (json?.features ?? []).map((f) => {
      const p = f.properties;
      return {
        id: p.monitoring_location_id, param: p.parameter_code, value: num(p.value), unit: p.unit_of_measure,
        time: timeOf(p.time), approval: p.approval_status ?? null, qualifiers: quals(p.qualifier),
        lng: f.geometry?.coordinates?.[0], lat: f.geometry?.coordinates?.[1],
      };
    }).filter((r) => r.id && r.param && Number.isFinite(r.lng) && Number.isFinite(r.lat));
  },
  parseLocations(json) {
    const out = new Map();
    for (const f of json?.features ?? []) {
      const p = f.properties;
      out.set(f.id, {
        id: f.id, number: p.monitoring_location_number, name: p.monitoring_location_name,
        siteTypeCode: p.site_type_code, siteType: p.site_type, state: p.state_name,
        altitude: p.altitude ?? null, datum: p.vertical_datum ?? null,
      });
    }
    return out;
  },
  parseSeries(json) {
    const feats = json?.features ?? [];
    const points = feats.map((f) => ({
      t: timeOf(f.properties.time), v: num(f.properties.value),
      approval: f.properties.approval_status ?? null, qualifiers: quals(f.properties.qualifier),
    })).filter((p) => Number.isFinite(p.t)).sort((a, b) => a.t - b.t);
    return { points, unit: feats.find((f) => f.properties.unit_of_measure)?.properties.unit_of_measure ?? null };
  },
};

// Fetch a URL and every page after it (the adapter's next links).
export async function fetchAllPages(url, { fetch = globalThis.fetch, adapter = ogcAdapter, signal, maxPages = 20 } = {}) {
  const features = [];
  let next = url;
  for (let page = 0; next && page < maxPages; page += 1) {
    const r = await fetch(next, { signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const json = await r.json();
    features.push(...(json.features ?? []));
    next = adapter.nextUrl(json);
  }
  return features;
}

// --- station model ----------------------------------------------------------------

export function classifyType(siteTypeCode, params = []) {
  const code = siteTypeCode ?? '';
  if (code.startsWith('GW')) return 'well';
  if (code === 'LK') return 'lake';
  if (code === 'ST-TS' || code.startsWith('ES') || code.startsWith('OC')) return 'tidal';
  if (code.startsWith('ST') || code.startsWith('SP') || code.startsWith('WE')) return 'stream';
  if (params.some((p) => ['72019', '62610', '62611'].includes(p))) return 'well';
  if (params.some((p) => ['62614', '62615'].includes(p))) return 'lake';
  if (params.some((p) => ['62619', '62620', '72279'].includes(p))) return 'tidal';
  return 'stream';
}

const HOUR = 3600e3;
export function readingStatus(reading, now) {
  if (!reading) return 'stale';
  if (reading.value === null) return 'issue';
  const age = now - reading.time;
  if (age <= 3 * HOUR) return 'current';
  if (age <= 72 * HOUR) return 'delayed';
  return 'stale';
}

// Group readings by station; keep the latest per parameter; order readings by
// what leads for the station's type.
export function buildStations(readings, locations, now) {
  const groups = new Map();
  for (const r of readings) {
    if (!WATER_PARAMS[r.param]) continue;
    let g = groups.get(r.id);
    if (!g) groups.set(r.id, g = { lng: r.lng, lat: r.lat, byParam: new Map() });
    const prev = g.byParam.get(r.param);
    if (!prev || r.time > prev.time) g.byParam.set(r.param, r);
  }
  const stations = [];
  for (const [id, g] of groups) {
    const loc = locations.get(id);
    const params = [...g.byParam.keys()];
    const type = classifyType(loc?.siteTypeCode, params);
    const order = PRIORITY[type];
    const rank = (p) => { const i = order.indexOf(p); return i < 0 ? order.length + PARAM_CODES.indexOf(p) : i; };
    const list = [...g.byParam.values()].sort((a, b) => rank(a.param) - rank(b.param)).map((r) => ({
      param: r.param, label: WATER_PARAMS[r.param].label, unit: r.unit, value: r.value, time: r.time,
      approval: r.approval, qualifiers: r.qualifiers,
    }));
    // Lead with a reading that has a value, in priority order.
    const primary = list.find((r) => r.value !== null) ?? list[0];
    const number = loc?.number ?? id.replace(/^[A-Z]+-/, '');
    stations.push({
      id, number, type, lng: g.lng, lat: g.lat,
      name: loc?.name ?? `USGS ${number}`, named: Boolean(loc?.name),
      siteType: loc?.siteType ?? null, state: loc?.state ?? null,
      readings: list, primary, status: readingStatus(primary, now),
    });
  }
  return stations;
}

export function stationsToGeoJSON(stations) {
  return {
    type: 'FeatureCollection',
    features: stations.map((s) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [s.lng, s.lat] },
      properties: { id: s.id, type: s.type, status: s.status, icon: `water-${s.type}-${s.status}` },
    })),
  };
}

// --- areas and caching ------------------------------------------------------------

// Widen a view's [w, s, e, n] outward to whole `step` degrees, so nearby
// views share one cached area.
export function snapBbox([w, s, e, n], step = 1) {
  const snap = (v, f) => Number((f(v / step) * step).toFixed(6));
  return [snap(w, Math.floor), snap(s, Math.floor), snap(e, Math.ceil), snap(n, Math.ceil)];
}
export const bboxArea = ([w, s, e, n]) => (e - w) * (n - s);
export const bboxContains = (a, b) => a[0] <= b[0] && a[1] <= b[1] && a[2] >= b[2] && a[3] >= b[3];

// Loads stations area by area and keeps them. `maxArea` (square degrees)
// stops a national view from asking for every station at once.
export function createWaterClient({
  adapter = ogcAdapter, fetch = globalThis.fetch, now = Date.now,
  maxArea = 150, ttl = 10 * 60e3, chunk = 150, step = 1,
} = {}) {
  const readings = new Map(); // `${id}|${param}` -> reading
  const locations = new Map();
  let areas = []; // { bbox, at, promise }
  const seriesCache = new Map();

  const stations = () => buildStations(readings.values(), locations, now());

  async function loadNames(ids, signal) {
    const missing = ids.filter((id) => !locations.has(id));
    const parts = [];
    for (let i = 0; i < missing.length; i += chunk) parts.push(missing.slice(i, i + chunk));
    await Promise.all(parts.map(async (part) => {
      try {
        const feats = await fetchAllPages(adapter.locationsUrl(part), { fetch, adapter, signal });
        for (const [id, loc] of adapter.parseLocations({ features: feats })) locations.set(id, loc);
      } catch (err) {
        if (signal?.aborted) throw err;
        console.warn?.('Station names not loaded:', err.message);
      }
    }));
  }

  return {
    adapter,
    stations,
    get size() { return new Set([...readings.values()].map((r) => r.id)).size; },
    // status: 'loaded' | 'cached' | 'too-large'
    async loadArea(view, { signal } = {}) {
      const bbox = snapBbox(view, step);
      if (bboxArea(bbox) > maxArea) return { status: 'too-large', bbox, stations: stations() };
      const t = now();
      areas = areas.filter((a) => t - a.at < ttl);
      const hit = areas.find((a) => bboxContains(a.bbox, bbox));
      if (hit) {
        await hit.promise;
        return { status: hit.done ? 'cached' : 'loaded', bbox, stations: stations() };
      }
      const area = { bbox, at: t, done: false };
      area.promise = (async () => {
        const feats = await fetchAllPages(adapter.latestUrl(bbox), { fetch, adapter, signal });
        const fresh = adapter.parseLatest({ features: feats });
        // Replace what this area held, so series that went quiet drop out.
        for (const [key, r] of readings) {
          if (bboxContains(bbox, [r.lng, r.lat, r.lng, r.lat])) readings.delete(key);
        }
        for (const r of fresh) readings.set(`${r.id}|${r.param}`, r);
        await loadNames([...new Set(fresh.map((r) => r.id))], signal);
      })();
      areas.push(area);
      try {
        await area.promise;
        area.done = true;
      } catch (err) {
        areas = areas.filter((a) => a !== area);
        throw err;
      }
      return { status: 'loaded', bbox, stations: stations() };
    },
    async series(id, param, range, { signal } = {}) {
      const key = `${id}|${param}|${range}`;
      const t = now();
      const hit = seriesCache.get(key);
      if (hit && t - hit.at < ttl) return hit.promise;
      const promise = fetchAllPages(adapter.seriesUrl(id, param, range), { fetch, adapter, signal, maxPages: 5 })
        .then((feats) => ({ ...adapter.parseSeries({ features: feats }), retrieved: t, daily: RANGES[range].collection === 'daily',
          url: adapter.seriesUrl(id, param, range) }));
      seriesCache.set(key, { at: t, promise });
      promise.catch(() => seriesCache.delete(key));
      return promise;
    },
  };
}

export function debounce(fn, ms, clock = globalThis) {
  let timer = null;
  return (...args) => {
    if (timer !== null) clock.clearTimeout(timer);
    timer = clock.setTimeout(() => { timer = null; fn(...args); }, ms);
  };
}
