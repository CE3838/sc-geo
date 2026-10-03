// "Water monitoring (USGS)" layer: a symbol per USGS station with a current
// water reading in the view (usgs-water.js), shaped by station type and
// colored by how fresh its latest reading is, plus a chart panel (a bottom
// sheet on phones) that opens when a station is clicked.
import {
  RANGES, STATION_TYPES, STATUS_TEXT, WATER_DATA_CITATION, WATER_DATA_SOURCE, WATER_PARAMS,
  createWaterClient, debounce, qualifierLabels, stationPageUrl, stationsToGeoJSON,
} from './usgs-water.js';
import { chartModel, formatValue, nearestIndex } from './water-chart.js';
import { el, svg } from './dom.js';
import { onStyleReady } from './geo.js';

const SOURCE = 'water-stations';
const LAYER = 'water-stations';

// Shapes in an 18 x 18 box, for the map icons (canvas Path2D) and the legend (SVG).
const SHAPES = {
  stream: 'M2.5 9a6.5 6.5 0 1 0 13 0a6.5 6.5 0 1 0 -13 0Z',
  lake: 'M3 3.5h12v11H3Z',
  well: 'M2 3h14L9 16Z',
  tidal: 'M9 1.5L16.5 9L9 16.5L1.5 9Z',
};
export const STATUS_COLORS = { current: '#1565c0', delayed: '#e09b00', stale: '#8a949c', issue: '#c62828' };

function icon(shape, color, ratio = 2) {
  const size = 18 * ratio;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  const path = new Path2D(SHAPES[shape]);
  ctx.lineJoin = 'round';
  ctx.lineWidth = 3.2;
  ctx.strokeStyle = 'rgba(0,0,0,0.55)';
  ctx.stroke(path);
  ctx.fillStyle = color;
  ctx.fill(path);
  ctx.lineWidth = 1.6;
  ctx.strokeStyle = '#ffffff';
  ctx.stroke(path);
  return { image: ctx.getImageData(0, 0, size, size), ratio };
}

function sample(shape, color = '#5f6b76') {
  return svg('svg', { width: 14, height: 14, viewBox: '0 0 18 18', 'aria-hidden': 'true', class: 'water-sample' },
    svg('path', { d: SHAPES[shape], fill: color, stroke: '#fff', 'stroke-width': 1.6, 'stroke-linejoin': 'round' }));
}

const timeText = (t, opts = {}) => new Date(t).toLocaleString('en-US', {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', ...opts,
});
const dateText = (t) => new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
const unitText = (u) => ({ 'ft^3/s': 'ft³/s' }[u] ?? u ?? '');

function qualifierTags(r) {
  const tags = qualifierLabels(r.qualifiers).map((q) => el('span', { class: 'water-tag water-tag-warn', title: q.code }, q.text));
  if (r.approval === 'Provisional') tags.push(el('span', { class: 'water-tag', title: 'Subject to revision' }, 'Provisional'));
  return tags;
}

export function setupWater(map, ui, { phone = window.matchMedia('(max-width: 700px)') } = {}) {
  const client = createWaterClient();
  let on = true;
  let ready = false;

  // --- Layers panel row and key ----------------------------------------------------
  const key = el('div', { class: 'water-key' },
    el('ul', { 'aria-label': 'Station types' }, ...Object.entries(STATION_TYPES).map(([k, label]) =>
      el('li', {}, sample(k), label))),
    el('ul', { 'aria-label': 'Latest reading' }, ...Object.entries(STATUS_TEXT).map(([k, label]) =>
      el('li', {}, el('span', { class: 'water-dot', style: `background:${STATUS_COLORS[k]}` }), label))),
    el('p', { class: 'geo-cite' }, 'Live from ', el('a', { href: 'https://api.waterdata.usgs.gov/', target: '_blank',
      rel: 'noopener noreferrer' }, 'USGS Water Data'), '. Click a station for its chart.'));
  const row = ui.addLayer({ id: 'water', label: 'Water monitoring (USGS)', order: 60, detail: key,
    onChange: (checked) => {
      on = checked;
      key.hidden = !checked;
      if (map.getLayer(LAYER)) map.setLayoutProperty(LAYER, 'visibility', checked ? 'visible' : 'none');
      if (checked) load(); else { panel.close(); row.setNote(''); }
    } });

  // --- stations on the map -----------------------------------------------------------
  function draw(stations) {
    map.getSource(SOURCE)?.setData(stationsToGeoJSON(stations));
  }

  let loading = 0;
  async function load() {
    if (!on || !ready) return;
    const b = map.getBounds();
    const view = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    const mine = ++loading;
    row.setNote(' loading…');
    try {
      const r = await client.loadArea(view);
      if (mine !== loading) return;
      draw(r.stations);
      const shown = r.stations.filter((s) => b.contains([s.lng, s.lat])).length;
      row.setNote(r.status === 'too-large' ? ' zoom in to load' : ` ${shown.toLocaleString()}`);
    } catch (err) {
      if (mine !== loading) return;
      console.warn('USGS water stations not loaded:', err.message);
      row.setNote(' service unavailable');
    }
  }
  const loadSoon = debounce(load, 400);

  onStyleReady(map, () => {
    for (const shape of Object.keys(SHAPES)) {
      for (const [status, color] of Object.entries(STATUS_COLORS)) {
        const id = `water-${shape}-${status}`;
        if (!map.hasImage(id)) { const { image, ratio } = icon(shape, color); map.addImage(id, image, { pixelRatio: ratio }); }
      }
    }
    map.addSource(SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      attribution: 'Water data: USGS Water Data' });
    map.addLayer({
      id: LAYER, type: 'symbol', source: SOURCE,
      layout: {
        'icon-image': ['get', 'icon'],
        'icon-size': ['interpolate', ['linear'], ['zoom'], 5, 0.6, 9, 0.85, 13, 1.05],
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
        // Fresh readings on top.
        'symbol-sort-key': ['match', ['get', 'status'], 'current', 3, 'delayed', 2, 'issue', 1, 0],
        visibility: on ? 'visible' : 'none',
      },
    });
    ready = true;
    load();
  });
  map.on('moveend', loadSoon);
  map.on('mouseenter', LAYER, () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', LAYER, () => { map.getCanvas().style.cursor = ''; });

  function stationAt(point, tolerance = 7) {
    if (!on || !map.getLayer(LAYER)) return null;
    const box = [[point.x - tolerance, point.y - tolerance], [point.x + tolerance, point.y + tolerance]];
    const hits = map.queryRenderedFeatures(box, { layers: [LAYER] });
    if (!hits.length) return null;
    const d = (f) => { const p = map.project(f.geometry.coordinates); return (p.x - point.x) ** 2 + (p.y - point.y) ** 2; };
    const best = hits.reduce((a, f) => (d(f) < d(a) ? f : a));
    return client.stations().find((s) => s.id === best.properties.id) ?? null;
  }

  // --- chart panel --------------------------------------------------------------------
  const panel = createPanel(map.getContainer(), client);
  // On phones the sheet covers the click callout; close it for other clicks.
  map.on('click', (e) => { if (phone.matches && panel.isOpen && !stationAt(e.point)) panel.close(); });

  return {
    stationAt,
    // Open the chart for a station under a click; true if one was hit.
    openAt(e) {
      const s = stationAt(e.point);
      if (!s) return false;
      panel.open(s);
      return true;
    },
    close: () => panel.close(),
    get isOpen() { return panel.isOpen; },
  };
}

function createPanel(container, client) {
  const W = 360;
  const H = 200;
  let station = null;
  let param = null;
  let range = '7d';
  let request = 0;

  const body = el('div', { class: 'water-body' });
  const close = el('button', { type: 'button', class: 'card-close', 'aria-label': 'Close water chart', onclick: () => api.close() }, '×');
  const root = el('aside', { class: 'water-panel', 'aria-label': 'Water monitoring station', hidden: true },
    el('div', { class: 'card-header' }, el('h2', { class: 'card-kicker' }, 'Water monitoring · USGS'), close), body);
  // Keep clicks and drags in the panel from reaching the map.
  for (const type of ['mousedown', 'touchstart', 'wheel', 'dblclick', 'click']) {
    root.addEventListener(type, (ev) => ev.stopPropagation(), { passive: true });
  }
  container.append(root);
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && api.isOpen) api.close(); });

  const chartBox = el('div', { class: 'water-chart' });
  const readout = el('div', { class: 'water-readout', 'aria-live': 'polite' });
  const note = el('div', { class: 'water-chart-note' });
  const cite = el('p', { class: 'geo-cite water-cite' });

  function render() {
    const s = station;
    const withValues = s.readings.filter((r) => r.value !== null || r.param === param);
    const rangeButtons = el('div', { class: 'water-ranges', role: 'group', 'aria-label': 'Time range' },
      ...Object.entries(RANGES).map(([k, r]) => el('button', {
        type: 'button', class: `btn water-range${k === range ? ' active' : ''}`, 'aria-pressed': String(k === range),
        onclick: () => { range = k; render(); },
      }, r.label)));
    const select = withValues.length > 1 && el('select', { class: 'water-param', 'aria-label': 'Series',
      onchange: (ev) => { param = ev.target.value; render(); } },
    ...withValues.map((r) => el('option', { value: r.param, selected: r.param === param }, `${r.label} (${unitText(r.unit)})`)));

    body.replaceChildren(
      el('h3', { class: 'card-title' }, s.name),
      el('div', { class: 'card-sub' }, [`USGS ${s.number}`, STATION_TYPES[s.type], s.siteType && s.siteType !== STATION_TYPES[s.type] ? s.siteType : null,
        s.state].filter(Boolean).join(' · ')),
      el('table', { class: 'card-props water-latest' }, el('tbody', {}, ...s.readings.map((r) => el('tr', {},
        el('th', { scope: 'row' }, r.label),
        el('td', {}, el('strong', {}, formatValue(r.value, r.unit)), ' ',
          el('span', { class: 'card-muted' }, timeText(r.time, { timeZoneName: 'short' })), ' ', ...qualifierTags(r)))))),
      el('div', { class: 'water-controls' }, select, rangeButtons),
      readout, chartBox, note, cite,
      el('a', { class: 'btn water-link', href: stationPageUrl(s.id), target: '_blank', rel: 'noopener noreferrer' },
        'View on USGS Water Data'));
    loadChart();
  }

  async function loadChart() {
    const s = station;
    const mine = ++request;
    const info = WATER_PARAMS[param];
    readout.textContent = '';
    note.textContent = '';
    cite.textContent = '';
    chartBox.replaceChildren(el('p', { class: 'card-muted water-loading' }, 'Loading chart…'));
    try {
      const series = await client.series(s.id, param, range);
      if (mine !== request) return;
      drawChart(series, info);
      cite.append(`Source: ${WATER_DATA_CITATION} (${series.daily ? 'daily means' : 'instantaneous values'}, `,
        `${s.id}, parameter ${param}), retrieved ${timeText(series.retrieved, { year: 'numeric', timeZoneName: 'short' })}. `,
        el('span', { title: series.url }, WATER_DATA_SOURCE), '.');
    } catch (err) {
      if (mine !== request) return;
      console.warn('USGS series not loaded:', err.message);
      chartBox.replaceChildren(el('p', { class: 'card-muted water-unavailable' },
        'USGS Water Data is unavailable right now. Try again later.'));
    }
  }

  function drawChart(series, info) {
    const days = RANGES[range].days;
    const t1 = series.retrieved;
    const t0 = t1 - days * 86400e3;
    const points = series.points.filter((p) => p.t >= t0 - 86400e3);
    const m = chartModel(points, { width: W, height: H, t0, t1, invert: Boolean(info.invert) });
    if (m.empty) {
      chartBox.replaceChildren(el('p', { class: 'card-muted water-empty' },
        series.daily ? 'No daily values for this series in the last year (tidal series often have none).' : `No readings in the last ${RANGES[range].label}.`));
      return;
    }
    const unit = unitText(series.unit);
    const { top, bottom: mb, left, right: mr } = m.margin;
    const bottom = H - mb;
    const right = W - mr;
    const kids = [
      svg('rect', { x: left, y: top, width: right - left, height: bottom - top, class: 'wc-plot' }),
      ...m.yTicks.flatMap((k) => [
        svg('line', { x1: left, x2: right, y1: k.y, y2: k.y, class: 'wc-grid' }),
        svg('text', { x: left - 5, y: k.y + 3.5, class: 'wc-label', 'text-anchor': 'end' }, document.createTextNode(k.label)),
      ]),
      ...m.xTicks.flatMap((k) => [
        svg('line', { x1: k.x, x2: k.x, y1: bottom, y2: bottom + 4, class: 'wc-axis' }),
        svg('text', { x: k.x, y: bottom + 15, class: 'wc-label', 'text-anchor': 'middle' }, document.createTextNode(k.label)),
      ]),
      svg('line', { x1: left, x2: right, y1: bottom, y2: bottom, class: 'wc-axis' }),
      svg('line', { x1: left, x2: left, y1: top, y2: bottom, class: 'wc-axis' }),
      svg('text', { x: 4, y: 10, class: 'wc-unit' },
        document.createTextNode(info.invert ? `${unit} below land surface (deeper ↓)` : unit)),
      svg('path', { d: m.path, class: 'wc-line' }),
    ];
    for (const [p, label] of [[m.max, 'max'], [m.min, 'min']]) {
      const below = label === 'min' ? !m.inverted : m.inverted;
      const anchor = p.x > W - 80 ? 'end' : p.x < left + 40 ? 'start' : 'middle';
      kids.push(svg('circle', { cx: p.x, cy: p.y, r: 3, class: `wc-${label}` }),
        svg('text', { x: p.x, y: Math.min(bottom - 3, Math.max(top + 9, p.y + (below ? 12 : -6))), class: 'wc-mark', 'text-anchor': anchor },
          document.createTextNode(`${label} ${formatValue(p.v, null)}`)));
    }
    const cross = svg('line', { y1: top, y2: bottom, class: 'wc-cross', visibility: 'hidden' });
    const dot = svg('circle', { r: 3.5, class: 'wc-dot', visibility: 'hidden' });
    kids.push(cross, dot);
    const chart = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'wc', role: 'img',
      'aria-label': `${info.label}, ${RANGES[range].label}: min ${formatValue(m.min.v, series.unit)}, max ${formatValue(m.max.v, series.unit)}` },
    ...kids);

    const valid = points.filter((p) => p.v !== null);
    const latestText = () => {
      const p = valid.at(-1);
      return `Latest ${formatValue(p.v, series.unit)} · ${series.daily ? dateText(p.t) : timeText(p.t)}`;
    };
    readout.textContent = latestText();
    const move = (ev) => {
      const r = chart.getBoundingClientRect();
      const x = ((ev.clientX - r.left) / r.width) * W;
      const t = t0 + ((x - left) / (right - left)) * (t1 - t0);
      const i = nearestIndex(valid, t);
      if (i < 0) return;
      const p = valid[i];
      const px = m.x(p.t);
      const py = m.y(p.v);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('visibility', 'visible');
      dot.setAttribute('cx', px); dot.setAttribute('cy', py); dot.setAttribute('visibility', 'visible');
      const q = qualifierLabels(p.qualifiers).map((f) => f.text);
      readout.textContent = `${formatValue(p.v, series.unit)} · ${series.daily ? `${dateText(p.t)} (daily mean)` : timeText(p.t)}`
        + `${q.length ? ` · ${q.join(', ')}` : ''}${p.approval === 'Provisional' ? ' · provisional' : ''}`;
    };
    const leave = () => {
      cross.setAttribute('visibility', 'hidden');
      dot.setAttribute('visibility', 'hidden');
      readout.textContent = latestText();
    };
    chart.addEventListener('pointermove', move);
    chart.addEventListener('pointerdown', move);
    chart.addEventListener('pointerleave', leave);
    chartBox.replaceChildren(chart);

    const notes = [];
    notes.push(`${info.label}, ${unit}. ${series.daily ? 'Daily means' : 'Instantaneous values'}, last ${RANGES[range].label}.`);
    if (info.invert) notes.push('Axis inverted: deeper water levels plot lower.');
    const flags = new Set(valid.flatMap((p) => qualifierLabels(p.qualifiers).map((q) => q.text)));
    if (flags.size) notes.push(`Includes: ${[...flags].join(', ')}.`);
    if (valid.some((p) => p.approval === 'Provisional')) notes.push('Provisional data are subject to revision.');
    note.textContent = notes.join(' ');
  }

  const api = {
    get isOpen() { return !root.hidden; },
    open(s) {
      station = s;
      param = s.primary?.param ?? s.readings[0]?.param;
      if (!RANGES[range]) range = '7d';
      root.hidden = false;
      render();
      body.scrollTop = 0;
    },
    close() {
      root.hidden = true;
      request += 1;
      station = null;
    },
  };
  return api;
}
