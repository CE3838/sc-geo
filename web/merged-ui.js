// Merged geology: one surficial and one bedrock layer built from every
// available map (merge/build.py). Layers panel: a row per layer, color by
// age / material / confidence, opacity. Map units panel: legend and how the
// layers were merged. Click: a short description, and the property card
// model (card.js).
import {
  confidenceColor, confidenceText, CONFIDENCE_STOPS, GEOLOGY_LAYERS, layerName, legendFor, matchColor, parseAlternatives, scaleText, sourceLink,
} from './merged.js';
import { safeHttpsUrl, shortCitation } from './geology.js';
import { mergedCard } from './card.js';
import { el } from './dom.js';
import { onStyleReady } from './geo.js';

const BASE = 'data/geology/';
const LAYERS = GEOLOGY_LAYERS;

const getJson = (name) => fetch(BASE + name).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${name}: HTTP ${r.status}`))));

// Resolves to the controller, or rejects if the merged files are missing.
// `ui` is the sidebar (sidebar.js).
export async function setupMergedGeology(map, ui) {
  const [legend, units, summary, ...data] = await Promise.all([
    getJson('merged-legend.json'), getJson('merged-units.json'), getJson('merged-sources.json'),
    ...LAYERS.map((l) => getJson(`merged-${l.id}.geojson`)),
  ]);
  const sources = summary.source_details ?? {};
  const state = { mode: 'age', opacity: 0.6, visible: Object.fromEntries(LAYERS.map((l) => [l.id, l.visible])) };
  const features = Object.fromEntries(LAYERS.map((l, i) => [l.id, data[i].features]));

  const colorFor = (mode) => (mode === 'confidence' ? confidenceColor()
    : mode === 'material' ? matchColor('material_class', legend.material) : matchColor('age_class', legend.age));

  await new Promise((r) => onStyleReady(map, r));
  // Bedrock first so surficial units draw on top of it.
  for (const l of [...LAYERS].reverse()) {
    map.addSource(`merged-${l.id}`, { type: 'geojson', data: data[LAYERS.indexOf(l)],
      attribution: 'Geology: merged from USGS, SCGS and other maps (see Map units)' });
    map.addLayer({ id: `merged-${l.id}-fill`, type: 'fill', source: `merged-${l.id}`,
      paint: { 'fill-color': colorFor(state.mode), 'fill-opacity': state.opacity } }, 'mask');
    map.addLayer({ id: `merged-${l.id}-line`, type: 'line', source: `merged-${l.id}`, minzoom: 9,
      paint: { 'line-color': '#222', 'line-opacity': 0.4, 'line-width': 0.5 } }, 'mask');
  }

  for (const l of LAYERS) {
    ui.addLayer({ id: `geo-${l.id}`, label: l.label, order: l.order, checked: l.visible, count: features[l.id].length,
      onChange: (on) => { state.visible[l.id] = on; apply(); } });
  }
  const modeSelect = el('select', { id: 'geo-mode', onchange: () => { state.mode = modeSelect.value; apply(); } },
    el('option', { value: 'age' }, 'Age'), el('option', { value: 'material' }, 'Material'),
    el('option', { value: 'confidence' }, 'Confidence'));
  const opacity = el('input', { type: 'range', id: 'geo-opacity', min: '0', max: '100', value: String(state.opacity * 100),
    oninput: () => { state.opacity = Number(opacity.value) / 100; apply(); } });
  ui.addControls(
    el('div', { class: 'geo-row' }, el('label', { for: 'geo-mode' }, 'Color geology by'), modeSelect),
    el('div', { class: 'geo-row' }, el('label', { for: 'geo-opacity' }, 'Opacity'), opacity));

  const legendList = el('ul', { class: 'geo-legend', 'aria-label': 'Legend' });
  const used = (summary.sources ?? []).filter((s) => s.status === 'used');
  ui.units.append(legendList, el('p', { class: 'geo-source' },
    `Merged from ${used.length} maps (${used.filter((s) => s.scale && s.scale <= 24000).length} at 1:24,000). `
    + 'Where maps overlap the most detailed and recent map is shown; confidence reflects map scale, '
    + 'how many maps agree, and whether the unit is a recognized Geolex unit. Colors are derived classes.'));

  function apply() {
    for (const l of LAYERS) {
      const vis = state.visible[l.id] ? 'visible' : 'none';
      map.setLayoutProperty(`merged-${l.id}-fill`, 'visibility', vis);
      map.setLayoutProperty(`merged-${l.id}-line`, 'visibility', vis);
      map.setPaintProperty(`merged-${l.id}-fill`, 'fill-color', colorFor(state.mode));
      map.setPaintProperty(`merged-${l.id}-fill`, 'fill-opacity', state.opacity);
    }
    const shown = LAYERS.filter((l) => state.visible[l.id]).flatMap((l) => features[l.id]);
    let entries;
    if (state.mode === 'confidence') {
      entries = CONFIDENCE_STOPS.map(([v, color]) => ({ id: `${v.toFixed(1)} confidence`, color }));
    } else {
      const [prop, classes] = state.mode === 'material' ? ['material_class', legend.material] : ['age_class', legend.age];
      entries = legendFor(shown, prop, classes);
    }
    legendList.replaceChildren(...entries.map((e) => el('li', {},
      el('span', { class: 'geo-swatch', style: `background:${e.color}` }), e.id,
      e.count != null && el('span', { class: 'geo-count' }, ` ${e.count}`))));
  }
  apply();

  return {
    kind: 'merged',
    unitAt(point) {
      const layers = LAYERS.filter((l) => state.visible[l.id]).map((l) => `merged-${l.id}-fill`);
      return layers.length ? map.queryRenderedFeatures(point, { layers })[0] ?? null : null;
    },
    // Property card model for a clicked feature (card.js).
    card(feature, lng, lat, records = []) {
      const p = feature.properties;
      return mergedCard({ props: p, unit: units[p.unit], sources, records, lng, lat });
    },
    describe(feature) {
      const p = feature.properties;
      const u = units[p.unit] ?? {};
      const src = sources[p.source] ?? {};
      const link = safeHttpsUrl(sourceLink(p.source));
      const alts = parseAlternatives(p.alternatives);
      return el('div', { class: 'feature-info' },
        el('div', { class: 'feature-layer' }, u.unit_name || u.name || p.map_unit),
        el('div', {}, `${layerName(p.layer)} · map label ${u.map_unit ?? p.map_unit}`),
        u.age && el('div', {}, `Age: ${u.age}`),
        el('div', {}, `Material: ${p.material_class}`),
        u.description && el('div', { class: 'geo-cite' }, shortCitation(u.description, 220)),
        el('div', { class: 'geo-conf' }, confidenceText(p)),
        el('div', { class: 'geo-cite' }, `Source: ${shortCitation(src.citation || src.title || p.source, 180)} (${scaleText(src.scale)})`),
        link && el('a', { href: link, target: '_blank', rel: 'noopener noreferrer' }, 'Source record'),
        alts.length > 0 && el('div', { class: 'geo-alts' }, 'Other maps here:',
          el('ul', {}, ...alts.slice(0, 3).map((a) => el('li', {},
            `${a.name ?? 'unnamed unit'}${a.age ? ` (${a.age})` : ''} — ${shortCitation(sources[a.source]?.title || a.source, 60)}, `
            + `${scaleText(a.scale)}, covers ${Math.round((a.overlap ?? 0) * 100)}%`)))));
    },
  };
}
