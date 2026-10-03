// Property card: a closable side panel (a bottom sheet on phones) for the
// map unit at a clicked point (card.js model), plus soil properties from
// NRCS SSURGO, fetched when the card opens.
import { el } from './dom.js';
import { formatCoords } from './geo.js';
import { formatStatePlane } from './stateplane.js';
import { soilAt } from './ssurgo.js';
import { scaleText } from './merged.js';

const pct = (v) => (v === null ? null : `${v}%`);

function citeMark(n) {
  return n ? el('sup', { class: 'cite' }, el('a', { href: `#card-ref-${n}` }, `[${n}]`)) : null;
}

function propertyRows(rows) {
  return el('table', { class: 'card-props' }, el('tbody', {}, ...rows.map((r) => el('tr', {},
    el('th', { scope: 'row' }, r.label),
    el('td', {}, el('span', { class: r.label === 'Description' ? 'card-desc' : null }, r.value), ' ',
      r.inferred ? el('span', { class: 'tag-inferred', title: `Inferred${r.note ? `: ${r.note}` : ''}` },
        `inferred${r.note ? ` · ${r.note}` : ''}`) : citeMark(r.cite))))));
}

function soilSection(soil) {
  if (!soil) return el('p', { class: 'card-muted' }, 'No soil map unit here (water or unmapped).');
  const v = soil.values;
  const rows = [
    ['Sand / silt / clay', [v.sand, v.silt, v.clay].some((x) => x !== null)
      ? [pct(v.sand) ?? '–', pct(v.silt) ?? '–', pct(v.clay) ?? '–'].join(' / ') : null],
    ['Liquid limit', v.liquidLimit],
    ['Plasticity index', v.plasticityIndex],
    ['Unified class', v.unified],
    ['Shrink-swell', soil.shrinkSwell ? `${soil.shrinkSwell.value} (LEP ${v.lep}%)` : null],
  ].filter(([, value]) => value !== null && value !== undefined);
  const where = [
    `Map unit ${soil.mapUnit.symbol} · ${soil.mapUnit.name}`,
    soil.component && `${soil.component.name} ${soil.component.percent ?? '?'}% of map unit`,
    soil.horizon && `top horizon ${soil.horizon.name ?? ''} ${soil.horizon.topCm}–${soil.horizon.bottomCm} cm`,
  ].filter(Boolean).join(' · ');
  return el('div', {},
    el('p', { class: 'card-muted' }, where),
    rows.length ? el('table', { class: 'card-props' }, el('tbody', {}, ...rows.map(([label, value]) => el('tr', {},
      el('th', { scope: 'row' }, label),
      el('td', {}, String(value), ' ', label === 'Shrink-swell'
        ? el('span', { class: 'tag-inferred', title: 'Class from LEP, NRCS classes' }, 'inferred · from LEP')
        : el('span', { class: 'tag-source' }, 'NRCS SSURGO')))))) : el('p', { class: 'card-muted' },
      'No horizon data for this component.'),
    el('p', { class: 'geo-cite' }, 'Estimates (SSURGO representative values), not site measurements. Source: ',
      el('a', { href: 'https://sdmdataaccess.sc.egov.usda.gov/', target: '_blank', rel: 'noopener noreferrer' },
        'NRCS SSURGO via Soil Data Access'), `, ${soil.provenance.locator}.`));
}

export function setupCard(container, { onToggle } = {}) {
  let soilQuery = null;
  let drawn = 0;
  const body = el('div', { class: 'card-body' });
  const close = el('button', { type: 'button', class: 'card-close', 'aria-label': 'Close card', onclick: () => api.close() }, '×');
  container.append(el('div', { class: 'card-header' }, el('h2', { class: 'card-kicker' }, 'Property card'), close), body);

  const api = {
    get isOpen() { return !container.hidden; },
    // `model` from card.js, or null when there is no map unit at the point.
    open(model, { lng, lat }) {
      const parts = [];
      if (model) {
        parts.push(el('h3', { class: 'card-title' }, model.title,
          model.group && el('span', { class: 'card-group' }, ` (${model.group})`)));
        parts.push(el('div', { class: 'card-sub' }, model.subtitle));
        if (model.age) {
          parts.push(el('div', { class: 'card-age' }, model.age,
            model.ma && el('span', { class: 'card-ma' }, ` · ${model.ma}`)));
        }
        if (model.aliases.length) parts.push(el('div', { class: 'card-aka' }, `Also: ${model.aliases.join('; ')}`));
        if (model.confidence) {
          const c = model.confidence;
          parts.push(el('div', { class: 'card-conf' },
            el('span', { class: `badge badge-${c.level.toLowerCase()}` }, c.text),
            c.why.length > 0 && el('details', { class: 'card-why' },
              el('summary', {}, `Why ${c.value.toFixed(2)}`),
              el('table', {}, el('tbody', {}, ...c.why.map((w) => el('tr', { class: w.total ? 'why-total' : null },
                el('td', {}, w.label), el('td', {}, w.value))))),
              el('p', { class: 'geo-cite' }, 'Scored by merge/score.py from map scale, the mapper’s certainty, '
                + 'agreement with other maps and Geolex. High ≥ 0.70, Medium 0.40–0.70, Low < 0.40.'))));
        } else if (model.confidenceNote) {
          parts.push(el('p', { class: 'card-muted' }, model.confidenceNote));
        }
        parts.push(el('h4', {}, 'Properties'), propertyRows(model.rows));
      } else {
        parts.push(el('h3', { class: 'card-title' }, 'No geologic map unit here'),
          el('p', { class: 'card-muted' }, 'Turn on a geology layer, or pick a point on land in South Carolina.'));
      }
      const soil = el('div', { class: 'card-soil' }, el('p', { class: 'card-muted' }, 'Loading soil data…'));
      parts.push(el('h4', {}, 'Soil at this point ', el('span', { class: 'card-h-note' }, 'NRCS SSURGO')), soil);
      if (model?.alternatives.length) {
        parts.push(el('h4', {}, 'Other maps here'), el('ul', { class: 'card-alts' }, ...model.alternatives.map((a) =>
          el('li', {}, el('strong', {}, a.name), ` — ${a.citation}`, citeMark(a.cite), el('div', { class: 'card-muted' }, a.detail)))));
      }
      if (model?.references.length) {
        parts.push(el('h4', {}, 'Key references'), el('ol', { class: 'card-refs' }, ...model.references.map((r) => {
          // Scale and year, unless the citation already says them.
          const extra = [r.scale && scaleText(r.scale), r.year && String(r.year)].filter((t) => t && !r.citation.includes(t));
          return el('li', { id: `card-ref-${r.n}`, value: String(r.n) }, r.citation,
            extra.length > 0 && el('span', { class: 'card-muted' }, ` (${extra.join(', ')})`),
            r.url && ' ', r.url && el('a', { href: r.url, target: '_blank', rel: 'noopener noreferrer', class: 'card-link' }, 'Record'));
        })));
      }
      parts.push(el('p', { class: 'card-point' }, `${formatCoords(lng, lat)} · ${formatStatePlane(lng, lat)} (SC State Plane, NAD83)`));
      body.replaceChildren(...parts);
      body.scrollTop = 0;
      const wasOpen = api.isOpen;
      container.hidden = false;
      if (!wasOpen) onToggle?.(true);

      // One request per point, even when the card is redrawn for it.
      const key = `${lng},${lat}`;
      if (soilQuery?.key !== key || soilQuery.ctrl.signal.aborted) {
        soilQuery?.ctrl.abort();
        const ctrl = new AbortController();
        soilQuery = { key, ctrl, promise: soilAt(lng, lat, { signal: ctrl.signal }) };
      }
      const { ctrl, promise } = soilQuery;
      const shown = ++drawn;
      promise
        .then((s) => { if (shown === drawn && !ctrl.signal.aborted) soil.replaceChildren(soilSection(s)); })
        .catch((err) => {
          if (shown !== drawn || ctrl.signal.aborted) return;
          console.warn('Soil data not loaded:', err.message);
          soil.replaceChildren(el('p', { class: 'card-muted' }, 'Soil data unavailable right now (NRCS Soil Data Access).'));
        });
    },
    close() {
      soilQuery?.ctrl.abort();
      if (container.hidden) return;
      container.hidden = true;
      onToggle?.(false);
    },
  };
  return api;
}
