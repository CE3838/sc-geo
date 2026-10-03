// CAD layer panel: import files, then toggle or delete each layer. Imported
// data stays in this browser tab; nothing is uploaded.
import { ACCEPT, importCadFile } from './cad/import.js';
import { CRS_OPTIONS } from './cad/project.js';
import { CadStore } from './cad/store.js';

const FORMAT_LABELS = {
  kml: 'KML', kmz: 'KMZ', dxf: 'DXF', dgn7: 'DGN v7', landxml: 'LandXML',
  dgn8: 'DGN v8', dwg: 'DWG', 'dxf-binary': 'Binary DXF',
};

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

const mapLayerIds = (layer) => [`cad-${layer.id}-fill`, `cad-${layer.id}-line`, `cad-${layer.id}-point`];

export function setupLayerPanel(map) {
  const store = new CadStore();
  const ready = new Promise((resolve) => (map.isStyleLoaded() ? resolve() : map.once('load', resolve)));

  // --- map sync ---------------------------------------------------------
  function addToMap(layer) {
    const source = `cad-${layer.id}`;
    const visibility = layer.visible ? 'visible' : 'none';
    const [fill, line, point] = mapLayerIds(layer);
    map.addSource(source, { type: 'geojson', data: layer.geojson });
    map.addLayer({
      id: fill, type: 'fill', source, layout: { visibility },
      filter: ['match', ['geometry-type'], ['Polygon', 'MultiPolygon'], true, false],
      paint: { 'fill-color': layer.color, 'fill-opacity': 0.15 },
    });
    map.addLayer({
      id: line, type: 'line', source, layout: { visibility },
      filter: ['!=', ['geometry-type'], 'Point'],
      paint: { 'line-color': layer.color, 'line-width': 2 },
    });
    map.addLayer({
      id: point, type: 'circle', source, layout: { visibility },
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-color': layer.color, 'circle-radius': 4,
        'circle-stroke-color': '#000', 'circle-stroke-width': 1,
      },
    });
  }

  function removeFromMap(layer) {
    for (const id of mapLayerIds(layer)) if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource(`cad-${layer.id}`)) map.removeSource(`cad-${layer.id}`);
  }

  store.subscribe(async (e) => {
    await ready;
    if (e.type === 'add') e.file.layers.forEach(addToMap);
    else if (e.type === 'visibility') {
      for (const id of mapLayerIds(e.layer)) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', e.layer.visible ? 'visible' : 'none');
      }
    } else if (e.type === 'remove-layer') removeFromMap(e.layer);
    else if (e.type === 'remove-file') e.file.layers.forEach(removeFromMap);
    render();
  });

  // --- panel ------------------------------------------------------------
  const list = el('ul', { class: 'cad-files' });
  const status = el('p', { class: 'cad-status', role: 'status' });
  const crsSelect = el('select', { id: 'cad-crs' },
    el('option', { value: 'auto' }, 'Auto-detect'),
    ...Object.entries(CRS_OPTIONS).map(([k, v]) => el('option', { value: k }, v.label)));
  const input = el('input', {
    type: 'file', multiple: true, accept: ACCEPT, class: 'visually-hidden', id: 'cad-file-input',
    onchange: () => {
      importFiles([...input.files]);
      input.value = '';
    },
  });
  const body = el('div', { class: 'cad-body', id: 'cad-body' },
    el('div', { class: 'cad-controls' },
      el('label', { for: 'cad-file-input', class: 'cad-import' }, 'Import CAD files…'),
      input,
      el('label', { class: 'cad-crs-label' }, 'Coordinates for DXF, DGN and LandXML', crsSelect)),
    el('p', { class: 'cad-hint' }, 'LandXML, DXF, DGN v7, KML and KMZ are drawn. DWG and DGN v8 are listed by name only. Files stay in this browser.'),
    status,
    list);
  const toggle = el('button', {
    type: 'button', class: 'cad-collapse', 'aria-expanded': 'true', 'aria-controls': 'cad-body',
    onclick: () => {
      const open = toggle.getAttribute('aria-expanded') !== 'true';
      toggle.setAttribute('aria-expanded', String(open));
      body.hidden = !open;
      toggle.textContent = open ? 'Hide' : 'Show';
    },
  }, 'Hide');
  const panel = el('aside', { class: 'layer-panel', 'aria-label': 'CAD layers' },
    el('div', { class: 'cad-header' }, el('h2', {}, 'CAD layers'), toggle),
    body);
  document.body.append(panel);
  // Start collapsed on phones so the map stays visible.
  if (window.matchMedia('(max-width: 600px)').matches) toggle.click();

  function zoomTo(bounds) {
    if (!bounds) return;
    map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: 40, maxZoom: 18 });
  }

  function render() {
    list.replaceChildren(...store.files.map((file) => {
      const header = el('div', { class: 'cad-file-header' },
        el('span', { class: 'cad-file-name', title: file.name }, file.name),
        el('span', { class: 'cad-badge' }, FORMAT_LABELS[file.format] ?? file.format),
        file.bounds && el('button', { type: 'button', class: 'cad-btn', onclick: () => zoomTo(file.bounds) }, 'Zoom'),
        el('button', {
          type: 'button', class: 'cad-btn', 'aria-label': `Remove ${file.name}`,
          onclick: () => store.removeFile(file.id),
        }, 'Remove'));
      const notes = [
        file.status === 'listed' && el('p', { class: 'cad-note' }, `Listed by name only. ${file.reason}`),
        file.crsLabel && file.format !== 'kml' && file.format !== 'kmz' && el('p', { class: 'cad-meta' }, file.crsLabel),
        ...file.warnings.map((w) => el('p', { class: 'cad-warning' }, w)),
      ];
      const layers = file.status === 'imported' && el('ul', { class: 'cad-layers' },
        ...(file.layers.length ? file.layers.map((layer) => {
          const box = el('input', {
            type: 'checkbox', id: `chk-${layer.id}`, checked: layer.visible, 'aria-label': `Show layer ${layer.name}`,
            onchange: () => store.setLayerVisible(file.id, layer.id, box.checked),
          });
          return el('li', {},
            box,
            el('label', { for: `chk-${layer.id}` },
              el('span', { class: 'cad-swatch', style: `background:${layer.color}` }),
              el('span', { class: 'cad-layer-name', title: layer.name }, layer.name),
              el('span', { class: 'cad-count' }, String(layer.count))),
            el('button', {
              type: 'button', class: 'cad-delete', title: 'Delete layer', 'aria-label': `Delete layer ${layer.name}`,
              onclick: () => store.removeLayer(file.id, layer.id),
            }, '×'));
        }) : [el('li', { class: 'cad-note' }, 'All layers deleted.')]));
      return el('li', { class: 'cad-file' }, header, ...notes, layers);
    }));
  }

  async function importFiles(files) {
    for (const f of files) {
      status.textContent = `Reading ${f.name}…`;
      try {
        const bytes = new Uint8Array(await f.arrayBuffer());
        const result = await importCadFile({ name: f.name, bytes, crs: crsSelect.value });
        const file = store.addFile(result);
        if (files.length === 1) zoomTo(file.bounds);
        status.textContent = '';
      } catch (err) {
        status.textContent = `${f.name}: ${err.message}`;
      }
    }
  }

  // Drag and drop onto the map.
  const container = map.getContainer();
  container.addEventListener('dragover', (e) => e.preventDefault());
  container.addEventListener('drop', (e) => {
    e.preventDefault();
    importFiles([...e.dataTransfer.files]);
  });

  render();

  return {
    store,
    // CAD features under a screen point, topmost first.
    featuresAt(point) {
      const layers = store.files.flatMap((f) => f.layers.filter((l) => l.visible).flatMap(mapLayerIds))
        .filter((id) => map.getLayer(id));
      if (!layers.length) return [];
      const box = [[point.x - 4, point.y - 4], [point.x + 4, point.y + 4]];
      return map.queryRenderedFeatures(box, { layers });
    },
  };
}
