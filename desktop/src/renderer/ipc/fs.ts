/**
 * Typed, project-scoped file I/O for TS plugins (ADR-0008 pivot).
 *
 * Thin generic-typed wrappers over `window.vc.fs.*` (Electron main, Node fs).
 * All paths are ABSOLUTE and must resolve inside the open project (or
 * <userData>/presets) — the main process `assertInProject` enforces this and
 * throws otherwise.
 *
 * The `Fs` type is the injection seam: the pure plugin ports (configOwner,
 * presets, render, publish, hotclipsRepo, imports, material model) take an `Fs`
 * argument so vitest can pass an in-memory fake instead of touching disk.
 * `realFs` is the production binding to `window.vc.fs`.
 *
 * Missing-path contract (matches the main handlers): readJson/readText → null,
 * list → [], stat → { exists: false }. writeJson/writeText are atomic and write
 * 2-space-indent JSON with no trailing newline, byte-for-byte matching the
 * retired Python `*.save()` so on-disk goldens are unchanged.
 */

export interface FsEntry {
  name: string;
  isDir: boolean;
}

export interface FsStat {
  exists: boolean;
  isDir?: boolean;
  size?: number;
  mtimeMs?: number;
}

export interface Fs {
  readJson<T = unknown>(absPath: string): Promise<T | null>;
  writeJson(absPath: string, value: unknown): Promise<string>;
  readText(absPath: string): Promise<string | null>;
  writeText(absPath: string, text: string): Promise<string>;
  list(absDir: string): Promise<FsEntry[]>;
  copy(srcAbs: string, destAbs: string): Promise<string>;
  remove(absPath: string): Promise<void>;
  stat(absPath: string): Promise<FsStat>;
}

export const realFs: Fs = {
  readJson<T = unknown>(absPath: string): Promise<T | null> {
    return window.vc.fs.readJson(absPath) as Promise<T | null>;
  },
  writeJson(absPath: string, value: unknown): Promise<string> {
    return window.vc.fs.writeJson(absPath, value);
  },
  readText(absPath: string): Promise<string | null> {
    return window.vc.fs.readText(absPath);
  },
  writeText(absPath: string, text: string): Promise<string> {
    return window.vc.fs.writeText(absPath, text);
  },
  list(absDir: string): Promise<FsEntry[]> {
    return window.vc.fs.list(absDir);
  },
  copy(srcAbs: string, destAbs: string): Promise<string> {
    return window.vc.fs.copy(srcAbs, destAbs);
  },
  remove(absPath: string): Promise<void> {
    return window.vc.fs.remove(absPath);
  },
  stat(absPath: string): Promise<FsStat> {
    return window.vc.fs.stat(absPath);
  },
};
