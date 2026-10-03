// MicroStation DGN v7 (ISFF) -> layers, one per level. Element layout follows
// GDAL's DGN reader (ogr/ogrsf_frmts/dgn, MIT). Supported: line (3), line
// string (4), shape (6), curve (11, as its vertices), complex chain/shape
// (12/14, merged), ellipse (15), arc (16) and text (17). Cell components are
// read as ordinary elements. DGN v8 is a different (OLE) format and is not
// read here.
import { closeRing } from './geometry.js';

const DEG = Math.PI / 180;

// DGN 32-bit integers are stored as two little-endian words, high word first.
function int32(b, o) {
  return (b[o + 2] | (b[o + 3] << 8) | (b[o] << 16) | (b[o + 1] << 24)) | 0;
}

export function vaxToDouble(b, o) {
  const w0 = b[o] | (b[o + 1] << 8);
  const w1 = b[o + 2] | (b[o + 3] << 8);
  const w2 = b[o + 4] | (b[o + 5] << 8);
  const w3 = b[o + 6] | (b[o + 7] << 8);
  const exp = (w0 >> 7) & 0xff;
  if (exp === 0) return 0;
  const sign = w0 & 0x8000 ? -1 : 1;
  const frac = (w0 & 0x7f) * 2 ** 48 + w1 * 2 ** 32 + w2 * 2 ** 16 + w3; // 55 bits
  return sign * (1 + frac / 2 ** 55) * 2 ** (exp - 129);
}

export function isDgn7(b) {
  return b.length >= 4 && (b[0] === 0x08 || b[0] === 0xc8) && b[1] === 0x09 && b[2] === 0xfe && b[3] === 0x02;
}

function strokeArc(origin, primary, secondary, rotationDeg, startDeg, sweepDeg) {
  const n = Math.max(16, Math.ceil(Math.abs(sweepDeg) / 2));
  const cr = Math.cos(rotationDeg * DEG);
  const sr = Math.sin(rotationDeg * DEG);
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const a = (startDeg + (sweepDeg * i) / n) * DEG;
    const ex = primary * Math.cos(a);
    const ey = secondary * Math.sin(a);
    pts.push([origin[0] + ex * cr - ey * sr, origin[1] + ex * sr + ey * cr]);
  }
  return pts;
}

export function parseDgn7(bytes) {
  if (!isDgn7(bytes)) throw new Error('Not a DGN v7 file');
  const b = bytes;
  let dim = 2;
  let scale = 1;
  let origin = [0, 0];
  let masterUnits = '';
  const layers = new Map();
  const skipped = {};

  const tx = (x, y) => [x * scale - origin[0], y * scale - origin[1]];
  const point = (o) => tx(int32(b, o), int32(b, o + 4));
  const vaxPoint = (o) => tx(vaxToDouble(b, o), vaxToDouble(b, o + 8));

  function vertices(o) {
    const count = b[o + 36] | (b[o + 37] << 8);
    const size = dim * 4;
    const pts = [];
    for (let i = 0; i < count; i++) pts.push(point(o + 38 + i * size));
    return pts;
  }

  function arcGeometry(o, type) {
    if (type === 15) {
      const primary = vaxToDouble(b, o + 36) * scale;
      const secondary = vaxToDouble(b, o + 44) * scale;
      const rot = dim === 2 ? int32(b, o + 52) / 360000 : 0;
      const c = vaxPoint(o + (dim === 2 ? 56 : 68));
      return strokeArc(c, primary, secondary, rot, 0, 360);
    }
    const start = int32(b, o + 36) / 360000;
    let sweepRaw;
    if (b[o + 41] & 0x80) {
      const tmp = Uint8Array.from(b.subarray(o + 40, o + 44));
      tmp[1] &= 0x7f;
      sweepRaw = -int32(tmp, 0);
    } else sweepRaw = int32(b, o + 40);
    const sweep = sweepRaw === 0 ? 360 : sweepRaw / 360000;
    const primary = vaxToDouble(b, o + 44) * scale;
    const secondary = vaxToDouble(b, o + 52) * scale;
    const rot = dim === 2 ? int32(b, o + 60) / 360000 : 0;
    const c = vaxPoint(o + (dim === 2 ? 64 : 76));
    return strokeArc(c, primary, secondary, rot, start, sweep);
  }

  // Vertices for a linear or arc element (used directly and for complex parts).
  function linework(o, type) {
    if (type === 3) return dim === 2 ? [point(o + 36), point(o + 44)] : [point(o + 36), point(o + 48)];
    if (type === 4 || type === 6 || type === 11) return vertices(o);
    if (type === 15 || type === 16) return arcGeometry(o, type);
    return null;
  }

  function add(level, geometry, props) {
    const name = `Level ${level}`;
    if (!layers.has(name)) layers.set(name, { name, level, features: [] });
    layers.get(name).features.push({ type: 'Feature', geometry, properties: { level, ...props } });
  }

  let o = 0;
  let complex = null; // { level, type, remaining, pts, props }
  while (o + 4 <= b.length) {
    if (b[o] === 0xff && b[o + 1] === 0xff) break;
    const words = b[o + 2] | (b[o + 3] << 8);
    const size = words * 2 + 4;
    if (o + size > b.length) break;
    const level = b[o] & 0x3f;
    const isComponent = (b[o] & 0x80) !== 0;
    const deleted = (b[o + 1] & 0x80) !== 0;
    const type = b[o + 1] & 0x7f;
    const color = size >= 36 ? b[o + 35] : 0;

    if (type === 9 && !deleted) {
      dim = b[o + 1214] & 0x40 ? 3 : 2;
      const subPerMaster = int32(b, o + 1112);
      const uorPerSub = int32(b, o + 1116);
      masterUnits = String.fromCharCode(b[o + 1120], b[o + 1121]).replace(/\0/g, '').trim();
      if (subPerMaster && uorPerSub) {
        scale = 1 / (uorPerSub * subPerMaster);
        origin = [vaxToDouble(b, o + 1240) * scale, vaxToDouble(b, o + 1248) * scale];
      }
    } else if (complex && isComponent && complex.remaining > 0) {
      if (!deleted) {
        const pts = linework(o, type);
        if (pts) complex.pts.push(...(complex.pts.length ? pts.slice(1) : pts));
      }
      if (--complex.remaining === 0) {
        finishComplex();
      }
    } else if (!deleted) {
      if (complex) finishComplex();
      const props = { type, color };
      if (type === 12 || type === 14) {
        const n = b[o + 38] | (b[o + 39] << 8);
        complex = { level, type, remaining: n, pts: [], props };
        if (n === 0) finishComplex();
      } else if (type === 17) {
        const n = b[o + (dim === 2 ? 58 : 74)];
        const off = o + (dim === 2 ? 60 : 76);
        props.text = new TextDecoder('latin1').decode(b.subarray(off, off + n)).replace(/\0+$/, '');
        add(level, { type: 'Point', coordinates: point(o + (dim === 2 ? 50 : 62)) }, props);
      } else {
        const pts = linework(o, type);
        if (pts && pts.length >= 2) {
          if (type === 11) props.approximate = true;
          if (type === 6) add(level, { type: 'Polygon', coordinates: [closeRing(pts)] }, props);
          else add(level, { type: 'LineString', coordinates: pts }, props);
        } else if (![2, 5, 7, 8, 10, 66].includes(type)) {
          skipped[type] = (skipped[type] ?? 0) + 1;
        }
      }
    }
    o += size;
  }
  if (complex) finishComplex();

  function finishComplex() {
    const c = complex;
    complex = null;
    if (c.pts.length < 2) return;
    if (c.type === 14) add(c.level, { type: 'Polygon', coordinates: [closeRing(c.pts)] }, c.props);
    else add(c.level, { type: 'LineString', coordinates: c.pts }, c.props);
  }

  const sorted = [...layers.values()].sort((x, y) => x.level - y.level).map(({ name, features }) => ({ name, features }));
  const units = /^(ft|'|fe)/i.test(masterUnits) ? 'ft' : /^m/i.test(masterUnits) ? 'm' : null;
  return { layers: sorted, dimension: dim, units, masterUnits, skipped };
}
