// Fault and shear-zone lines (SGMC_Structure, harvest/sgmc.py) drawn with
// geologic map symbology: solid where located with certainty, dashed where
// approximate or inferred, dotted where concealed, and "?" along queried
// lines. Thrusts are heavier; their teeth are not drawn because SGMC does
// not record which side the upper plate is on for South Carolina.
// MapLibre 4 has no data-driven line-dasharray, so each certainty is its
// own layer. Pure layer specs here; faults-ui.js adds them to the map.

const COLOR = '#1a1a1a';
const WIDTH = ['match', ['get', 'kind'], 'thrust fault', 2.4, 'shear zone', 1.2, 1.7];
const CASING = ['match', ['get', 'kind'], 'thrust fault', 4.4, 'shear zone', 3.2, 3.7];
const LINES = ['!=', ['get', 'kind'], 'contact'];

const DASH = {
  certain: null,
  approximate: [4, 2],
  concealed: [1, 2],
};
const CERTAINTY = {
  certain: ['certain'],
  approximate: ['approximate', 'inferred'],
  concealed: ['concealed'],
};

export function faultLayers(source) {
  const layers = [
    // Shear zones: a translucent band under the center line.
    {
      id: 'faults-shear-band', type: 'line', source, filter: ['==', ['get', 'kind'], 'shear zone'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#7b3294', 'line-opacity': 0.35, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 3, 12, 8] },
    },
    // Light casing so lines read over dark imagery.
    {
      id: 'faults-casing', type: 'line', source, filter: LINES,
      layout: { 'line-join': 'round' },
      paint: { 'line-color': '#ffffff', 'line-opacity': 0.55, 'line-width': CASING },
    },
  ];
  for (const [name, values] of Object.entries(CERTAINTY)) {
    const paint = { 'line-color': ['match', ['get', 'kind'], 'shear zone', '#4a1a5c', COLOR], 'line-width': WIDTH };
    if (DASH[name]) paint['line-dasharray'] = DASH[name];
    layers.push({
      id: `faults-${name}`, type: 'line', source,
      filter: ['all', LINES, ['in', ['get', 'certainty'], ['literal', values]]],
      layout: { 'line-join': 'round' },
      paint,
    });
  }
  layers.push({
    id: 'faults-queried', type: 'symbol', source, filter: ['==', ['get', 'queried'], true],
    layout: {
      'symbol-placement': 'line', 'symbol-spacing': 140, 'icon-image': 'fault-query',
      'icon-allow-overlap': true, 'icon-rotation-alignment': 'viewport',
    },
  });
  return layers;
}

export const FAULT_LAYER_IDS = faultLayers('x').map((l) => l.id);

// For the Layers panel: inline SVG line samples.
export const FAULT_LEGEND = [
  { label: 'Fault', stroke: COLOR, width: 1.7 },
  { label: 'Thrust fault', stroke: COLOR, width: 2.6 },
  { label: 'Shear zone', stroke: '#4a1a5c', width: 1.2, band: '#7b3294' },
  { label: 'Approximate or inferred', stroke: COLOR, width: 1.7, dash: '6 3' },
  { label: 'Concealed', stroke: COLOR, width: 1.7, dash: '1.7 3.4' },
  { label: 'Queried (?)', stroke: COLOR, width: 1.7, query: true },
];

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

export function describeFault(p, meta) {
  const notes = [p.certainty && p.certainty !== 'certain' ? p.certainty : null, p.queried ? 'queried' : null]
    .filter(Boolean);
  const ref = meta?.references?.[p.ref];
  return {
    title: `${cap(p.kind === 'other' ? 'structure line' : p.kind) ?? 'Fault'}${notes.length ? ` (${notes.join(', ')})` : ''}`,
    detail: p.description ?? null,
    source: ref ? `USGS SGMC, from ${ref}` : 'USGS SGMC',
  };
}
