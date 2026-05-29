/**
 * Preload — the contextBridge boundary between the sandboxed renderer and the
 * main process. Minimal for the substrate round: just URL construction for the
 * vc-media:// protocol. File writes for the export spike (Spike C) get added
 * here as a typed ipcRenderer.invoke when that phase lands.
 */

import { contextBridge, ipcRenderer } from "electron";

const api = {
  /** Build a fetchable vc-media:// URL for an absolute local file path. */
  mediaUrl(absPath: string): string {
    return `vc-media://local/${encodeURIComponent(absPath)}`;
  },
  /** Build a vc-media:// URL for a file under the repo's spike-assets/ dir. */
  spikeMediaUrl(name: string): string {
    return `vc-media://spike/${encodeURIComponent(name)}`;
  },
  /** Persist exported mp4 bytes under user_data/exports; returns the path. */
  writeExport(name: string, bytes: Uint8Array): Promise<string> {
    return ipcRenderer.invoke("vc:writeExport", name, bytes);
  },
  platform: process.platform,
};

export type VcApi = typeof api;

contextBridge.exposeInMainWorld("vc", api);
