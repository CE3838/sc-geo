// Aerial imagery tiles with a per-tile timeout and fallback. Kept free of DOM
// and MapLibre so it can be tested with `node --test`.
//
// The viewer registers `load` as a MapLibre custom protocol (IMAGERY_TILE_URL).
// Each tile is asked of the servers in NAIP_SOURCES order (web/geo.js):
// - a request that has not answered within IMAGERY_TIMEOUT_MS is aborted, and
//   a timeout, network error, bad status or non-image answer sends that tile
//   to the next server (a hung server never errors on its own);
// - after IMAGERY_SWITCH_AFTER failures in a row a server is switched off for
//   the session: later tiles skip it, and tiles still waiting on it move to the
//   next server at once. Nothing is retried against it. The last server is
//   never switched off; when it fails too the tile errors and the viewer shows
//   its "imagery unavailable" notice.
// Each tile is requested at most once from each server.
import { fillTile, hiDpiUrl } from './geo.js';

// How long one tile request may wait for an answer, in milliseconds.
export const IMAGERY_TIMEOUT_MS = 8000;
// Failures in a row (timeouts or errors) after which a server is skipped for the session.
export const IMAGERY_SWITCH_AFTER = 3;

export const IMAGERY_PROTOCOL = 'naip';
export const IMAGERY_TILE_URL = `${IMAGERY_PROTOCOL}://tile/{z}/{x}/{y}`;

// {z, x, y} of an IMAGERY_TILE_URL, or null.
export function parseTileUrl(url) {
  const m = /^naip:\/\/tile\/(\d+)\/(\d+)\/(\d+)$/.exec(url);
  return m ? { z: Number(m[1]), x: Number(m[2]), y: Number(m[3]) } : null;
}

// MapLibre recognizes aborted requests by this message.
const abortError = () => Object.assign(new Error('AbortError'), { name: 'AbortError' });

export function createImageryLoader(sources, {
  fetch = (...a) => globalThis.fetch(...a),
  setTimeout = (...a) => globalThis.setTimeout(...a),
  clearTimeout = (...a) => globalThis.clearTimeout(...a),
  timeoutMs = IMAGERY_TIMEOUT_MS,
  switchAfter = IMAGERY_SWITCH_AFTER,
  pixelRatio = 1,
  onChange = () => {},
} = {}) {
  const state = sources.map(() => ({ failures: 0, off: false, served: false, inflight: new Set() }));
  const firstOn = () => state.findIndex((s) => !s.off);

  function attribution() {
    const served = sources.filter((_, i) => state[i].served).map((s) => s.attribution);
    return served.length ? served.join('; ') : sources[firstOn()].attribution;
  }

  function switchOff(i) {
    const s = state[i];
    s.off = true;
    // Tiles still waiting on this server go to the next one now.
    for (const ctl of s.inflight) ctl.abort('switched');
    const to = firstOn();
    onChange({ switchedFrom: sources[i].id, switchedTo: sources[to].id, attribution: attribution() });
  }

  // One request to one server; resolves to the image bytes or rejects.
  async function attempt(i, tile, outer) {
    const ctl = new AbortController();
    const onOuter = () => ctl.abort('cancelled');
    outer.addEventListener('abort', onOuter);
    const timer = setTimeout(() => ctl.abort('timeout'), timeoutMs);
    state[i].inflight.add(ctl);
    try {
      const res = await fetch(fillTile(hiDpiUrl(sources[i].url, pixelRatio), tile), { signal: ctl.signal });
      const type = res.headers.get('content-type') ?? '';
      if (!res.ok || !type.startsWith('image/')) throw new Error(`HTTP ${res.status} ${type}`);
      const data = await res.arrayBuffer();
      if (ctl.signal.aborted) throw new Error(String(ctl.signal.reason));
      return data;
    } catch (err) {
      err.reason = ctl.signal.aborted ? ctl.signal.reason : 'error';
      throw err;
    } finally {
      clearTimeout(timer);
      outer.removeEventListener('abort', onOuter);
      state[i].inflight.delete(ctl);
    }
  }

  // MapLibre addProtocol load function: (requestParameters, abortController) => {data}.
  async function load(params, abortController) {
    const tile = parseTileUrl(params.url);
    if (!tile) throw new Error(`Not an imagery tile URL: ${params.url}`);
    const outer = abortController.signal;
    for (let i = 0; i < sources.length; i += 1) {
      if (outer.aborted) throw abortError();
      const s = state[i];
      if (s.off) continue;
      try {
        const data = await attempt(i, tile, outer);
        s.failures = 0;
        if (!s.served) {
          s.served = true;
          onChange({ servedBy: sources[i].id, attribution: attribution() });
        }
        return { data };
      } catch (err) {
        if (outer.aborted) throw abortError();
        if (err.reason === 'switched') continue; // another tile's failure switched this server off
        s.failures += 1;
        const later = state.slice(i + 1).some((t) => !t.off);
        if (!s.off && later && s.failures >= switchAfter) switchOff(i);
      }
    }
    throw new Error('Imagery tile unavailable from every server');
  }

  return {
    load,
    attribution,
    state: () => {
      const i = firstOn();
      return { active: sources[i].id, failures: state[i].failures };
    },
  };
}
