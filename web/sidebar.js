// Left panel: "Layers" (a checkbox per layer, in a fixed order whatever
// loads first, plus display controls) and "Map units" (the legend). On
// phones it is a drawer opened from the header.
import { el } from './dom.js';

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
    // One layer row. `order` keeps rows in a fixed order as they load.
    addLayer({ id, label, checked = true, order = 50, count = null, onChange, detail = null }) {
      const input = el('input', { type: 'checkbox', id: `layer-${id}`, checked,
        onchange: () => onChange?.(input.checked) });
      const note = el('span', { class: 'layer-note' });
      const row = el('li', { class: 'layer-row', 'data-order': String(order) },
        el('div', { class: 'layer-main' }, input,
          el('label', { for: `layer-${id}` }, label,
            count != null && el('span', { class: 'geo-count' }, ` ${count.toLocaleString()}`)),
          note),
        detail);
      const after = [...list.children].find((r) => Number(r.dataset.order) > order);
      list.insertBefore(row, after ?? null);
      return {
        input, row,
        setNote(text) { note.textContent = text; },
        disable(text) { input.checked = false; input.disabled = true; note.textContent = text; },
      };
    },
    addControls(...nodes) { controls.append(...nodes); },
  };
}
