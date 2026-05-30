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
  /** Write bytes to an absolute path (Python-computed clip output path). */
  writeFile(absPath: string, bytes: Uint8Array): Promise<string> {
    return ipcRenderer.invoke("vc:writeFile", absPath, bytes);
  },
  /** Reveal a file in the OS file manager. */
  showInFolder(absPath: string): Promise<void> {
    return ipcRenderer.invoke("vc:showInFolder", absPath);
  },
  /** Open a file with the OS default app (play a rendered clip). Returns "" or an error. */
  openPath(absPath: string): Promise<string> {
    return ipcRenderer.invoke("vc:openPath", absPath);
  },
  /** Open a file dialog to pick a local video; returns its absolute path or null. */
  pickVideo(): Promise<string | null> {
    return ipcRenderer.invoke("vc:pickVideo");
  },
  /** Open a folder dialog to pick a project directory; returns its path or null. */
  pickFolder(): Promise<string | null> {
    return ipcRenderer.invoke("vc:pickFolder");
  },
  /** Business RPC to the Python sidecar. Returns the tagged reply from main;
   *  the renderer's ipc client (src/renderer/ipc/) unwraps it. */
  rpc: {
    call(method: string, params?: Record<string, unknown>): Promise<unknown> {
      return ipcRenderer.invoke("vc:rpc", method, params);
    },
    /** Subscribe to server→client notifications. Returns an unsubscribe fn. */
    onNotification(cb: (method: string, params: unknown) => void): () => void {
      const listener = (_e: unknown, method: string, params: unknown): void =>
        cb(method, params);
      ipcRenderer.on("vc:rpc:notification", listener);
      return () => ipcRenderer.removeListener("vc:rpc:notification", listener);
    },
  },
  platform: process.platform,
};

export type VcApi = typeof api;

contextBridge.exposeInMainWorld("vc", api);
