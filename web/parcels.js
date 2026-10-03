// Property lines and tax map parcel IDs, read live from each county's own
// public parcel service for the area on screen (never copied: several
// counties restrict redistribution). config/parcel_registry.json lists one
// entry per county (harvest/parcel_registry.py checks them); the viewer
// reads the copy in web/data/parcel_registry.json. Owner names are never
// requested. Pure helpers; parcels-ui.js puts them on the map.
import { queryUrl } from './arcgis.js';

export const PARCEL_MINZOOM = 15;
export const PARCEL_LABEL_MINZOOM = 17;
export const PARCEL_TILE_ZOOM = 15;

// { name, fips, bbox, rings } for each county in web/data/sc-counties.geojson.
export function countyBoxes(geojson) {
  return (geojson?.features ?? []).map((f) => {
    const g = f.geometry;
    const rings = (g.type === 'MultiPolygon' ? g.coordinates : [g.coordinates]).flat();
    const bbox = [Infinity, Infinity, -Infinity, -Infinity];
    for (const [x, y] of rings.flat()) {
      bbox[0] = Math.min(bbox[0], x); bbox[1] = Math.min(bbox[1], y);
      bbox[2] = Math.max(bbox[2], x); bbox[3] = Math.max(bbox[3], y);
    }
    return { name: f.properties.name, fips: f.properties.fips, bbox, rings };
  });
}

function inRings(rings, [x, y]) {
  let inside = false;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}

function crosses([ax, ay], [bx, by], [cx, cy], [dx, dy]) {
  const d = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx);
  if (d === 0) return false;
  const t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / d;
  const u = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / d;
  return t >= 0 && t <= 1 && u >= 0 && u <= 1;
}

// Whether polygon rings and a box [w, s, e, n] overlap.
export function ringsMeetBox(rings, [w, s, e, n]) {
  const corners = [[w, s], [e, s], [e, n], [w, n]];
  if (corners.some((c) => inRings(rings, c))) return true;
  for (const ring of rings) {
    for (let i = 1; i < ring.length; i += 1) {
      const [x, y] = ring[i];
      if (x >= w && x <= e && y >= s && y <= n) return true;
      for (let k = 0; k < 4; k += 1) if (crosses(ring[i - 1], ring[i], corners[k], corners[(k + 1) % 4])) return true;
    }
  }
  return false;
}

// Counties that meet the view. The boundary file is generalized (1:20M)
// and leaves out small islands, so the view is grown by `margin` degrees.
export function countiesForBounds(boxes, [w, s, e, n], margin = 0.03) {
  const grown = [w - margin, s - margin, e + margin, n + margin];
  return boxes.filter(({ bbox: b, rings }) => b[0] <= grown[2] && b[2] >= grown[0] && b[1] <= grown[3] && b[3] >= grown[1]
    && (!rings || ringsMeetBox(rings, grown)));
}

// Whether a registry entry can be queried from the browser, and why not.
export function parcelPlan(entry) {
  if (!entry) return { usable: false, reason: 'not in the parcel registry' };
  if (entry.status === 'no public service' || !entry.url) return { usable: false, reason: 'no public parcel service' };
  if (entry.status === 'blocked') return { usable: false, reason: 'service is blocked' };
  if (entry.cors === false) return { usable: false, reason: 'service blocks browser access (CORS)' };
  if (!entry.id_field) return { usable: false, reason: 'no parcel ID field known' };
  return { usable: true, reason: null };
}

// Only the parcel ID, acreage, address and record link fields; never owners.
export function parcelOutFields(entry) {
  const fields = [entry.id_field, entry.acreage_field, ...(entry.address_fields ?? []), entry.record_link_field];
  return [...new Set(fields.filter(Boolean))];
}

export function parcelQueryUrl(entry, bbox, offset = 0) {
  return queryUrl(entry.url, {
    bbox,
    outFields: parcelOutFields(entry),
    format: entry.geojson === false ? 'json' : 'geojson',
    offset,
    count: Math.min(entry.max_record_count || 1000, 1000),
    orderBy: entry.oid_field || null,
  });
}

function pick(props, field) {
  if (!field) return undefined;
  if (field in props) return props[field];
  const key = Object.keys(props).find((k) => k.toLowerCase() === field.toLowerCase());
  return key === undefined ? undefined : props[key];
}

// http(s) links only (some county record pages have no https).
function webUrl(url) {
  try {
    const u = new URL(String(url).trim());
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null;
  } catch {
    return null;
  }
}

const text = (v) => (v === null || v === undefined ? '' : String(v).trim());

// Link to the county's public record for a parcel: a link the service
// gives, the registry's {id} template, or the county's search page.
export function recordLink(entry, pid, props = {}) {
  const given = webUrl(text(pick(props, entry.record_link_field)));
  if (given) return { url: given, deep: true };
  const tpl = entry.record_url;
  if (!tpl) return { url: null, deep: false };
  if (tpl.includes('{id}')) {
    return pid ? { url: webUrl(tpl.replace('{id}', encodeURIComponent(pid))), deep: true } : { url: null, deep: false };
  }
  return { url: webUrl(tpl), deep: false };
}

// The few properties the map keeps for a parcel.
export function normalizeParcel(entry, props) {
  const pid = text(pick(props, entry.id_field)) || null;
  const acresRaw = Number.parseFloat(text(pick(props, entry.acreage_field)));
  const address = (entry.address_fields ?? []).map((f) => text(pick(props, f))).filter(Boolean).join(' ') || null;
  const link = recordLink(entry, pid, props);
  return {
    pid,
    acres: Number.isFinite(acresRaw) && acresRaw > 0 ? Math.round(acresRaw * 100) / 100 : null,
    address,
    county: entry.county,
    url: link.url,
    deep_link: link.deep,
  };
}

export function describeParcel(p) {
  const rows = [['Parcel ID (TMS/PIN)', p.pid ?? 'not given']];
  if (p.acres != null) rows.push(['Acreage', `${p.acres} ac`]);
  if (p.address) rows.push(['Address', p.address]);
  return {
    title: p.pid ? `Parcel ${p.pid}` : 'Parcel',
    rows,
    source: `${p.county} County parcel service (live)`,
    link: p.url ? { url: p.url, text: p.deep_link ? 'County record' : 'County record search' } : null,
  };
}

export function parcelLayers(source) {
  return [
    { id: 'parcels-fill', type: 'fill', source, minzoom: PARCEL_MINZOOM,
      paint: { 'fill-color': '#ffd54f', 'fill-opacity': 0.04 } },
    { id: 'parcels-casing', type: 'line', source, minzoom: PARCEL_MINZOOM,
      paint: { 'line-color': '#000000', 'line-opacity': 0.5, 'line-width': ['interpolate', ['linear'], ['zoom'], 15, 2.2, 19, 4] } },
    { id: 'parcels-line', type: 'line', source, minzoom: PARCEL_MINZOOM,
      paint: { 'line-color': '#ffd54f', 'line-width': ['interpolate', ['linear'], ['zoom'], 15, 0.8, 19, 1.8] } },
    { id: 'parcels-label', type: 'symbol', source, minzoom: PARCEL_LABEL_MINZOOM, filter: ['has', 'pid'],
      layout: { 'text-field': ['get', 'pid'], 'text-font': ['Noto Sans Regular'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 17, 10, 20, 13], 'text-padding': 2, 'text-max-width': 12 },
      paint: { 'text-color': '#fff8d6', 'text-halo-color': '#000000', 'text-halo-width': 1.4 } },
  ];
}

export const PARCEL_LAYER_IDS = parcelLayers('x').map((l) => l.id);
