// Property card model: what the side card shows for the map unit at a
// clicked point. Pure (no DOM) so it can be tested with `node --test`.
// Every row names the reference it comes from (`cite`, 1-based into
// `references`) and derived values are flagged `inferred`.
import { formatAgeRange, safeHttpsUrl } from './geology.js';
import { layerName, parseAlternatives, scaleText, sourceLink } from './merged.js';

export const SGMC_REFERENCE = {
  id: 'usgs-sgmc',
  citation: 'Horton, J.D., San Juan, C.A., and Stoeser, D.B., 2017, The State Geologic Map Compilation (SGMC) '
    + 'geodatabase of the conterminous United States: U.S. Geological Survey Data Series 1052.',
  url: 'https://doi.org/10.5066/F7WH2N65',
  scale: 500000,
  year: 2017,
};

// High >= 0.7, Medium 0.4-0.7, Low < 0.4.
export function confidenceLevel(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const level = value >= 0.7 ? 'High' : value >= 0.4 ? 'Medium' : 'Low';
  return { value, level, text: `${value.toFixed(2)} · ${level}` };
}

// Identity weights from merge/score.py (identity_weight).
const IDENTITY = { certain: 1.0, questionable: 0.8 };
const AGREEMENT = (a) => 0.8 + 0.25 * a; // merge/score.py confidence()
const LONE_MAP = 0.92;
const GEOLEX_BONUS = 0.03;

// The steps of merge/score.py confidence(), rebuilt from what each polygon
// stores: conf_base (scale x identity), agreement, n_sources and
// research_support. The scale weight is conf_base / identity weight.
export function confidenceWhy(p, source) {
  if (typeof p?.conf !== 'number' || typeof p.conf_base !== 'number') return [];
  const ic = (p.identity_confidence ?? '').trim().toLowerCase();
  const idw = IDENTITY[ic] ?? 0.9;
  const why = [
    { label: `Map scale ${scaleText(source?.scale)}`, value: (p.conf_base / idw).toFixed(2) },
    { label: `Mapper’s identification: ${ic || 'not stated'}`, value: `× ${idw.toFixed(2)}` },
  ];
  if (typeof p.agreement === 'number') {
    const others = Math.max(1, (p.n_sources ?? 2) - 1);
    why.push({
      label: `${others} other map${others === 1 ? '' : 's'} cover${others === 1 ? 's' : ''} this ground; `
        + `${Math.round(p.agreement * 100)}% agree`,
      value: `× ${AGREEMENT(p.agreement).toFixed(2)}`,
    });
  } else {
    why.push({ label: 'No other map covers this ground', value: `× ${LONE_MAP.toFixed(2)}` });
  }
  why.push(p.research_support
    ? { label: 'Recognized Geolex unit, age matches', value: `+ ${GEOLEX_BONUS.toFixed(2)}` }
    : { label: 'Not matched to a Geolex unit', value: '+ 0' });
  why.push({ label: 'Confidence', value: p.conf.toFixed(2), total: true });
  return why;
}

const sig = (n) => String(Number(n.toPrecision(3)));

// [young, old] in Ma -> "old–young Ma".
export function formatMa(range) {
  if (!Array.isArray(range) || range.length !== 2 || !range.every(Number.isFinite)) return null;
  const [young, old] = range;
  return young === old ? `${sig(old)} Ma` : `${sig(old)}–${sig(young)} Ma`;
}

// "Weems and Lemon, 1993" from a USGS-style citation.
export function shortRef(ref) {
  const text = ref?.citation || ref?.title || '';
  const m = /^(.*?),\s*(\d{4})\b/.exec(text);
  if (m) {
    const names = m[1].split(/,\s*/).map((s) => s.replace(/^and\s+/, '').trim())
      .filter((s) => s && !s.includes('.'));
    if (names.length) {
      const who = names.length === 1 ? names[0] : names.length === 2 ? `${names[0]} and ${names[1]}` : `${names[0]} and others`;
      return `${who}, ${m[2]}`;
    }
  }
  const head = text.length > 60 ? `${text.slice(0, 60).trimEnd()}…` : text;
  return ref?.year && head ? `${head}, ${ref.year}` : head;
}

// A footprint wider or taller than South Carolina (about 4.8 by 3.2
// degrees) is a regional work; its scale says nothing about detail at a
// point, so it ranks as if its scale were unknown. Same rule as
// merge/references.py rank_key.
const MAX_SPAN = [5, 3.5];
const rankScale = (r) => (r.scale && r.bbox[2] - r.bbox[0] <= MAX_SPAN[0] && r.bbox[3] - r.bbox[1] <= MAX_SPAN[1]
  ? r.scale : Infinity);

// Catalog records (references.json) whose footprint holds the point, most
// detailed first, then newest; `exclude` is the source map already listed.
export function keyReferences(records, lng, lat, exclude = null, n = 4) {
  if (!Array.isArray(records)) return [];
  return records
    .filter((r) => r.id !== exclude && r.bbox && r.bbox[0] <= lng && lng <= r.bbox[2] && r.bbox[1] <= lat && lat <= r.bbox[3])
    .sort((a, b) => rankScale(a) - rankScale(b) || (b.year ?? 0) - (a.year ?? 0))
    .slice(0, n);
}

const ref = (n, r) => ({
  n, id: r.id, citation: r.citation || r.id, url: safeHttpsUrl(r.url) ?? null, scale: r.scale ?? null, year: r.year ?? null,
});

function distinct(values, ...skip) {
  const seen = new Set(skip.filter(Boolean).map((s) => s.toLowerCase()));
  const out = [];
  for (const v of values) {
    if (!v || seen.has(v.toLowerCase())) continue;
    seen.add(v.toLowerCase());
    out.push(v);
  }
  return out;
}

const row = (label, value, extra = {}) => (value === null || value === undefined || value === '' ? null
  : { label, value: String(value), cite: 1, inferred: false, ...extra });

// Card for a merged-geology polygon (merge/build.py output): `props` from
// the polygon, `unit` from merged-units.json, `sources` from
// merged-sources.json source_details, `records` from references.json.
export function mergedCard({ props: p, unit, sources, records, lng, lat }) {
  const u = unit ?? {};
  const src = sources?.[p.source] ?? {};
  const title = u.unit_name || u.name || p.map_unit;
  const group = [u.formation, u.canonical].find((g) => g && g.toLowerCase() !== title.toLowerCase()) ?? null;
  const fromCatalog = (records ?? []).find((r) => r.id === p.source);
  const references = [ref(1, {
    id: p.source,
    citation: src.citation || src.title || fromCatalog?.citation || p.source,
    url: fromCatalog?.url || sourceLink(p.source),
    scale: src.scale ?? fromCatalog?.scale,
    year: src.year ?? fromCatalog?.year,
  })];
  for (const r of keyReferences(records, lng, lat, p.source, 4)) references.push(ref(references.length + 1, r));
  const citeOf = (id) => references.find((r) => r.id === id)?.n ?? null;
  const loc = { locator: p.locator ?? null };
  return {
    title,
    group,
    subtitle: `${layerName(p.layer)} · map label ${u.map_unit ?? p.map_unit}`,
    age: u.age ?? null,
    ma: formatMa(u.age_ma),
    aliases: distinct([u.name, u.full_name, u.formation, u.canonical], title, group),
    confidence: confidenceLevel(p.conf) && { ...confidenceLevel(p.conf), why: confidenceWhy(p, src) },
    confidenceNote: null,
    rows: [
      row('Map unit', u.map_unit ?? p.map_unit, loc),
      row('Age range', formatMa(u.age_ma), { inferred: true, note: 'from the age text, ICS chart' }),
      row('Geomaterial', u.geomaterial, loc),
      row('Lithology', u.lith, loc),
      row('Material class', p.material_class, { inferred: true, note: 'derived class' }),
      row('Mapper’s identification', p.identity_confidence, loc),
      row('Description', u.description, loc),
    ].filter(Boolean),
    alternatives: parseAlternatives(p.alternatives).map((a) => ({
      name: a.name ?? 'unnamed unit',
      citation: shortRef(sources?.[a.source] ?? { citation: a.source }),
      cite: citeOf(a.source),
      detail: [a.age, scaleText(a.scale), `covers ${Math.round((a.overlap ?? 0) * 100)}%`].filter(Boolean).join(' · '),
    })),
    references,
  };
}

// Card for an SGMC polygon (harvest/sgmc.py output), used when the merged
// layers are not available. `meta` is sgmc-sc.meta.json.
export function sgmcCard({ props: p, meta, records, lng, lat }) {
  const label = (p.unit ?? '').split(';')[0] || null;
  const title = p.name || label || 'Map unit';
  const references = [ref(1, SGMC_REFERENCE)];
  const stateMap = meta?.references?.[p.ref_id];
  if (stateMap) {
    references.push(ref(2, { id: `usgs-sgmc:${p.ref_id}`, citation: stateMap, url: p.ngmdb, scale: 500000 }));
  }
  const mapCite = references.length;
  for (const r of keyReferences(records, lng, lat, null, 5 - references.length)) {
    references.push(ref(references.length + 1, r));
  }
  const loc = { locator: p.locator ?? null };
  return {
    title,
    group: null,
    subtitle: `SGMC 1:500,000 · map label ${label ?? '?'}`,
    age: formatAgeRange(p.age_min, p.age_max),
    ma: null,
    aliases: distinct([p.strat_unit], title),
    confidence: null,
    confidenceNote: 'Confidence not scored: only the statewide 1:500,000 compilation is loaded here.',
    rows: [
      row('Map unit', label, loc),
      row('Rock', p.major ? `${p.major}${p.minor ? `; minor ${p.minor}` : ''}` : null, { ...loc, cite: mapCite }),
      row('Lithology', p.lith, loc),
      row('Province', p.province, loc),
      row('Age class', p.age_class, { inferred: true, note: 'derived class' }),
      row('Rock-type class', p.lith_class, { inferred: true, note: 'derived class' }),
      row('Description', p.description, { ...loc, cite: mapCite }),
    ].filter(Boolean),
    alternatives: [],
    references,
  };
}
