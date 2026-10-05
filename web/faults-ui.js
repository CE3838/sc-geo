// Faults and shear zones from SGMC (harvest/sgmc.py writes
// data/geology/sgmc-faults-sc.geojson), drawn above the geology with
// geologic map symbology (faults.js), with a row and key in the Layers panel.
import { FAULT_LAYER_IDS, FAULT_LEGEND, describeFault, faultLayers } from './faults.js';
import { el, svg } from './dom.js';
import { onStyleReady } from './geo.js';

const URL = 'data/geology/sgmc-faults-sc.geojson';

// A "?" marker for queried lines, drawn on a canvas so no font glyphs are needed.
function queryIcon(ratio = 2) {
  const size = 16 * ratio;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.font = `bold ${13 * ratio}px system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 3 * ratio;
  ctx.strokeStyle = '#ffffff';
  ctx.strokeText('?', size / 2, size / 2 + ratio);
  ctx.fillStyle = '#1a1a1a';
  ctx.fillText('?', size / 2, size / 2 + ratio);
  return { image: ctx.getImageData(0, 0, size, size), ratio };
}

function sample(e) {
  const kids = [];
  if (e.band) kids.push(svg('line', { x1: 2, y1: 7, x2: 30, y2: 7, stroke: e.band, 'stroke-opacity': 0.35, 'stroke-width': 7 }));
  kids.push(svg('line', { x1: 2, y1: 7, x2: 30, y2: 7, stroke: e.stroke, 'stroke-width': e.width, 'stroke-dasharray': e.dash }));
  if (e.query) kids.push(svg('text', { x: 16, y: 11, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700,
    fill: '#1a1a1a', stroke: '#fff', 'stroke-width': 2.5, 'paint-order': 'stroke' }, document.createTextNode('?')));
  return svg('svg', { width: 32, height: 14, viewBox: '0 0 32 14', 'aria-hidden': 'true', class: 'fault-sample' }, ...kids);
}

export function setupFaults(map, ui) {
  let meta = null;
  const key = el('ul', { class: 'fault-key', 'aria-label': 'Fault symbols' },
    ...FAULT_LEGEND.map((e) => el('li', {}, sample(e), e.label)));
  const row = ui.addLayer({ id: 'faults', label: 'Faults and Shear Zones', order: 30, detail: key,
    onChange: (on) => {
      for (const id of FAULT_LAYER_IDS) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
      key.hidden = !on;
    } });

  async function load() {
    try {
      const r = await fetch(URL);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      meta = data.meta ?? null;
      const { image, ratio } = queryIcon();
      if (!map.hasImage('fault-query')) map.addImage('fault-query', image, { pixelRatio: ratio });
      map.addSource('faults', { type: 'geojson', data, attribution: 'Faults: USGS SGMC (Horton and Dicken, 2001)' });
      // Above the geology and the neighbor mask, under the state outline.
      for (const layer of faultLayers('faults')) map.addLayer(layer, 'sc-outline-casing');
      row.setNote(` ${data.features.length.toLocaleString()}`);
      if (!row.input.checked) row.input.dispatchEvent(new Event('change'));
    } catch (err) {
      row.disable('not in this build');
      key.hidden = true;
      console.warn('Fault layer not loaded:', err.message);
    }
  }
  onStyleReady(map, load);

  return {
    // Fault line within a few pixels of a screen point, if shown.
    faultAt(point, tolerance = 5) {
      if (!row.input.checked || !map.getLayer('faults-certain')) return null;
      const box = [[point.x - tolerance, point.y - tolerance], [point.x + tolerance, point.y + tolerance]];
      return map.queryRenderedFeatures(box, { layers: FAULT_LAYER_IDS.filter((id) => id !== 'faults-queried') })[0] ?? null;
    },
    describe(feature) {
      const d = describeFault(feature.properties, meta);
      return el('div', { class: 'callout-fault' },
        el('div', { class: 'feature-layer' }, d.title),
        d.detail && el('div', {}, d.detail),
        el('div', { class: 'geo-cite' }, d.source));
    },
  };
}
