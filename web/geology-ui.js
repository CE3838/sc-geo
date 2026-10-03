// Geology layer: USGS SGMC map units under the state outline, with a small
// panel (on/off, color by age or rock type, opacity, legend) and popup info.
import { colorExpression, formatAgeRange, legendEntries, mode, safeHttpsUrl, shortCitation } from './geology.js';

const DATA_URL = 'data/geology/sgmc-sc.geojson';
const META_URL = 'data/geology/sgmc-sc.meta.json';

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, '');
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  node.append(...kids.filter((k) => k != null && k !== false));
  return node;
}

export function setupGeology(map, container) {
  const state = { visible: true, mode: 'age', opacity: 0.55, features: [], meta: null };

  const legend = el('ul', { class: 'geo-legend', 'aria-label': 'Legend' });
  const status = el('p', { class: 'geo-status', role: 'status' }, 'Loading geology…');
  const source = el('p', { class: 'geo-source' });
  const toggle = el('input', {
    type: 'checkbox', id: 'geo-visible', checked: true,
    onchange: () => {
      state.visible = toggle.checked;
      apply();
    },
  });
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
  const body = el('div', { class: 'panel-body', id: 'geo-body' },
    el('div', { class: 'geo-row' }, toggle, el('label', { for: 'geo-visible' }, 'Geologic map units')),
    el('div', { class: 'geo-row' }, el('label', { for: 'geo-mode' }, 'Color by'), modeSelect),
    el('div', { class: 'geo-row' }, el('label', { for: 'geo-opacity' }, 'Opacity'), opacity),
    status, legend, source);
  const collapse = el('button', {
    type: 'button', class: 'panel-collapse', 'aria-expanded': 'true', 'aria-controls': 'geo-body',
    onclick: () => {
      const open = collapse.getAttribute('aria-expanded') !== 'true';
      collapse.setAttribute('aria-expanded', String(open));
      body.hidden = !open;
      collapse.textContent = open ? 'Hide' : 'Show';
    },
  }, 'Hide');
  container.append(el('section', { class: 'panel', 'aria-label': 'Geology' },
    el('div', { class: 'panel-header' }, el('h2', {}, 'Geology'), collapse), body));
  if (window.matchMedia('(max-width: 600px)').matches) collapse.click();

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
      status.textContent = '';
      const when = meta?.retrieved_at ? `, retrieved ${meta.retrieved_at.slice(0, 10)}` : '';
      source.textContent = `Source: USGS State Geologic Map Compilation (1:500,000 state maps)${when}. Colors are derived classes.`;
      apply();
    } catch (err) {
      status.textContent = 'Geology data is not available in this build.';
      toggle.disabled = true;
      console.warn('Geology layer not loaded:', err);
    }
  }

  if (map.isStyleLoaded()) load();
  else map.once('load', load);

  return {
    // Geology unit under a screen point, if the layer is on.
    unitAt(point) {
      if (!state.visible || !map.getLayer('geology-fill')) return null;
      return map.queryRenderedFeatures(point, { layers: ['geology-fill'] })[0] ?? null;
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
