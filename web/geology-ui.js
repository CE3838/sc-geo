// Geology layer: USGS SGMC map units under the state outline, used when the
// merged layers are not available. Layers panel: on/off, color by age or
// rock type, opacity. Map units panel: legend and source. Click: a short
// description and the property card model (card.js).
import { colorExpression, formatAgeRange, legendEntries, mode, safeHttpsUrl, shortCitation } from './geology.js';
import { sgmcCard } from './card.js';
import { el } from './dom.js';
import { onStyleReady } from './geo.js';

const DATA_URL = 'data/geology/sgmc-sc.geojson';
const META_URL = 'data/geology/sgmc-sc.meta.json';

// `ui` is the sidebar (sidebar.js).
export function setupGeology(map, ui) {
  const state = { visible: true, mode: 'age', opacity: 0.55, features: [], meta: null };

  const layer = ui.addLayer({ id: 'geo-visible', label: 'Geologic Map Units (SGMC)', order: 10,
    onChange: (on) => { state.visible = on; apply(); } });
  layer.setNote('Loading…');
  const modeSelect = el('select', {
    id: 'geo-mode',
    onchange: () => {
      state.mode = modeSelect.value;
      apply();
    },
  }, el('option', { value: 'age' }, 'Age'), el('option', { value: 'lith' }, 'Rock type'));
  const opacity = el('input', {
    type: 'range', id: 'geo-opacity', min: '0', max: '100', value: String(state.opacity * 100),
    oninput: () => {
      state.opacity = Number(opacity.value) / 100;
      apply();
    },
  });
  ui.addControls(
    el('div', { class: 'geo-row' }, el('label', { for: 'geo-mode' }, 'Color geology by'), modeSelect),
    el('div', { class: 'geo-row' }, el('label', { for: 'geo-opacity' }, 'Opacity'), opacity));
  const legend = el('ul', { class: 'geo-legend', 'aria-label': 'Legend' });
  const source = el('p', { class: 'geo-source' });
  ui.units.append(legend, source);

  function apply() {
    if (!map.getLayer('geology-fill')) return;
    const vis = state.visible ? 'visible' : 'none';
    map.setLayoutProperty('geology-fill', 'visibility', vis);
    map.setLayoutProperty('geology-line', 'visibility', vis);
    map.setPaintProperty('geology-fill', 'fill-color', colorExpression(state.mode));
    map.setPaintProperty('geology-fill', 'fill-opacity', state.opacity);
    legend.replaceChildren(...legendEntries(state.features, state.mode).map((e) =>
      el('li', {}, el('span', { class: 'geo-swatch', style: `background:${e.color}` }), e.id)));
    legend.setAttribute('aria-label', `Legend: ${mode(state.mode).label}`);
  }

  async function load() {
    try {
      const [data, meta] = await Promise.all([
        fetch(DATA_URL).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))),
        fetch(META_URL).then((r) => (r.ok ? r.json() : null)).catch(() => null),
      ]);
      state.features = data.features;
      state.meta = meta;
      map.addSource('geology', { type: 'geojson', data, attribution: 'Geology: USGS SGMC (Horton and others, 2017)' });
      // Under the neighbor mask and state outline, above the imagery.
      map.addLayer({
        id: 'geology-fill', type: 'fill', source: 'geology',
        paint: { 'fill-color': colorExpression(state.mode), 'fill-opacity': state.opacity },
      }, 'mask');
      map.addLayer({
        id: 'geology-line', type: 'line', source: 'geology', minzoom: 8,
        paint: { 'line-color': '#222', 'line-opacity': 0.45, 'line-width': 0.6 },
      }, 'mask');
      layer.setNote('');
      const when = meta?.retrieved_at ? `, retrieved ${meta.retrieved_at.slice(0, 10)}` : '';
      source.textContent = `Source: USGS State Geologic Map Compilation (1:500,000 state maps)${when}. Colors are derived classes.`;
      apply();
    } catch (err) {
      layer.disable('not in this build');
      source.textContent = 'Geology data is not available in this build.';
      console.warn('Geology layer not loaded:', err);
    }
  }

  onStyleReady(map, load);

  return {
    kind: 'sgmc',
    // Geology unit under a screen point, if the layer is on.
    unitAt(point) {
      if (!state.visible || !map.getLayer('geology-fill')) return null;
      return map.queryRenderedFeatures(point, { layers: ['geology-fill'] })[0] ?? null;
    },
    card(feature, lng, lat, records = []) {
      return sgmcCard({ props: feature.properties, meta: state.meta, records, lng, lat });
    },
    describe(feature) {
      const p = feature.properties;
      const box = el('div', { class: 'feature-info' },
        el('div', { class: 'feature-layer' }, p.name || p.unit || 'Map unit'),
        p.unit && el('div', {}, `Map label: ${p.unit.split(';')[0]}`),
        el('div', {}, `Age: ${formatAgeRange(p.age_min, p.age_max)}`),
        p.major && el('div', {}, `Rock: ${p.major}${p.minor ? `; minor ${p.minor}` : ''}`),
        p.lith && el('div', {}, `Type: ${p.lith}`));
      const ref = state.meta?.references?.[p.ref_id];
      if (ref) box.append(el('div', { class: 'geo-cite' }, `Source map: ${shortCitation(ref)}`));
      const link = safeHttpsUrl(p.ngmdb);
      if (link) {
        box.append(el('a', { href: link, target: '_blank', rel: 'noopener noreferrer' }, 'Source map in NGMDB'));
      }
      return box;
    },
  };
}
