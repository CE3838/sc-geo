// In-memory state for imported CAD files and their layers. Nothing here is
// uploaded or saved; it lives only in the current browser tab.

const COLORS = ['#ff3b30', '#ffcc00', '#34c759', '#00c7be', '#32ade6', '#af52de', '#ff2d55', '#ff9500'];

export class CadStore {
  files = [];
  #listeners = new Set();
  #nextId = 1;
  #colorIndex = 0;

  subscribe(fn) {
    this.#listeners.add(fn);
    return () => this.#listeners.delete(fn);
  }

  #emit(event) {
    for (const fn of this.#listeners) fn(event);
  }

  addFile(result) {
    const file = {
      id: `f${this.#nextId++}`,
      name: result.name,
      format: result.format,
      status: result.status,
      reason: result.reason,
      crs: result.crs,
      crsLabel: result.crsLabel,
      bounds: result.bounds ?? null,
      warnings: result.warnings ?? [],
      layers: result.layers.map((l) => ({
        id: `l${this.#nextId++}`,
        name: l.name,
        count: l.count ?? l.geojson.features.length,
        geojson: l.geojson,
        visible: !l.off,
        color: COLORS[this.#colorIndex++ % COLORS.length],
      })),
    };
    this.files.push(file);
    this.#emit({ type: 'add', file });
    return file;
  }

  getFile(fileId) {
    const f = this.files.find((x) => x.id === fileId);
    if (!f) throw new Error(`No file ${fileId}`);
    return f;
  }

  getLayer(layerId) {
    for (const f of this.files) {
      const l = f.layers.find((x) => x.id === layerId);
      if (l) return l;
    }
    throw new Error(`No layer ${layerId}`);
  }

  setLayerVisible(fileId, layerId, visible) {
    const layer = this.getFile(fileId).layers.find((l) => l.id === layerId);
    if (!layer) throw new Error(`No layer ${layerId}`);
    layer.visible = visible;
    this.#emit({ type: 'visibility', fileId, layer });
  }

  removeLayer(fileId, layerId) {
    const file = this.getFile(fileId);
    const layer = file.layers.find((l) => l.id === layerId);
    if (!layer) throw new Error(`No layer ${layerId}`);
    file.layers = file.layers.filter((l) => l !== layer);
    this.#emit({ type: 'remove-layer', fileId, layer });
  }

  removeFile(fileId) {
    const file = this.getFile(fileId);
    this.files = this.files.filter((f) => f !== file);
    this.#emit({ type: 'remove-file', file });
  }
}
