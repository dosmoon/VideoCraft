/**
 * Preload — the contextBridge boundary between the sandboxed renderer and the
 * main process. Exposes vc-media:// URL construction, file writes for rendered
 * clips, OS integration, and the business RPC bridge to the Python sidecar.
 */

import { contextBridge, ipcRenderer } from "electron";
import type { BuildInfo } from "./buildInfo";
import type { AppInfo } from "./appInfo";
import type { MenuLabels } from "./menu";

const api = {
  /** Build a fetchable vc-media:// URL for an absolute local file path. */
  mediaUrl(absPath: string): string {
    return `vc-media://local/${encodeURIComponent(absPath)}`;
  },
  /** Write bytes to an absolute path (Python-computed clip output path). */
  writeFile(absPath: string, bytes: Uint8Array): Promise<string> {
    return ipcRenderer.invoke("vc:writeFile", absPath, bytes);
  },
  /** Open a positional write stream to disk for large mp4 exports; returns a
   *  handle id. Pair with writeStreamChunk + closeWriteStream/abortWriteStream. */
  openWriteStream(absPath: string): Promise<number> {
    return ipcRenderer.invoke("vc:writeStream:open", absPath);
  },
  /** Write one chunk at a byte position into an open write stream. */
  writeStreamChunk(id: number, position: number, bytes: Uint8Array): Promise<void> {
    return ipcRenderer.invoke("vc:writeStream:write", id, position, bytes);
  },
  /** Finalize a write stream (rename .part into place); returns the final path. */
  closeWriteStream(id: number): Promise<string> {
    return ipcRenderer.invoke("vc:writeStream:close", id);
  },
  /** Discard a write stream's partial file (on cancel/error). */
  abortWriteStream(id: number): Promise<void> {
    return ipcRenderer.invoke("vc:writeStream:abort", id);
  },
  /** Native ffmpeg (NVENC) encode: pipe raw frames in, ffmpeg encodes to disk. */
  ffmpegEncode: {
    probe(): Promise<{ ffmpeg: boolean; nvenc: boolean }> {
      return ipcRenderer.invoke("vc:ffmpegEncode:probe");
    },
    start(params: {
      outputPath: string;
      width: number;
      height: number;
      fps: number;
      bitrate: number;
      pixfmt: "bgra" | "rgba";
      sourcePath?: string;
      audioStartSec?: number;
    }): Promise<number> {
      return ipcRenderer.invoke("vc:ffmpegEncode:start", params);
    },
    writeFrame(id: number, bytes: Uint8Array): Promise<void> {
      return ipcRenderer.invoke("vc:ffmpegEncode:writeFrame", id, bytes);
    },
    finish(id: number): Promise<string> {
      return ipcRenderer.invoke("vc:ffmpegEncode:finish", id);
    },
    abort(id: number): Promise<void> {
      return ipcRenderer.invoke("vc:ffmpegEncode:abort", id);
    },
  },
  /** Stream-copy a rendered mp4 into one file per chapter (publish-side split). */
  splitChapters(params: {
    inputPath: string;
    outDir: string;
    segments: { name: string; startSec: number; durationSec: number }[];
  }): Promise<{ written: string[]; failed: { name: string; error: string }[] }> {
    return ipcRenderer.invoke("vc:splitChapters", params);
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
  /** Generic project-scoped file I/O (ADR-0008: TS plugins own their files).
   *  Paths are absolute; main-process assertInProject rejects anything outside
   *  the open project or <userData>/presets. */
  fs: {
    readJson(absPath: string): Promise<unknown> {
      return ipcRenderer.invoke("vc:fs:readJson", absPath);
    },
    writeJson(absPath: string, value: unknown): Promise<string> {
      return ipcRenderer.invoke("vc:fs:writeJson", absPath, value);
    },
    readText(absPath: string): Promise<string | null> {
      return ipcRenderer.invoke("vc:fs:readText", absPath);
    },
    writeText(absPath: string, text: string): Promise<string> {
      return ipcRenderer.invoke("vc:fs:writeText", absPath, text);
    },
    list(absDir: string): Promise<{ name: string; isDir: boolean }[]> {
      return ipcRenderer.invoke("vc:fs:list", absDir);
    },
    copy(srcAbs: string, destAbs: string): Promise<string> {
      return ipcRenderer.invoke("vc:fs:copy", srcAbs, destAbs);
    },
    remove(absPath: string): Promise<void> {
      return ipcRenderer.invoke("vc:fs:remove", absPath);
    },
    stat(absPath: string): Promise<{ exists: boolean; isDir?: boolean; size?: number; mtimeMs?: number }> {
      return ipcRenderer.invoke("vc:fs:stat", absPath);
    },
    presetsDir(): Promise<string> {
      return ipcRenderer.invoke("vc:fs:presetsDir");
    },
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
  /** Build identity (version + build number + git SHA + timestamp) for the
   *  About card. Resolved by main from package.json + build-info.json. */
  buildInfo(): Promise<BuildInfo> {
    return ipcRenderer.invoke("vc:buildInfo");
  },
  /** Brand identity (author / org / license / homepage) for the About card. */
  appInfo(): Promise<AppInfo> {
    return ipcRenderer.invoke("vc:appInfo");
  },
  /** Install the app menu with renderer-localised labels (Shell calls this on
   *  mount and on every language switch). */
  setMenu(labels: MenuLabels): Promise<void> {
    return ipcRenderer.invoke("vc:setMenu", labels);
  },
  platform: process.platform,
};

export type VcApi = typeof api;

contextBridge.exposeInMainWorld("vc", api);
