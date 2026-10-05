// Roads layer: US Census Bureau TIGER roads read live for the area on screen
// (roads.js), drawn above the geology with casings for aerial imagery,
// route shields and street names, and a row in the Layers panel.
import { LiveTiles, debounce, fetchAllPages, queryUrl, tileBounds } from './arcgis.js';
import { LIVE_ON_AT_START } from './live.js';
import {
  ROAD_ATTRIBUTION, ROAD_CLICK_LAYER_IDS, ROAD_FIELDS, ROAD_ORDER_BY, ROAD_TIERS, describeRoad, normalizeRoad, roadLayers,
  shieldSpec, tiersForZoom,
} from './roads.js';
import { el } from './dom.js';
import { IMAGERY_BOUNDS, onStyleReady } from './geo.js';

const EMPTY = { type: 'FeatureCollection', features: [] };
const PAGE = 2000;

export async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// The view clipped to the area roads exist in (SC and a margin), or null.
export function viewBox(map, limit = IMAGERY_BOUNDS) {
  const b = map.getBounds();
  const box = [Math.max(b.getWest(), limit[0][0]), Math.max(b.getSouth(), limit[0][1]),
    Math.min(b.getEast(), limit[1][0]), Math.min(b.getNorth(), limit[1][1])];
  return box[0] < box[2] && box[1] < box[3] ? box : null;
}

function shieldPath(ctx, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(r, 2 * r);
  ctx.quadraticCurveTo(w / 2, 5 * r, w - r, 2 * r);
  ctx.lineTo(w - r, h * 0.55);
  ctx.quadraticCurveTo(w - r, h * 0.86, w / 2, h - r);
  ctx.quadraticCurveTo(r, h * 0.86, r, h * 0.55);
  ctx.closePath();
}

// Route shield drawn on a canvas, so no sprite sheet is needed.
function drawShield(spec, ratio = 2) {
  const w = Math.round(spec.width * ratio);
  const h = Math.round(spec.height * ratio);
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (spec.shape === 'sc') {
    ctx.beginPath();
    ctx.roundRect(ratio, ratio, w - 2 * ratio, h - 2 * ratio, 4 * ratio);
    ctx.fillStyle = spec.fill;
    ctx.fill();
    ctx.lineWidth = 1.6 * ratio;
    ctx.strokeStyle = spec.stroke;
    ctx.stroke();
  } else {
    shieldPath(ctx, w, h, ratio);
    ctx.fillStyle = spec.fill;
    ctx.fill();
    if (spec.band) {
      ctx.save();
      ctx.clip();
      ctx.fillStyle = spec.band;
      ctx.fillRect(0, 0, w, h * 0.3);
      ctx.restore();
    }
    shieldPath(ctx, w, h, ratio);
    ctx.lineWidth = 1.5 * ratio;
    ctx.strokeStyle = spec.stroke ?? '#ffffff';
    ctx.stroke();
  }
  ctx.fillStyle = spec.textColor;
  ctx.font = `700 ${(spec.text.length > 2 ? 10.5 : 11.5) * ratio}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(spec.text, w / 2, h * (spec.band ? 0.6 : 0.52));
  return { image: ctx.getImageData(0, 0, w, h), ratio };
}

export function setupRoads(map, ui) {
  let on = LIVE_ON_AT_START.roads;
  let ready = false;
  const row = ui.addLayer({ id: 'roads', label: 'Roads and Route Numbers', order: 40, checked: LIVE_ON_AT_START.roads,
    onChange: (checked) => {
      on = checked;
      for (const l of roadLayers()) if (map.getLayer(l.id)) map.setLayoutProperty(l.id, 'visibility', on ? 'visible' : 'none');
      if (on) refresh();
      else row.setNote('');
    } });

  async function fetchTier(tier, tile) {
    const bbox = tileBounds(tile);
    const out = [];
    for (const layer of tier.layers) {
      const { features } = await fetchAllPages(fetchJson, (offset) => queryUrl(layer.url, {
        bbox, where: layer.where, outFields: ROAD_FIELDS, offset, count: PAGE,
        maxAllowableOffset: tier.maxAllowableOffset, precision: tier.precision, orderBy: ROAD_ORDER_BY,
      }), { pageSize: PAGE, maxPages: 5 });
      for (const f of features) if (f.geometry) out.push(normalizeRoad(f, layer.name));
    }
    return out;
  }
  const live = new Map(ROAD_TIERS.map((t) => [t.id, new LiveTiles({
    tileZoom: t.tileZoom, maxTiles: t.maxTiles, keyOf: (f) => f.properties.key, fetchTile: (tile) => fetchTier(t, tile),
  })]));

  let generation = 0;
  async function update() {
    if (!ready || !on) return;
    const box = viewBox(map);
    if (!box) return;
    const gen = ++generation;
    const tiers = tiersForZoom(map.getZoom());
    row.setNote(' loading…');
    const results = await Promise.all(tiers.map(async (t) => [t, await live.get(t.id).update(box)]));
    if (gen !== generation) return;
    const errors = [];
    for (const [t, r] of results) {
      if (r.tooMany) continue;
      map.getSource(t.source)?.setData({ type: 'FeatureCollection', features: r.features });
      errors.push(...r.errors);
    }
    if (errors.length) console.warn('Roads not loaded for part of the view:', errors[0]);
    row.setNote(errors.length ? ' road service unavailable' : '');
  }
  const refresh = debounce(() => { update().catch((err) => console.warn('Roads:', err.message)); }, 250);

  onStyleReady(map, () => {
    for (const t of ROAD_TIERS) map.addSource(t.source, { type: 'geojson', data: EMPTY, attribution: ROAD_ATTRIBUTION, tolerance: 0.5 });
    // Lines above the geology and under faults and the state outline; labels on top.
    const under = ['faults-shear-band', 'faults-casing', 'sc-outline-casing'].find((id) => map.getLayer(id));
    for (const layer of roadLayers()) {
      map.addLayer(layer, layer.type === 'line' ? under : undefined);
      map.setLayoutProperty(layer.id, 'visibility', on ? 'visible' : 'none');
    }
    ready = true;
    refresh();
  });
  map.on('styleimagemissing', (e) => {
    if (!e.id.startsWith('shield:') || map.hasImage(e.id)) return;
    const [, cls, ...rest] = e.id.split(':');
    const spec = shieldSpec(cls, rest.join(':'));
    if (!spec) {
      map.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) });
      return;
    }
    const { image, ratio } = drawShield(spec);
    map.addImage(e.id, image, { pixelRatio: ratio });
  });
  map.on('moveend', refresh);

  return {
    // Road within a few pixels of a screen point, the most important first.
    roadAt(point, tolerance = 6) {
      if (!on) return null;
      const layers = ROAD_CLICK_LAYER_IDS.filter((id) => map.getLayer(id));
      if (!layers.length) return null;
      const box = [[point.x - tolerance, point.y - tolerance], [point.x + tolerance, point.y + tolerance]];
      const hits = map.queryRenderedFeatures(box, { layers });
      return hits.sort((a, b) => (b.properties.rank ?? 0) - (a.properties.rank ?? 0))[0] ?? null;
    },
    describe(feature) {
      const d = describeRoad(feature.properties);
      return el('div', { class: 'callout-road' },
        el('div', { class: 'feature-layer' }, d.title),
        el('div', { class: 'callout-sub' }, d.detail),
        el('div', { class: 'geo-cite' }, d.source));
    },
  };
}
