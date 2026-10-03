import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FAULT_LEGEND, describeFault, faultLayers } from '../../web/faults.js';

const byId = (layers) => Object.fromEntries(layers.map((l) => [l.id, l]));

test('faultLayers: solid for certain, dashed for approximate/inferred, dotted for concealed', () => {
  const L = byId(faultLayers('faults'));
  assert.ok(L['faults-certain'] && L['faults-approximate'] && L['faults-concealed']);
  assert.equal(L['faults-certain'].paint['line-dasharray'], undefined);
  assert.deepEqual(L['faults-approximate'].paint['line-dasharray'], [4, 2]);
  assert.deepEqual(L['faults-concealed'].paint['line-dasharray'], [1, 2]);
  assert.deepEqual(L['faults-approximate'].filter[2], ['in', ['get', 'certainty'], ['literal', ['approximate', 'inferred']]]);
  assert.ok(Object.values(L).every((l) => l.source === 'faults'));
});

test('faultLayers: queried lines get a "?" along them; shear zones a band', () => {
  const L = byId(faultLayers('faults'));
  const q = L['faults-queried'];
  assert.equal(q.type, 'symbol');
  assert.deepEqual(q.filter, ['==', ['get', 'queried'], true]);
  assert.equal(q.layout['symbol-placement'], 'line');
  assert.equal(q.layout['icon-image'], 'fault-query');
  assert.deepEqual(L['faults-shear-band'].filter, ['==', ['get', 'kind'], 'shear zone']);
});

test('the fault legend covers kinds and certainty', () => {
  assert.deepEqual(FAULT_LEGEND.map((e) => e.label), [
    'Fault', 'Thrust fault', 'Shear zone', 'Approximate or inferred', 'Concealed', 'Queried (?)',
  ]);
});

test('describeFault: text for the callout, with its source', () => {
  const text = describeFault({ kind: 'thrust fault', certainty: 'approximate', queried: true,
    description: 'Thrust fault, direction of motion undefined', ref: 'R1' },
  { references: { R1: 'Horton, J.Wright, and Dicken, Connie L., 2001, Preliminary Geologic Map' } });
  assert.deepEqual(text, {
    title: 'Thrust fault (approximate, queried)',
    detail: 'Thrust fault, direction of motion undefined',
    source: 'USGS SGMC, from Horton, J.Wright, and Dicken, Connie L., 2001, Preliminary Geologic Map',
  });
  assert.equal(describeFault({ kind: 'shear zone', certainty: 'certain' }, null).title, 'Shear zone');
});
