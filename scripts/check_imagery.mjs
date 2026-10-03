// Fetch one NAIP tile over downtown Charleston from each imagery server and
// report whether it returns an image. Exits 1 if any server fails.
import { NAIP_SOURCES, fillTile, tileForLngLat } from '../web/geo.js';

const CHARLESTON = tileForLngLat(-79.93, 32.78, 16);

let failed = 0;
for (const src of NAIP_SOURCES) {
  const url = fillTile(src.url, CHARLESTON);
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
