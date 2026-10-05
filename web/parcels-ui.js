// Parcels layer: property lines and tax map parcel IDs from each county's
// own public service, queried live for the view from zoom 15 (parcels.js),
// with a row and a status note in the Layers panel. Counties without a
// public service, or whose service fails or blocks browsers, get a note.
import { LiveTiles, debounce, fetchAllPages, tileBounds } from './arcgis.js';
import { LIVE_ON_AT_START } from './live.js';
import {
  PARCEL_LAYER_IDS, PARCEL_MINZOOM, PARCEL_TILE_ZOOM, countiesForBounds, countyBoxes, describeParcel, normalizeParcel,
  parcelLayers, parcelPlan, parcelQueryUrl,
} from './parcels.js';
import { fetchJson, viewBox } from './roads-ui.js';
import { el } from './dom.js';
import { onStyleReady } from './geo.js';

const EMPTY = { type: 'FeatureCollection', features: [] };

export function setupParcels(map, ui) {
  let on = LIVE_ON_AT_START.parcels;
  let ready = false;
  let boxes = [];
  let registry = new Map();
  const status = el('ul', { class: 'parcel-status', 'aria-live': 'polite' });
  status.hidden = !on;
  const row = ui.addLayer({ id: 'parcels', label: 'Parcels (Property Lines)', order: 45, detail: status, checked: LIVE_ON_AT_START.parcels,
    onChange: (checked) => {
      on = checked;
      for (const id of PARCEL_LAYER_IDS) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
      status.hidden = !on;
      refresh();
    } });

  const live = new Map();
  function liveFor(entry) {
    if (!live.has(entry.fips)) {
      const pageSize = Math.min(entry.max_record_count || 1000, 1000);
      live.set(entry.fips, new LiveTiles({
        tileZoom: PARCEL_TILE_ZOOM, maxTiles: 16, keyOf: (f) => f.properties.key,
        fetchTile: async (tile) => {
          const { features } = await fetchAllPages(fetchJson, (offset) => parcelQueryUrl(entry, tileBounds(tile), offset),
            { pageSize, maxPages: 8 });
          return features.filter((f) => f.geometry).map((f, i) => {
            const props = normalizeParcel(entry, f.properties ?? {});
            return { type: 'Feature', geometry: f.geometry,
              properties: { ...props, key: `${entry.fips}:${f.id ?? props.pid ?? `${tile.x}/${tile.y}/${i}`}` } };
          });
        },
      }));
    }
    return live.get(entry.fips);
  }

  function show(lines) {
    status.replaceChildren(...lines.map(({ text, link }) => el('li', {}, text,
      link && ' ', link && el('a', { href: link, target: '_blank', rel: 'noopener noreferrer' }, 'county viewer'))));
  }

  let generation = 0;
  async function update() {
    if (!ready || !on) return;
    if (map.getZoom() < PARCEL_MINZOOM) {
      row.setNote('');
      show([{ text: `Zoom in to see parcels (zoom ${PARCEL_MINZOOM}+; now ${map.getZoom().toFixed(1)}).` }]);
      return;
    }
    const box = viewBox(map);
    const gen = ++generation;
    const counties = box ? countiesForBounds(boxes, box) : [];
    if (!counties.length) {
      map.getSource('parcels')?.setData(EMPTY);
      show([{ text: 'No South Carolina county in view.' }]);
      return;
    }
    row.setNote(' loading…');
    const results = await Promise.all(counties.map(async (c) => {
      const entry = registry.get(c.name);
      const plan = parcelPlan(entry);
      if (!plan.usable) return { c, entry, note: plan.reason };
      const r = await liveFor(entry).update(box);
      return { c, entry, r };
    }));
    if (gen !== generation) return;
    const features = [];
    const lines = [];
    for (const { c, entry, note, r } of results) {
      if (note) {
        lines.push({ text: `${c.name} County: ${note}.`, link: entry?.viewer_url ?? null });
      } else if (r.tooMany) {
        lines.push({ text: `${c.name} County: zoom in further.` });
      } else {
        features.push(...r.features);
        if (r.errors.length && !r.features.length) {
          console.warn(`${c.name} County parcel service:`, r.errors[0]);
          lines.push({ text: `${c.name} County: parcel service unavailable right now.`, link: entry.viewer_url ?? null });
        } else {
          lines.push({ text: `${c.name} County: ${r.features.length.toLocaleString()} parcels`
            + `${r.errors.length ? ' (part of the view failed)' : ''}.` });
        }
      }
    }
    map.getSource('parcels')?.setData({ type: 'FeatureCollection', features });
    row.setNote(features.length ? ` ${features.length.toLocaleString()}` : '');
    show(lines);
  }
  const refresh = debounce(() => { update().catch((err) => console.warn('Parcels:', err.message)); }, 400);

  async function load() {
    try {
      const [reg, counties] = await Promise.all(['data/parcel_registry.json', 'data/sc-counties.geojson'].map(async (u) => {
        const r = await fetch(u);
        if (!r.ok) throw new Error(`${u}: HTTP ${r.status}`);
        return r.json();
      }));
      registry = new Map(reg.counties.map((c) => [c.county, c]));
      boxes = countyBoxes(counties);
      map.addSource('parcels', { type: 'geojson', data: EMPTY, attribution: 'Parcels: county GIS services (live)' });
      // Lines above the geology and under roads, faults and the state outline; IDs on top.
      const under = ['roads-state-casing', 'faults-shear-band', 'faults-casing', 'sc-outline-casing'].find((id) => map.getLayer(id));
      for (const layer of parcelLayers('parcels')) {
        map.addLayer(layer, layer.type === 'symbol' ? undefined : under);
        map.setLayoutProperty(layer.id, 'visibility', on ? 'visible' : 'none');
      }
      ready = true;
      update().catch((err) => console.warn('Parcels:', err.message));
    } catch (err) {
      row.disable('not available');
      console.warn('Parcel layer not loaded:', err.message);
    }
  }
  onStyleReady(map, load);
  map.on('moveend', refresh);

  return {
    parcelAt(point) {
      if (!on || !map.getLayer('parcels-fill') || map.getZoom() < PARCEL_MINZOOM) return null;
      return map.queryRenderedFeatures(point, { layers: ['parcels-fill'] })[0] ?? null;
    },
    describe(feature) {
      const d = describeParcel(feature.properties);
      return el('div', { class: 'callout-parcel' },
        el('div', { class: 'feature-layer' }, d.title),
        el('dl', { class: 'callout-coords' }, ...d.rows.flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, v)])),
        el('div', { class: 'geo-cite' }, d.source,
          d.link && ' · ', d.link && el('a', { href: d.link.url, target: '_blank', rel: 'noopener noreferrer' }, d.link.text)));
    },
  };
}
