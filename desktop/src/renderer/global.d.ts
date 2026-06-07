/// <reference types="vite/client" />

// Mirror of electron/preload.ts `VcApi` (kept in sync by hand — the preload
// lives in the node tsconfig, so we don't cross-import it here).
interface VcRpcApi {
  call(method: string, params?: Record<string, unknown>): Promise<unknown>;
  onNotification(cb: (method: string, params: unknown) => void): () => void;
}

interface VcFsApi {
  readJson(absPath: string): Promise<unknown>;
  writeJson(absPath: string, value: unknown): Promise<string>;
  readText(absPath: string): Promise<string | null>;
  writeText(absPath: string, text: string): Promise<string>;
  list(absDir: string): Promise<{ name: string; isDir: boolean }[]>;
  copy(srcAbs: string, destAbs: string): Promise<string>;
  remove(absPath: string): Promise<void>;
  stat(absPath: string): Promise<{ exists: boolean; isDir?: boolean; size?: number; mtimeMs?: number }>;
  presetsDir(): Promise<string>;
}

interface VcFfmpegEncodeApi {
  probe(): Promise<{ ffmpeg: boolean; nvenc: boolean }>;
  start(params: {
    outputPath: string;
    width: number;
    height: number;
    fps: number;
    bitrate: number;
    pixfmt: "bgra" | "rgba";
    sourcePath?: string;
    audioStartSec?: number;
  }): Promise<number>;
  writeFrame(id: number, bytes: Uint8Array): Promise<void>;
  finish(id: number): Promise<string>;
  abort(id: number): Promise<void>;
}

interface VcApi {
  mediaUrl(absPath: string): string;
  writeFile(absPath: string, bytes: Uint8Array): Promise<string>;
  openWriteStream(absPath: string): Promise<number>;
  writeStreamChunk(id: number, position: number, bytes: Uint8Array): Promise<void>;
  closeWriteStream(id: number): Promise<string>;
  abortWriteStream(id: number): Promise<void>;
  ffmpegEncode: VcFfmpegEncodeApi;
  splitChapters(params: {
    inputPath: string;
    outDir: string;
    segments: { name: string; startSec: number; durationSec: number }[];
  }): Promise<{ written: string[]; failed: { name: string; error: string }[] }>;
  showInFolder(absPath: string): Promise<void>;
  openPath(absPath: string): Promise<string>;
  openExternal(url: string): Promise<void>;
  pickVideo(): Promise<string | null>;
  pickImage(): Promise<string | null>;
  pickFolder(): Promise<string | null>;
  pickSubtitle(): Promise<string | null>;
  fs: VcFsApi;
  rpc: VcRpcApi;
  platform: string;
}

interface Window {
  vc: VcApi;
}
