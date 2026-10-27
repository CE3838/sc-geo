// Pure helpers for the merged geology layers (merge/build.py output).

// The two merged layers split units by material (merge/score.py layer()), not by province.
export const GEOLOGY_LAYERS = [
  { id: 'surficial', label: 'Unconsolidated Deposits', visible: true, order: 10 },
  { id: 'bedrock', label: 'Consolidated Rock', visible: true, order: 20 },
];

export function layerName(id) {
  return (GEOLOGY_LAYERS.find((l) => l.id === id) ?? GEOLOGY_LAYERS[0]).label;
}

export function matchColor(property, classes) {
  const expr = ['match', ['get', property]];
  for (const c of classes) if (c.id !== 'Unknown') expr.push(c.id, c.color);
  expr.push((classes.find((c) => c.id === 'Unknown') ?? { color: '#bdbdbd' }).color);
  return expr;
}

export const CONFIDENCE_STOPS = [[0.3, '#d73027'], [0.6, '#fee08b'], [0.9, '#1a9850']];

export function confidenceColor() {
  return ['interpolate', ['linear'], ['coalesce', ['get', 'conf'], 0], ...CONFIDENCE_STOPS.flat()];
}

export function confidenceText(p) {
  if (typeof p.conf !== 'number') return 'Confidence unknown';
  const parts = [`${Math.round(p.conf * 100)}% confidence`];
  if (p.n_sources > 1 && typeof p.agreement === 'number') {
    parts.push(`${p.n_sources} maps, ${Math.round(p.agreement * 100)}% agree`);
  } else {
    parts.push('only map here');
  }
  if (p.research_support) parts.push('Geolex unit');
  return parts.join(' · ');
}

export function parseAlternatives(text) {
  try {
    const v = JSON.parse(text);
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export function sourceLink(id) {
  const m = /^ngmdb:(\d+)$/.exec(id ?? '');
  if (m) return `https://ngmdb.usgs.gov/Prodesc/proddesc_${m[1]}.htm`;
  if ((id ?? '').startsWith('usgs-sgmc')) return 'https://doi.org/10.5066/F7WH2N65';
  return null;
}

export function scaleText(scale) {
  return scale ? `1:${Number(scale).toLocaleString('en-US')}` : 'scale unknown';
}

export function legendFor(features, property, classes) {
  const known = new Set(classes.map((c) => c.id));
  const counts = new Map();
  for (const f of features) {
    let id = f.properties[property];
    if (!known.has(id)) id = 'Unknown';
    counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return classes.filter((c) => counts.has(c.id)).map((c) => ({ ...c, count: counts.get(c.id) }));
}

const sig = (n) => String(Number(n.toPrecision(3)));

// [young, old] in Ma -> "young–old Ma" (the younger age first).
export function formatMa(range) {
  if (!Array.isArray(range) || range.length !== 2 || !range.every(Number.isFinite)) return null;
  const [young, old] = range;
  return young === old ? `${sig(old)} Ma` : `${sig(young)}–${sig(old)} Ma`;
}

const unitName = (u, key) => u?.unit_name || u?.name || u?.map_unit || key.split('|').pop();
const UNDIVIDED = /\b(undivided|undifferentiated)\b/i;

// The Map units panel: units on screen under their period, then epoch (age
// classes from merge/classes.py, youngest first). Units with the same Geolex
// name (or the same name in any capitals) are one entry listing every map
// label; the younger units come first. Undivided and undifferentiated units
// are one entry per epoch, "Undifferentiated - <epoch>", keeping the printed
// names in `includes`. An older legend without periods groups by age class alone.
export function groupUnits(features, units, ageClasses) {
  const known = new Map(ageClasses.map((c) => [c.id, c]));
  const unknown = known.get('Unknown') ?? { id: 'Unknown', color: '#bdbdbd' };
  const epochs = new Map();
  for (const feat of features) {
    const p = feat.properties;
    const cls = known.get(p.age_class) ?? unknown;
    const u = units[p.unit];
    const name = unitName(u, p.unit ?? '?');
    const undivided = UNDIVIDED.test(name);
    const key = undivided ? '\u0000undivided' : (u?.canonical || name).toLowerCase();
    let e = epochs.get(cls.id);
    if (!e) epochs.set(cls.id, e = { ...cls, period: cls.period ?? cls.id, units: new Map() });
    let entry = e.units.get(key);
    if (!entry) {
      e.units.set(key, entry = { key, name: undivided ? `Undifferentiated - ${cls.id === 'Unknown' ? 'age unknown' : cls.id}` : name,
        labels: new Set(), includes: new Set(), count: 0, age_ma: u?.age_ma ?? null, material_class: p.material_class });
    }
    if (undivided) entry.includes.add(name);
    else if (name.length < entry.name.length) entry.name = name;  // the formation, not one of its facies
    if (u?.map_unit) entry.labels.add(u.map_unit);
    entry.count += 1;
  }
  const order = [...ageClasses.map((c) => c.id), 'Unknown'];
  const periods = new Map();
  for (const e of [...epochs.values()].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))) {
    const list = [...e.units.values()].map((x) => ({ ...x, labels: [...x.labels].sort(), includes: [...x.includes].sort((a, b) => a.localeCompare(b)), ma: formatMa(x.age_ma) }))
      .sort((a, b) => (a.age_ma?.[0] ?? Infinity) - (b.age_ma?.[0] ?? Infinity)
        || (a.age_ma?.[1] ?? Infinity) - (b.age_ma?.[1] ?? Infinity) || a.name.localeCompare(b.name));
    let g = periods.get(e.period);
    if (!g) periods.set(e.period, g = { period: e.period, count: 0, epochs: [] });
    g.epochs.push({ id: e.id, color: e.color, units: list });
    g.count += list.reduce((n, x) => n + x.count, 0);
  }
  return [...periods.values()];
}
