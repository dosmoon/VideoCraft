/// <reference types="vite/client" />

// Mirror of electron/preload.ts `VcApi` (kept in sync by hand — the preload
// lives in the node tsconfig, so we don't cross-import it here).
interface VcRpcApi {
  call(method: string, params?: Record<string, unknown>): Promise<unknown>;
  onNotification(cb: (method: string, params: unknown) => void): () => void;
}

interface VcApi {
  mediaUrl(absPath: string): string;
  spikeMediaUrl(name: string): string;
  writeExport(name: string, bytes: Uint8Array): Promise<string>;
  pickVideo(): Promise<string | null>;
  pickFolder(): Promise<string | null>;
  rpc: VcRpcApi;
  platform: string;
}

interface Window {
  vc: VcApi;
}
