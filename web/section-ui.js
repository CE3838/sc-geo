// Section tool: draw, edit, name, save, export and import a section line
// (web/section.js holds the logic). A panel in the sidebar; the line is drawn
// on the map. No network requests: profiles come in a later step.
//
// While editing: a click adds a point, dragging a point moves it, a click on a
// point deletes it, and a double-click or Enter finishes (two or more points).
// Escape stops editing; a line with fewer than two points is dropped.
import { el } from './dom.js';
import { onStyleReady } from './geo.js';
import {
  addVertex, canFinish, createStore, deleteVertex, formatLength, fromGeoJSON, hitVertex, lengthFeet, moveVertex,
  newLine, toGeoJSON, vertexRows,
} from './section.js';

const SRC = 'section-line';
const HIT_PX = 8;
const nowIso = () => new Date().toISOString();
const makeId = () => `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
const fileName = (name) => `${String(name).replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'section'}.geojson`;

function storageOrNull() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

// `root` is the sidebar element (#panels). Returns { isEditing, ... }.
export function setupSection(map, root) {
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
  const current = el('div', { class: 'section-current' },
    el('label', {}, 'Name ', nameInput),
    el('div', { class: 'section-actions' }, saveBtn, exportBtn, clearBtn),
    lengthOut, table);
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
