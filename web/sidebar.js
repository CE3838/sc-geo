// Left panel: "Layers" (a checkbox per layer, in a fixed order whatever
// loads first, plus display controls, with collapsible folders such as
// "Hydro") and "Map units" (the legend). On phones it is a drawer opened
// from the header.
import { el } from './dom.js';

// Insert `row` into `list` before the first row with a larger order.
function place(list, row, order) {
  const after = [...list.children].find((r) => Number(r.dataset?.order) > order);
  list.insertBefore(row, after ?? null);
}

// One layer row. `order` keeps rows in a fixed order as they load.
function layerRow(list, { id, label, checked = true, order = 50, count = null, onChange, detail = null }) {
  const input = el('input', { type: 'checkbox', id: `layer-${id}`, checked,
    onchange: () => onChange?.(input.checked) });
  const note = el('span', { class: 'layer-note' });
  const row = el('li', { class: 'layer-row', 'data-order': String(order) },
    el('div', { class: 'layer-main' }, input,
      el('label', { for: `layer-${id}` }, label,
        count != null && el('span', { class: 'geo-count' }, ` ${count.toLocaleString()}`)),
      note),
    detail);
  place(list, row, order);
  return {
    input, row,
    setNote(text) { note.textContent = text; },
    disable(text) { input.checked = false; input.disabled = true; note.textContent = text; },
  };
}

const storedOpen = (id, fallback) => {
  try {
    const v = globalThis.localStorage?.getItem(`sc-geo:folder:${id}`);
    return v == null ? fallback : v === 'open';
  } catch {
    return fallback;
  }
};
const storeOpen = (id, open) => {
  try { globalThis.localStorage?.setItem(`sc-geo:folder:${id}`, open ? 'open' : 'closed'); } catch { /* private mode */ }
};

export function createSidebar(root) {
  const list = el('ul', { class: 'layer-list' });
  const controls = el('div', { class: 'layer-controls' });
  const units = el('div', { class: 'units-body' });
  root.append(
    el('section', { class: 'side-section', 'aria-labelledby': 'layers-h' },
      el('h2', { id: 'layers-h' }, 'Layers'), list, controls),
    el('section', { class: 'side-section', 'aria-labelledby': 'units-h' },
      el('h2', { id: 'units-h' }, 'Map units'), units),
  );

  return {
    units,
    addLayer: (opts) => layerRow(list, opts),
    // A collapsible folder of layer rows; it has the same addLayer as the panel.
    addFolder({ id, label, order = 50, open = true }) {
      const inner = el('ul', { class: 'layer-list folder-list', id: `folder-${id}-list` });
      let isOpen = storedOpen(id, open);
      const button = el('button', { type: 'button', class: 'folder-toggle', 'aria-controls': `folder-${id}-list`,
        'aria-expanded': String(isOpen), onclick: () => setOpen(!isOpen) },
      el('span', { class: 'folder-caret', 'aria-hidden': 'true' }), label);
      const row = el('li', { class: 'layer-folder', 'data-order': String(order), 'data-folder': id }, button, inner);
      function setOpen(v) {
        isOpen = v;
        inner.hidden = !v;
        button.setAttribute('aria-expanded', String(v));
        storeOpen(id, v);
      }
      inner.hidden = !isOpen;
      place(list, row, order);
      return { row, list: inner, setOpen, get open() { return isOpen; }, addLayer: (opts) => layerRow(inner, opts) };
    },
    addControls(...nodes) { controls.append(...nodes); },
  };
}
