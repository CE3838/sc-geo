import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  PARCEL_MINZOOM, countiesForBounds, ringsMeetBox, countyBoxes, describeParcel, normalizeParcel, parcelLayers, parcelOutFields,
  parcelPlan, parcelQueryUrl, recordLink,
} from '../../web/parcels.js';

const counties = JSON.parse(readFileSync(new URL('../../web/data/sc-counties.geojson', import.meta.url)));
const webRegistry = JSON.parse(readFileSync(new URL('../../web/data/parcel_registry.json', import.meta.url)));

const ENTRY = {
  county: 'Testing', fips: '45999', status: 'ok', cors: true,
  url: 'https://services.example.test/arcgis/rest/services/Parcels/FeatureServer/0',
  id_field: 'PIN', acreage_field: 'ACRES', address_fields: ['STNUM', 'STNAME'], max_record_count: 2000,
  record_url: 'https://records.example.test/parcel?pin={id}', oid_field: 'OBJECTID',
};

test('the county file has all 46 counties with names and FIPS codes', () => {
  assert.equal(counties.features.length, 46);
  const boxes = countyBoxes(counties);
  assert.equal(boxes.length, 46);
  const chas = boxes.find((b) => b.name === 'Charleston');
  assert.equal(chas.fips, '45019');
  const [w, s, e, n] = chas.bbox;
  assert.ok(w < -79.95 && e > -79.95 && s < 32.78 && n > 32.78);
});

test('countiesForBounds: downtown Charleston is Charleston only; a border view gets both counties', () => {
  const boxes = countyBoxes(counties);
  const names = (b) => countiesForBounds(boxes, b).map((c) => c.name);
  assert.deepEqual(names([-79.94, 32.77, -79.93, 32.78]), ['Charleston']);
  // The Ashley River near Summerville: Charleston, Dorchester and Berkeley meet nearby.
  const border = names([-80.06, 32.92, -80.03, 32.94]);
  assert.ok(border.includes('Charleston') && border.includes('Dorchester'), border.join());
  assert.deepEqual(names([-90, 40, -89, 41]), []);
  // Walterboro is Colleton only, though Dorchester's box reaches past it.
  assert.deepEqual(names([-80.67, 32.90, -80.66, 32.91]), ['Colleton']);
  // Isle of Palms and Kiawah, near the generalized coastline, still count as Charleston.
  assert.deepEqual(names([-79.76, 32.79, -79.75, 32.80]), ['Charleston']);
  assert.deepEqual(names([-80.08, 32.60, -80.07, 32.61]), ['Charleston']);
});

test('ringsMeetBox: inside, around, crossing and apart', () => {
  const square = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]];
  assert.equal(ringsMeetBox(square, [4, 4, 5, 5]), true); // box inside the polygon
  assert.equal(ringsMeetBox(square, [-1, -1, 11, 11]), true); // polygon inside the box
  assert.equal(ringsMeetBox(square, [9, -5, 12, 15]), true); // edges cross, no corner inside
  assert.equal(ringsMeetBox(square, [11, 11, 12, 12]), false);
});

test('the viewer copy of the registry has one entry per county', () => {
  assert.equal(webRegistry.counties.length, 46);
  const names = new Set(webRegistry.counties.map((c) => c.county));
  for (const f of counties.features) assert.ok(names.has(f.properties.name), f.properties.name);
  const chas = webRegistry.counties.find((c) => c.county === 'Charleston');
  assert.equal(chas.id_field, 'PID');
  assert.match(chas.url, /^https:\/\/.+\/MapServer\/\d+$/);
  for (const c of webRegistry.counties) {
    assert.ok(['ok', 'no public service', 'blocked', 'needs check'].includes(c.status), `${c.county}: ${c.status}`);
    // Owner names are never requested.
    for (const f of parcelOutFields(c)) assert.doesNotMatch(f, /owner|name1|name2/i, `${c.county}: ${f}`);
  }
});

test('parcelPlan: which counties can be queried from the browser, and why not', () => {
  assert.deepEqual(parcelPlan(ENTRY), { usable: true, reason: null });
  assert.equal(parcelPlan({ ...ENTRY, status: 'needs check', cors: null }).usable, true);
  assert.deepEqual(parcelPlan({ county: 'X', status: 'no public service', url: null }),
    { usable: false, reason: 'no public parcel service' });
  assert.deepEqual(parcelPlan({ ...ENTRY, cors: false }), { usable: false, reason: 'service blocks browser access (CORS)' });
  assert.deepEqual(parcelPlan({ ...ENTRY, status: 'blocked' }), { usable: false, reason: 'service is blocked' });
  assert.deepEqual(parcelPlan({ ...ENTRY, id_field: null }), { usable: false, reason: 'no parcel ID field known' });
  assert.equal(parcelPlan(null).usable, false);
});

test('parcelOutFields and parcelQueryUrl: ID, acreage, address only; envelope; GeoJSON; paging', () => {
  assert.deepEqual(parcelOutFields(ENTRY), ['PIN', 'ACRES', 'STNUM', 'STNAME']);
  assert.deepEqual(parcelOutFields({ ...ENTRY, record_link_field: 'PROPERTYCARD' }), ['PIN', 'ACRES', 'STNUM', 'STNAME', 'PROPERTYCARD']);
  const url = new URL(parcelQueryUrl(ENTRY, [-79.94, 32.77, -79.93, 32.78], 1000));
  const p = Object.fromEntries(url.searchParams);
  assert.equal(url.pathname, '/arcgis/rest/services/Parcels/FeatureServer/0/query');
  assert.equal(p.geometry, '-79.94,32.77,-79.93,32.78');
  assert.equal(p.geometryType, 'esriGeometryEnvelope');
  assert.equal(p.outFields, 'PIN,ACRES,STNUM,STNAME');
  assert.equal(p.f, 'geojson');
  assert.equal(p.resultOffset, '1000');
  assert.equal(p.resultRecordCount, '1000');
  assert.equal(p.orderByFields, 'OBJECTID');
  // Services without GeoJSON output are asked for esri JSON; small record limits are respected.
  const old = new URL(parcelQueryUrl({ ...ENTRY, geojson: false, max_record_count: 500, oid_field: null }, [0, 0, 1, 1], 0));
  assert.equal(old.searchParams.get('f'), 'json');
  assert.equal(old.searchParams.get('resultRecordCount'), '500');
  assert.equal(old.searchParams.get('orderByFields'), null);
});

test('normalizeParcel: parcel ID, acreage and address, case-insensitive; no other attributes', () => {
  const p = normalizeParcel(ENTRY, { pin: ' 4580402007 ', Acres: '0.12345', STNUM: 12, STNAME: 'KING ST', OWNER: 'X' });
  assert.deepEqual(p, {
    pid: '4580402007', acres: 0.12, address: '12 KING ST', county: 'Testing',
    url: 'https://records.example.test/parcel?pin=4580402007', deep_link: true,
  });
  const bare = normalizeParcel({ ...ENTRY, acreage_field: null, address_fields: [] }, { PIN: 77 });
  assert.equal(bare.pid, '77');
  assert.equal(bare.acres, null);
  assert.equal(bare.address, null);
  assert.equal(normalizeParcel(ENTRY, { PIN: '' }).pid, null);
});

test('recordLink: deep link template, link field from the service, or the search page', () => {
  assert.deepEqual(recordLink(ENTRY, 'A B/1', {}), { url: 'https://records.example.test/parcel?pin=A%20B%2F1', deep: true });
  const search = { ...ENTRY, record_url: 'https://records.example.test/search' };
  assert.deepEqual(recordLink(search, '1', {}), { url: 'https://records.example.test/search', deep: false });
  const field = { ...ENTRY, record_link_field: 'PROPERTYCARD' };
  assert.deepEqual(recordLink(field, '1', { PROPERTYCARD: 'https://county.example.test/card/1' }),
    { url: 'https://county.example.test/card/1', deep: true });
  assert.deepEqual(recordLink(field, '1', { PROPERTYCARD: 'http://web.county.example.test/card?p=1 ' }),
    { url: 'http://web.county.example.test/card?p=1', deep: true });
  // Only web links from the service are trusted.
  assert.equal(recordLink(field, '1', { PROPERTYCARD: 'javascript:alert(1)' }).url, 'https://records.example.test/parcel?pin=1');
  assert.deepEqual(recordLink({ ...ENTRY, record_url: null }, '1', {}), { url: null, deep: false });
});

test('describeParcel: callout text with the county as the cited source', () => {
  const d = describeParcel({ pid: '4580402007', acres: 0.12, address: '12 KING ST', county: 'Charleston', url: 'https://x.test/', deep_link: false });
  assert.deepEqual(d, {
    title: 'Parcel 4580402007',
    rows: [['Parcel ID (TMS/PIN)', '4580402007'], ['Acreage', '0.12 ac'], ['Address', '12 KING ST']],
    source: 'Charleston County parcel service (live)',
    link: { url: 'https://x.test/', text: 'County record search' },
  });
  const deep = describeParcel({ pid: '1', acres: null, address: null, county: 'York', url: 'https://y.test/1', deep_link: true });
  assert.equal(deep.link.text, 'County record');
  assert.deepEqual(deep.rows, [['Parcel ID (TMS/PIN)', '1']]);
});

test('parcelLayers: shown from z15, lines with a dark casing, IDs from z17', () => {
  assert.equal(PARCEL_MINZOOM, 15);
  const L = Object.fromEntries(parcelLayers('parcels').map((l) => [l.id, l]));
  assert.equal(L['parcels-fill'].minzoom, 15);
  assert.equal(L['parcels-line'].minzoom, 15);
  assert.equal(L['parcels-casing'].minzoom, 15);
  assert.equal(L['parcels-label'].minzoom, 17);
  assert.deepEqual(L['parcels-label'].layout['text-field'], ['get', 'pid']);
  assert.equal(L['parcels-fill'].paint['fill-opacity'] > 0, true, 'a faint fill so parcels can be clicked');
});
