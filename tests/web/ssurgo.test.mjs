import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  SDA_URL, horizonQuery, mapUnitQuery, parseTable, requestBody, shrinkSwell, soilAt, soilRecord,
} from '../../web/ssurgo.js';

// Real Soil Data Access responses to these exact queries (captured 2026-10-03).
const fixture = (name) => JSON.parse(readFileSync(new URL(`../fixtures/web/${name}.json`, import.meta.url)));

test('mapUnitQuery asks for the map unit under a WGS84 point', () => {
  const q = mapUnitQuery(-80, 33);
  assert.match(q, /SDA_Get_Mukey_from_intersection_with_WktWgs84\('point\(-80\.000000 33\.000000\)'\)/);
  assert.match(q, /mu\.muname/);
  assert.throws(() => mapUnitQuery(Number.NaN, 33), RangeError);
});

test('horizonQuery takes the dominant component and its top horizon, and rejects odd keys', () => {
  const q = horizonQuery('131940');
  assert.match(q, /WHERE c\.mukey = '131940' ORDER BY c\.comppct_r DESC/);
  assert.match(q, /SELECT MIN\(h2\.hzdept_r\)/);
  for (const col of ['sandtotal_r', 'silttotal_r', 'claytotal_r', 'll_r', 'pi_r', 'lep_r', 'unifiedcl']) {
    assert.ok(q.includes(col), col);
  }
  assert.throws(() => horizonQuery("1'; DROP TABLE x"), RangeError);
});

test('requestBody asks for JSON with column names', () => {
  assert.deepEqual(JSON.parse(requestBody('SELECT 1')), { query: 'SELECT 1', format: 'JSON+COLUMNNAME' });
});

test('parseTable turns rows into objects; an empty result is no rows', () => {
  assert.deepEqual(parseTable(fixture('sda-bethera-mapunit')), [{
    mukey: '131940', musym: 'Be', muname: 'Bethera loam', areasymbol: 'SC015', areaname: 'Berkeley County, South Carolina',
  }]);
  assert.deepEqual(parseTable(fixture('sda-ocean-mapunit')), []);
  assert.deepEqual(parseTable(null), []);
});

test('shrinkSwell uses the NRCS LEP classes', () => {
  assert.equal(shrinkSwell('1.5'), 'Low');
  assert.equal(shrinkSwell(3), 'Moderate');
  assert.equal(shrinkSwell(6.1), 'High');
  assert.equal(shrinkSwell(9), 'Very high');
  assert.equal(shrinkSwell(null), null);
});

test('soilRecord reads the top horizon with provenance and flags the derived class', () => {
  const rec = soilRecord(parseTable(fixture('sda-bethera-mapunit')), parseTable(fixture('sda-bethera-horizon')));
  assert.deepEqual(rec.mapUnit, {
    mukey: '131940', symbol: 'Be', name: 'Bethera loam', area: 'Berkeley County, South Carolina', areaSymbol: 'SC015',
  });
  assert.deepEqual(rec.component, { name: 'Coxville', percent: 95 });
  assert.deepEqual(rec.horizon, { name: 'A', topCm: 0, bottomCm: 20 });
  assert.deepEqual(rec.values, {
    sand: 81, silt: 3, clay: 16, liquidLimit: 33, plasticityIndex: 10, unified: 'SM', lep: 1.5,
  });
  assert.deepEqual(rec.shrinkSwell, { value: 'Low', inferred: true, basis: 'LEP 1.5%' });
  assert.equal(rec.provenance.source_id, 'nrcs-ssurgo');
  assert.equal(rec.provenance.locator, 'mukey 131940, cokey 28379081, chkey 85224826');
});

test('soilRecord keeps missing values as null (urban land)', () => {
  const rec = soilRecord(parseTable(fixture('sda-urban-mapunit')), parseTable(fixture('sda-urban-horizon')));
  assert.equal(rec.component.name, 'Urban land');
  assert.equal(rec.values.sand, null);
  assert.equal(rec.values.unified, null);
  assert.equal(rec.values.clay, 5);
  assert.equal(soilRecord([], []), null);
});

function fakeFetch(responses, calls = []) {
  return async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body), method: init.method });
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return { ok: next.status ? next.status < 400 : true, status: next.status ?? 200, json: async () => next.body ?? next };
  };
}

test('soilAt makes the two POSTs and returns the record', async () => {
  const calls = [];
  const rec = await soilAt(-80, 33, {
    fetch: fakeFetch([fixture('sda-bethera-mapunit'), fixture('sda-bethera-horizon')], calls),
  });
  assert.equal(rec.values.unified, 'SM');
  assert.equal(calls.length, 2);
  assert.ok(calls.every((c) => c.url === SDA_URL && c.method === 'POST'));
  assert.match(calls[1].body.query, /c\.mukey = '131940'/);
});

test('soilAt returns null off the soil map and rejects on errors', async () => {
  assert.equal(await soilAt(-79.5, 32.5, { fetch: fakeFetch([fixture('sda-ocean-mapunit')]) }), null);
  await assert.rejects(soilAt(-80, 33, { fetch: fakeFetch([{ status: 500, body: {} }]) }), /HTTP 500/);
  await assert.rejects(soilAt(-80, 33, { fetch: fakeFetch([new TypeError('Failed to fetch')]) }), /Failed to fetch/);
});
