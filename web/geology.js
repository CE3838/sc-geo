// Pure helpers for the geology layer (USGS SGMC units). No DOM or MapLibre
// here so they can be tested with `node --test`.

// Youngest to oldest. Colors follow the usual geologic time-scale scheme.
export const AGE_CLASSES = [
  { id: 'Quaternary', color: '#f9f97f' },
  { id: 'Neogene', color: '#ffe619' },
  { id: 'Tertiary', color: '#fdb46c' },
  { id: 'Paleogene', color: '#fd9a52' },
  { id: 'Cenozoic', color: '#f2f91d' },
  { id: 'Cretaceous', color: '#7fc64e' },
  { id: 'Jurassic', color: '#34b2c9' },
  { id: 'Triassic', color: '#812b92' },
  { id: 'Mesozoic', color: '#67c5ca' },
  { id: 'Permian', color: '#f04028' },
  { id: 'Carboniferous', color: '#67a599' },
  { id: 'Devonian', color: '#cb8c37' },
  { id: 'Silurian', color: '#b3e1b6' },
  { id: 'Ordovician', color: '#009270' },
  { id: 'Cambrian', color: '#7fa056' },
  { id: 'Paleozoic', color: '#99c08d' },
  { id: 'Neoproterozoic', color: '#feb342' },
  { id: 'Mesoproterozoic', color: '#fdb462' },
  { id: 'Paleoproterozoic', color: '#f74370' },
  { id: 'Proterozoic', color: '#f73563' },
  { id: 'Archean', color: '#f0047f' },
  { id: 'Precambrian', color: '#f768a1' },
  { id: 'Water', color: '#9ec9e2' },
  { id: 'Unknown', color: '#bdbdbd' },
];

export const LITH_CLASSES = [
  { id: 'Unconsolidated', color: '#f3dfa2' },
  { id: 'Unconsolidated and Sedimentary', color: '#e3b866' },
  { id: 'Sedimentary', color: '#c98b4b' },
  { id: 'Igneous', color: '#e06666' },
  { id: 'Igneous and Metamorphic', color: '#c27ba0' },
  { id: 'Metamorphic', color: '#8e7cc3' },
  { id: 'Tectonite', color: '#3d85c6' },
  { id: 'Water', color: '#9ec9e2' },
  { id: 'Unknown', color: '#bdbdbd' },
];

const MODES = {
  age: { property: 'age_class', classes: AGE_CLASSES, label: 'Age' },
  lith: { property: 'lith_class', classes: LITH_CLASSES, label: 'Rock type' },
};

export function mode(name) {
  const m = MODES[name];
  if (!m) throw new Error(`Unknown geology color mode: ${name}`);
  return m;
}

export function colorExpression(name) {
  const { property, classes } = mode(name);
  const expr = ['match', ['get', property]];
  for (const c of classes) if (c.id !== 'Unknown') expr.push(c.id, c.color);
  expr.push(classes.find((c) => c.id === 'Unknown').color);
  return expr;
}

export function legendEntries(features, name) {
  const { property, classes } = mode(name);
  const known = new Set(classes.map((c) => c.id));
  const counts = new Map();
  for (const f of features) {
    let id = f.properties[property];
    if (!known.has(id)) id = 'Unknown';
    counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return classes.filter((c) => counts.has(c.id)).map((c) => ({ ...c, count: counts.get(c.id) }));
}

const finest = (age) => (age ? age.split(' - ').pop().trim() : null);

// SGMC ages look like 'Phanerozoic - Cenozoic - Quaternary - Pleistocene'.
export function formatAgeRange(ageMin, ageMax) {
  const young = finest(ageMin);
  const old = finest(ageMax);
  if (!young && !old) return 'Unknown';
  if (!young || !old || young === old) return young || old;
  return `${old} to ${young}`;
}

export function safeHttpsUrl(url) {
  if (typeof url !== 'string') return null;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' ? u.href : null;
  } catch {
    return null;
  }
}

export function shortCitation(text, max = 160) {
  return text.length <= max ? text : `${text.slice(0, max).trimEnd()}…`;
}
