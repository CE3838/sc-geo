// Section tool: draw, edit, name, save, export and import a section line
// (web/section.js holds the logic). A panel in the sidebar; the line is drawn
// on the map. No network requests: profiles come in a later step.
//
// While editing: a click adds a point, dragging a point moves it, a click on a
// point deletes it, and a double-click or Enter finishes (two or more points).
// Escape stops editing; a line with fewer than two points is dropped.
import { el, svg } from './dom.js';
import { onStyleReady } from './geo.js';
import {
  addVertex, canFinish, createStore, deleteVertex, formatLength, fromGeoJSON, hitVertex, lengthFeet, moveVertex,
  newLine, toGeoJSON, vertexRows,
} from './section.js';
import { DATUM, createElevationCache, fetchProfile, profileChart, samplePoints } from './profile.js';
import { EPQS_SOURCE } from './elevation.js';
import { intervalsAlong, stripLayout } from './section-geology.js';

const SRC = 'section-line';
const HIT_PX = 8;
const nowIso = () => new Date().toISOString();
const makeId = () => `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
const fileName = (name) => `${String(name).replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'section'}.geojson`;

function storageOrNull() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

// `root` is the sidebar element (#panels). Returns { isEditing, ... }.
export function setupSection(map, root, { geology = () => null } = {}) {
  const store = createStore(storageOrNull());
  let line = null;      // the line on the map (saved or not)
  let editing = false;
  let drag = null;      // index of the vertex being dragged
  let dragged = false;  // a drag just ended: ignore the click that follows

  // --- panel ---------------------------------------------------------------
  const drawBtn = el('button', { type: 'button', class: 'btn btn-primary', onclick: () => (editing ? finish() : start()) },
    'Draw section line');
  const nameInput = el('input', { type: 'text', class: 'section-name', 'aria-label': 'Section name', maxlength: '80',
    oninput: () => { if (line) line = { ...line, name: nameInput.value }; } });
  const saveBtn = el('button', { type: 'button', class: 'btn', onclick: () => save() }, 'Save');
  const exportBtn = el('button', { type: 'button', class: 'btn', onclick: () => line && download(line) }, 'Export GeoJSON');
  const clearBtn = el('button', { type: 'button', class: 'btn', onclick: () => clear() }, 'Clear');
  const fileInput = el('input', { type: 'file', accept: '.geojson,.json,application/geo+json,application/json',
    class: 'section-file', hidden: true, onchange: () => importFile() });
  const importBtn = el('button', { type: 'button', class: 'btn', onclick: () => fileInput.click() }, 'Import GeoJSON');
  const hint = el('p', { class: 'card-muted section-hint' });
  const lengthOut = el('div', { class: 'section-length' });
  const table = el('table', { class: 'card-props section-vertices' });
  const message = el('p', { class: 'card-muted section-message', role: 'status' });
  const savedList = el('ul', { class: 'section-saved' });
  // Ground profile (USGS 3DEP), fetched only when the user asks.
  const cache = createElevationCache(storageOrNull());
  let profileRun = null;   // { ctrl, key } while fetching
  let profileKey = null;   // coordinates the shown profile belongs to
  const profileBtn = el('button', { type: 'button', class: 'btn', onclick: () => runProfile() }, 'Profile');
  const stopBtn = el('button', { type: 'button', class: 'btn', hidden: true, onclick: () => stopProfile() }, 'Stop');
  const profileStatus = el('p', { class: 'card-muted section-profile-status', role: 'status' });
  const profileChartBox = el('div', { class: 'section-profile' });
  // Surface geology strips from the merged layers already loaded (no requests).
  const geologyBox = el('div', { class: 'section-geology' });
  let geologyKey = null;
  const profileBox = el('div', {}, geologyBox,
    el('div', { class: 'section-actions' }, profileBtn, stopBtn), profileStatus, profileChartBox);
  const current = el('div', { class: 'section-current' },
    el('label', {}, 'Name ', nameInput),
    el('div', { class: 'section-actions' }, saveBtn, exportBtn, clearBtn),
    lengthOut, table, profileBox);
  root.append(el('section', { class: 'side-section', 'aria-labelledby': 'section-h' },
    el('h2', { id: 'section-h' }, 'Section lines'),
    el('div', { class: 'section-actions' }, drawBtn, importBtn, fileInput),
    hint, current, message,
    el('h3', { class: 'section-sub' }, 'Saved'), savedList));

  function say(text) { message.textContent = text; }

  function render() {
    const has = line && line.coords.length > 0;
    drawBtn.textContent = editing ? 'Finish line' : (line ? 'Edit line' : 'Draw section line');
    drawBtn.disabled = editing && !canFinish(line);
    hint.textContent = editing
      ? 'Click the map to add points; drag a point to move it; click a point to delete it. '
        + 'Double-click or press Enter to finish (two or more points); Escape stops.'
      : '';
    current.hidden = !line;
    if (line && document.activeElement !== nameInput) nameInput.value = line.name;
    saveBtn.disabled = !canFinish(line);
    exportBtn.disabled = !canFinish(line);
    lengthOut.textContent = has ? `Length ${formatLength(lengthFeet(line.coords))} (SC State Plane)` : '';
    table.replaceChildren(el('tbody', {}, ...(has ? vertexRows(line.coords) : []).map((r) => el('tr', {},
      el('th', { scope: 'row' }, r.label),
      el('td', {}, r.stateplane, el('div', { class: 'card-muted' }, `${r.latlon} · ${r.along} along`))))));
    renderSaved();
    draw();
    // A profile belongs to the coordinates it was made for: drop it when the line changes.
    const key = line ? JSON.stringify(line.coords) : null;
    if (profileRun && profileRun.key !== key) stopProfile();
    if (profileKey && profileKey !== key) { profileKey = null; profileChartBox.replaceChildren(); profileStatus.textContent = ''; }
    profileBtn.disabled = editing || !canFinish(line) || Boolean(profileRun);
    renderGeology(key);
  }

  const STRIP_W = 262;
  function renderGeology(key) {
    if (editing || !canFinish(line)) { geologyKey = null; geologyBox.replaceChildren(); return; }
    if (key === geologyKey) return;
    const g = geology()?.sectionLayers?.();
    if (!g) {
      geologyKey = null;
      geologyBox.replaceChildren(el('p', { class: 'card-muted' }, 'Geology strips need the merged map, which is not loaded.'));
      return;
    }
    geologyKey = key;
    const length = lengthFeet(line.coords);
    const rows = [['surficial', 'Surficial'], ['bedrock', 'Bedrock']].map(([id, label]) => ({
      label, strip: stripLayout(intervalsAlong(line.coords, g.features[id] ?? [], g), length, { width: STRIP_W }) }));
    const info = el('p', { class: 'card-muted section-strip-info', role: 'status' },
      'Point at or tap a strip for its unit.');
    const describe = (label, r) => (r.mapped
      ? `${label}: ${r.label}${r.conf !== null ? ` · confidence ${r.conf.toFixed(2)}` : ''}${r.citation ? ` · ${r.citation}` : ''}`
      : `${label}: ${r.label}`);
    const ROW_H = 12;
    const ROW_GAP = 16;
    const height = rows.length * (ROW_H + ROW_GAP) + 4;
    const show = (text) => { info.textContent = text; };
    const node = svg('svg', { width: STRIP_W, height, viewBox: `0 0 ${STRIP_W} ${height}`, role: 'img',
      'aria-label': 'Surface geology along the line: surficial and bedrock' },
    ...rows.flatMap((row, i) => {
      const y = i * (ROW_H + ROW_GAP) + ROW_GAP - 4;
      return [
        svg('text', { x: 2, y: y - 3, class: 'pf-label' }, document.createTextNode(row.label)),
        ...row.strip.rects.map((r) => {
          const text = describe(row.label, r);
          const rect = svg('rect', { x: r.x, y, width: Math.max(r.w, 0.5), height: ROW_H, tabindex: '0',
            class: r.mapped ? 'gs-unit' : 'gs-gap', fill: r.mapped ? r.color : 'none' }, svg('title', {}, document.createTextNode(text)));
          for (const ev of ['mouseenter', 'click', 'focus']) rect.addEventListener(ev, () => show(text));
          return rect;
        }),
        ...row.strip.rects.filter((r) => !r.mapped && r.w > 70).map((r) => svg('text',
          { x: r.x + r.w / 2, y: y + ROW_H - 3, 'text-anchor': 'middle', class: 'pf-label gs-gap-label' },
          document.createTextNode(r.label))),
      ];
    }));
    geologyBox.replaceChildren(el('figure', { class: 'section-figure' }, node, info,
      el('p', { class: 'geo-cite' }, 'Merged geologic map along the line, on the profile’s distance axis; '
        + 'blank stretches have no mapped unit. Colors as on the map when drawn. Provided as is, without warranty.')));
  }

  function stopProfile() {
    profileRun?.ctrl.abort();
  }

  function runProfile() {
    if (!canFinish(line) || editing || profileRun) return;
    const key = JSON.stringify(line.coords);
    const ctrl = new AbortController();
    profileRun = { ctrl, key };
    profileKey = key;
    stopBtn.hidden = false;
    profileBtn.disabled = true;
    profileChartBox.replaceChildren();
    const samples = samplePoints(line.coords);
    fetchProfile(samples, { cache, signal: ctrl.signal,
      onProgress: ({ done, total }) => { profileStatus.textContent = `Ground elevations ${done} of ${total}…`; } })
      .then((result) => {
        if (profileKey !== key) return;
        const gaps = result.points.filter((p) => p.feet === null).length;
        profileStatus.textContent = `${result.points.length} points${gaps ? `, ${gaps} without an elevation (gaps)` : ''}`
          + `${result.failed ? `; ${result.failed} failed and will be asked again next time` : ''}.`;
        profileChartBox.replaceChildren(chartNode(result));
      })
      .catch((err) => {
        if (profileKey !== key) return;
        profileStatus.textContent = err.name === 'AbortError' ? 'Profile stopped.' : `Profile failed: ${err.message}`;
      })
      .finally(() => {
        if (profileRun?.ctrl === ctrl) profileRun = null;
        stopBtn.hidden = true;
        profileBtn.disabled = editing || !canFinish(line);
      });
  }

  function chartNode(result) {
    const c = profileChart(result.points, { width: STRIP_W, height: 170 });
    const credit = el('p', { class: 'geo-cite' }, `Ground: ${result.source}, ${DATUM.vertical}, feet (${EPQS_SOURCE}). `
      + 'Provided as is, without warranty.');
    if (!c) return el('div', {}, el('p', { class: 'card-muted' }, 'No elevations returned for this line.'), credit);
    const { plot } = c;
    const text = (x, y, s, anchor = 'middle', extra = {}) => svg('text', { x, y, 'text-anchor': anchor, class: 'pf-label', ...extra },
      document.createTextNode(s));
    return el('figure', { class: 'section-figure' },
      svg('svg', { width: c.width, height: c.height, viewBox: `0 0 ${c.width} ${c.height}`, role: 'img',
        'aria-label': `Ground profile, ${c.yLabel}, against ${c.xLabel}` },
      svg('rect', { x: plot.x, y: plot.y, width: plot.w, height: plot.h, class: 'pf-plot' }),
      ...c.yTicks.map((t) => svg('g', {},
        svg('line', { x1: plot.x, x2: plot.x + plot.w, y1: t.pos, y2: t.pos, class: 'pf-grid' }),
        text(plot.x - 4, t.pos + 3.5, t.label, 'end'))),
      ...c.xTicks.map((t) => svg('g', {},
        svg('line', { x1: t.pos, x2: t.pos, y1: plot.y, y2: plot.y + plot.h, class: 'pf-grid' }),
        text(t.pos, plot.y + plot.h + 12, t.label))),
      ...c.gaps.map((g) => svg('line', { x1: g.pos, x2: g.pos, y1: plot.y, y2: plot.y + plot.h, class: 'pf-gap' })),
      svg('path', { d: c.path, class: 'pf-line' }),
      ...c.segments.filter((s) => s.length === 1).map(([[x, y]]) => svg('circle', { cx: x, cy: y, r: 2, class: 'pf-dot' })),
      text(plot.x + plot.w / 2, c.height - 3, c.xLabel),
      text(10, plot.y + plot.h / 2, 'ft (NAVD88)', 'middle', { transform: `rotate(-90 10 ${plot.y + plot.h / 2})` })),
      el('figcaption', { class: 'card-muted' }, `${c.yLabel} against distance along the line (ft). ${c.exaggerationText}.`
        + `${c.gaps.length ? ' Dashed lines: points without an elevation.' : ''}`),
      credit);
  }

  function renderSaved() {
    const lines = store.list();
    savedList.replaceChildren(...(lines.length ? lines.map((l) => {
      const input = el('input', { type: 'text', value: l.name, 'aria-label': 'Rename section', maxlength: '80',
        onchange: () => {
          store.rename(l.id, input.value);
          if (line?.id === l.id && input.value.trim()) line = { ...line, name: input.value.trim() };
          render();
        } });
      return el('li', {}, input,
        el('span', { class: 'card-muted' }, ` ${formatLength(lengthFeet(l.coords))}`),
        el('div', { class: 'section-actions' },
          el('button', { type: 'button', class: 'btn', onclick: () => load(l.id) }, 'Load'),
          el('button', { type: 'button', class: 'btn', onclick: () => download(l) }, 'Export'),
          el('button', { type: 'button', class: 'btn', onclick: () => remove(l.id) }, 'Delete')));
    }) : [el('li', { class: 'card-muted' }, 'No saved section lines.')]));
    if (!store.persistent && lines.length) say('Saved for this visit only: the browser does not allow local storage here.');
  }

  // --- map drawing -----------------------------------------------------------
  function data() {
    const coords = line?.coords ?? [];
    return {
      type: 'FeatureCollection',
      features: [
        ...(coords.length >= 2 ? [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }] : []),
        ...coords.map((c, i) => ({ type: 'Feature', properties: { n: String(i + 1) }, geometry: { type: 'Point', coordinates: c } })),
      ],
    };
  }

  function draw() {
    map.getSource(SRC)?.setData(data());
    if (map.getLayer('section-vertices')) {
      map.setPaintProperty('section-vertices', 'circle-radius', editing ? 6 : 4);
    }
  }

  onStyleReady(map, () => {
    map.addSource(SRC, { type: 'geojson', data: data() });
    map.addLayer({ id: 'section-line', type: 'line', source: SRC, filter: ['==', '$type', 'LineString'],
      paint: { 'line-color': '#ffeb3b', 'line-width': 3, 'line-dasharray': [2, 1] } });
    map.addLayer({ id: 'section-vertices', type: 'circle', source: SRC, filter: ['==', '$type', 'Point'],
      paint: { 'circle-radius': 4, 'circle-color': '#ffeb3b', 'circle-stroke-color': '#222', 'circle-stroke-width': 1.5 } });
    map.addLayer({ id: 'section-labels', type: 'symbol', source: SRC, filter: ['==', '$type', 'Point'],
      layout: { 'text-field': ['get', 'n'], 'text-size': 11, 'text-offset': [0, -1.2], 'text-font': ['Noto Sans Regular'] },
      paint: { 'text-color': '#222', 'text-halo-color': '#fff', 'text-halo-width': 1.5 } });
  });

  const vertexAt = (point) => hitVertex((line?.coords ?? []).map((c) => map.project(c)), point, HIT_PX);

  // --- editing ------------------------------------------------------------------
  function start() {
    line ??= newLine({ id: makeId(), existing: store.list(), now: nowIso() });
    editing = true;
    map.doubleClickZoom.disable();
    map.getCanvas().style.cursor = 'crosshair';
    say('');
    render();
  }

  function stop() {
    editing = false;
    drag = null;
    map.doubleClickZoom.enable();
    map.dragPan.enable();
    map.getCanvas().style.cursor = '';
    if (line && !canFinish(line)) line = null;
  }

  function finish() {
    if (!canFinish(line)) return;
    stop();
    say('Line finished. Name it and save it, or export it as GeoJSON.');
    render();
  }

  function save() {
    if (!canFinish(line)) return;
    line = { ...line, name: nameInput.value.trim() || line.name, updated: nowIso() };
    store.save(line);
    say(store.persistent ? `Saved “${line.name}” in this browser.`
      : `“${line.name}” is kept for this visit only: the browser does not allow local storage here.`);
    render();
  }

  function load(id) {
    if (editing) stop();
    line = store.get(id);
    say('');
    render();
    fit(line);
  }

  function remove(id) {
    store.remove(id);
    if (line?.id === id) { if (editing) stop(); line = null; }
    render();
  }

  function clear() {
    if (editing) stop();
    line = null;
    say('');
    render();
  }

  function fit(l) {
    if (!l || l.coords.length < 2) return;
    const lngs = l.coords.map((c) => c[0]);
    const lats = l.coords.map((c) => c[1]);
    map.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
      { padding: 60, maxZoom: 15 });
  }

  // Export: a file made in the browser (no upload).
  function download(l) {
    const blob = new Blob([JSON.stringify(toGeoJSON(l), null, 1)], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);
    const a = el('a', { href: url, download: fileName(l.name) });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  // Import: read on this computer only; nothing is sent anywhere.
  function importFile() {
    const file = fileInput.files?.[0];
    fileInput.value = '';
    if (!file) return;
    file.text().then((text) => {
      if (editing) stop();
      line = fromGeoJSON(text, { id: makeId(), now: nowIso() });
      say(`Imported “${line.name}”. Save it to keep it.`);
      render();
      fit(line);
    }).catch((err) => say(`Not imported: ${err.message}.`));
  }

  map.on('click', (e) => {
    if (!editing) return;
    if (dragged) { dragged = false; return; }
    const i = vertexAt(e.point);
    line = i >= 0 ? deleteVertex(line, i) : addVertex(line, [e.lngLat.lng, e.lngLat.lat]);
    render();
  });
  // A double-click's two clicks add a point and then delete it, so the line
  // ends at its last point before the double-click.
  map.on('dblclick', (e) => {
    if (!editing) return;
    e.preventDefault();
    finish();
  });

  function beginDrag(e) {
    if (!editing) return;
    const i = vertexAt(e.point);
    if (i < 0) return;
    e.preventDefault();
    drag = i;
    map.dragPan.disable();
  }
  function moveDrag(e) {
    if (drag === null) return;
    line = moveVertex(line, drag, [e.lngLat.lng, e.lngLat.lat]);
    dragged = true;
    draw();
  }
  function endDrag() {
    if (drag === null) return;
    drag = null;
    map.dragPan.enable();
    render();
    // MapLibre sends no click after a real drag; clear the flag in case it does not.
    setTimeout(() => { dragged = false; }, 0);
  }
  map.on('mousedown', beginDrag);
  map.on('touchstart', (e) => { if (e.points?.length === 1) beginDrag(e); });
  map.on('mousemove', moveDrag);
  map.on('touchmove', moveDrag);
  map.on('mouseup', endDrag);
  map.on('touchend', endDrag);

  document.addEventListener('keydown', (e) => {
    if (!editing || e.target?.closest?.('input, textarea, select')) return;
    if (e.key === 'Enter') { e.preventDefault(); finish(); }
    if (e.key === 'Escape') { stop(); render(); }
  });

  render();
  return {
    // True while the section tool takes map clicks (app.js then shows no callout).
    get isEditing() { return editing; },
    get line() { return line; },
  };
}
