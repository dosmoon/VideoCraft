/**
 * Preload — the contextBridge boundary between the sandboxed renderer and the
 * main process. Exposes vc-media:// URL construction, file writes for rendered
 * clips, OS integration, and the business RPC bridge to the Python sidecar.
 */

import { contextBridge, ipcRenderer } from "electron";

const api = {
  /** Build a fetchable vc-media:// URL for an absolute local file path. */
  mediaUrl(absPath: string): string {
    return `vc-media://local/${encodeURIComponent(absPath)}`;
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
  /** Open an http(s) URL in the default browser (install guide links). */
  openExternal(url: string): Promise<void> {
    return ipcRenderer.invoke("vc:openExternal", url);
  },
  /** Open a file dialog to pick a local video; returns its absolute path or null. */
  pickVideo(): Promise<string | null> {
    return ipcRenderer.invoke("vc:pickVideo");
  },
  /** Open a file dialog to pick a local image; returns its absolute path or null. */
  pickImage(): Promise<string | null> {
    return ipcRenderer.invoke("vc:pickImage");
  },
  /** Open a folder dialog to pick a project directory; returns its path or null. */
  pickFolder(): Promise<string | null> {
    return ipcRenderer.invoke("vc:pickFolder");
  },
  /** Open a file dialog to pick a local .srt; returns its absolute path or null. */
  pickSubtitle(): Promise<string | null> {
    return ipcRenderer.invoke("vc:pickSubtitle");
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
