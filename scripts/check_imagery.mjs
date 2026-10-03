// Fetch one NAIP tile over downtown Charleston from each imagery server and
// report whether it returns an image. Exits 1 if any server fails.
import { NAIP_SOURCES, fillBbox, mercatorBbox } from '../web/geo.js';

const CHARLESTON = [-79.94, 32.77, -79.92, 32.79];

let failed = 0;
for (const src of NAIP_SOURCES) {
  const url = fillBbox(src.url, mercatorBbox(CHARLESTON));
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(30000) });
    const type = res.headers.get('content-type') ?? '';
    const bytes = (await res.arrayBuffer()).byteLength;
    const ok = res.ok && type.startsWith('image/') && bytes > 1000;
    console.log(`${ok ? 'OK  ' : 'FAIL'} ${src.id}: HTTP ${res.status}, ${type || 'no content-type'}, ${bytes} bytes`);
    if (!ok) failed += 1;
  } catch (err) {
    console.log(`FAIL ${src.id}: ${err.message}`);
    failed += 1;
  }
}
process.exit(failed ? 1 : 0);
