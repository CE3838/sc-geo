// Pure helpers for the merged geology layers (merge/build.py output).

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
