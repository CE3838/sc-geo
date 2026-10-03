// Entry point for CAD imports in the browser. Detects the format from the
// file's contents, parses it, converts coordinates to lon/lat, and returns
// layers as GeoJSON. Formats that cannot be read are listed by name only.
import { isDgn7, parseDgn7 } from './dgn7.js';
import { parseDxf } from './dxf.js';
import { parseKml } from './kml.js';
import { parseLandXml } from './landxml.js';
import { CRS_OPTIONS, EPSG_TO_CRS, inBox, makeProjector } from './project.js';
import { readZip } from './zip.js';

export const ACCEPT = '.xml,.landxml,.dwg,.dxf,.dgn,.kml,.kmz';

const LISTED_REASONS = {
  dgn8: 'DGN v8 (MicroStation V8/CONNECT) cannot be read without an OpenRoads or MicroStation license. Ask the consultant for DGN v7, DXF or LandXML.',
  dwg: 'DWG is a closed format with no free reader that runs in the browser. Ask the consultant to save it as DXF (or LandXML for alignments and surfaces).',
  'dxf-binary': 'Binary DXF is not supported. Ask the consultant to save it as ASCII DXF.',
};

const OLE = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1];

export function detectFormat(name, bytes) {
  const ext = (name.match(/\.([^.]+)$/)?.[1] ?? '').toLowerCase();
  const head = new TextDecoder('latin1').decode(bytes.subarray(0, 4096));
  if (OLE.every((v, i) => bytes[i] === v)) return ext === 'dgn' ? 'dgn8' : 'unknown';
  if (isDgn7(bytes)) return 'dgn7';
  if (/^AC10\d\d/.test(head) || ext === 'dwg') return 'dwg';
  if (head.startsWith('PK\x03\x04')) return ext === 'kmz' ? 'kmz' : 'unknown';
  if (head.startsWith('AutoCAD Binary DXF')) return 'dxf-binary';
  if (ext === 'dxf' || /^\s*0\s*\r?\n\s*SECTION/.test(head)) return 'dxf';
  if (/<(\w+:)?kml[\s>/]/.test(head)) return 'kml';
  if (/<LandXML[\s>/]/.test(head)) return 'landxml';
  if (ext === 'dgn') return 'dgn8';
  return 'unknown';
}

async function kmzText(bytes) {
  const entries = (await readZip(bytes)).filter((e) => /\.kml$/i.test(e.name));
  const pick = entries.find((e) => e.name === 'doc.kml') ?? entries.find((e) => !e.name.includes('/')) ?? entries[0];
  if (!pick) throw new Error('KMZ contains no KML file');
  return new TextDecoder().decode(await pick.bytes());
}

function mapCoords(c, f) {
  return typeof c[0] === 'number' ? f(c) : c.map((x) => mapCoords(x, f));
}

function sampleCoords(layers, limit = 200) {
  const out = [];
  for (const l of layers) {
    for (const f of l.features) {
      const flat = [f.geometry.coordinates].flat(Infinity);
      for (let i = 0; i + 1 < flat.length; i += 2) out.push([flat[i], flat[i + 1]]);
      if (out.length >= limit) return out;
    }
  }
  return out;
}

function chooseCrs(layers, { epsg, units }) {
  if (epsg && EPSG_TO_CRS[epsg]) return EPSG_TO_CRS[epsg];
  const sample = sampleCoords(layers);
  if (sample.length && sample.filter((p) => inBox(p)).length > sample.length / 2) return 'lnglat';
  if (units === 'm') return 'sc-m';
  if (units === 'usft') return 'sc-usft';
  return 'sc-ft';
}

function describeSkipped(skipped = {}) {
  const parts = Object.entries(skipped).map(([k, n]) =>
    k === 'paperSpace' ? `${n} paper-space entit${n === 1 ? 'y' : 'ies'}` : `${n} ${/^\d+$/.test(k) ? `type ${k} element` : k}${n === 1 ? '' : 's'}`);
  return parts.length ? `Not drawn: ${parts.join(', ')}.` : null;
}

export async function importCadFile({ name, bytes, crs = 'auto' }) {
  const format = detectFormat(name, bytes);
  if (LISTED_REASONS[format]) {
    return { name, format, status: 'listed', reason: LISTED_REASONS[format], layers: [], warnings: [] };
  }
  let parsed;
  let fixedCrs = null;
  switch (format) {
    case 'kml':
      parsed = parseKml(new TextDecoder().decode(bytes), name);
      fixedCrs = 'lnglat';
      break;
    case 'kmz':
      parsed = parseKml(await kmzText(bytes), name);
      fixedCrs = 'lnglat';
      break;
    case 'dxf':
      parsed = parseDxf(new TextDecoder().decode(bytes));
      break;
    case 'dgn7':
      parsed = parseDgn7(bytes);
      break;
    case 'landxml':
      parsed = parseLandXml(new TextDecoder().decode(bytes));
      break;
    default:
      throw new Error(`${name}: unsupported file type. Supported: ${ACCEPT.replaceAll(',', ', ')}`);
  }

  const used = fixedCrs ?? (crs === 'auto' ? chooseCrs(parsed.layers, parsed) : crs);
  const project = makeProjector(used);
  const bounds = [Infinity, Infinity, -Infinity, -Infinity];
  const layers = parsed.layers.map((l) => {
    const features = [];
    for (const f of l.features) {
      let ok = true;
      const coordinates = mapCoords(f.geometry.coordinates, ([x, y]) => {
        const p = project(x, y);
        if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) ok = false;
        bounds[0] = Math.min(bounds[0], p[0]);
        bounds[1] = Math.min(bounds[1], p[1]);
        bounds[2] = Math.max(bounds[2], p[0]);
        bounds[3] = Math.max(bounds[3], p[1]);
        return p;
      });
      if (!ok) continue;
      features.push({
        type: 'Feature',
        geometry: { type: f.geometry.type, coordinates },
        properties: { layer: l.name, ...f.properties },
      });
    }
    return { name: l.name, off: Boolean(l.off), count: features.length, geojson: { type: 'FeatureCollection', features } };
  });

  const warnings = [];
  const hasData = bounds[0] <= bounds[2];
  if (hasData) {
    const center = [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2];
    if (!inBox(center)) {
      warnings.push(`Coordinates fall outside South Carolina. Check the coordinate system (used: ${CRS_OPTIONS[used].label}).`);
    }
  }
  const skippedNote = describeSkipped(parsed.skipped);
  if (skippedNote) warnings.push(skippedNote);

  return {
    name,
    format,
    status: 'imported',
    crs: used,
    crsLabel: CRS_OPTIONS[used].label,
    layers,
    bounds: hasData ? bounds : null,
    warnings,
  };
}
