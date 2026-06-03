/**
 * News-desk preview-data builder (ADR-0008 B4 TS port of
 * `src/creations/news_desk/preview.py`).
 *
 * News_desk renders the FULL source (no candidate cutting), so the preview is
 * just the source media ref + duration + each subtitle component's snapshot SRT
 * keyed by its own `srt_path` (the assembler's cuesBySrtPath key). Chapter data
 * is NOT returned — the chapter component's schedule is already snapshotted into
 * config at import time, so it rides through load_config/list_components.
 *
 * mediaRef + durationSec are resolved upstream (clientBackend: model.sourceVideoPath
 * + project meta); this module is the pure, injectable part (component srt_path
 * resolution against the instance dir), so vitest can drive it with an in-memory Fs.
 */

import type { Fs } from "../../renderer/ipc/fs";
import type { ComponentDict } from "./componentDefs";

export interface NewsDeskPreviewResult {
  mediaRef: string | null;
  durationSec: number;
  /** Absolute snapshot SRT path per subtitle component, keyed by its srt_path. */
  subtitlePaths: Record<string, string>;
}

export function emptyNewsDeskPreview(): NewsDeskPreviewResult {
  return { mediaRef: null, durationSec: 0, subtitlePaths: {} };
}

/** True for an absolute path (POSIX `/…` or Windows `X:\…` / `X:/…` / UNC). */
export function isAbsPath(p: string): boolean {
  return /^([a-zA-Z]:[\\/]|[\\/])/.test(p);
}

/** Resolve each subtitle component's snapshot SRT (relative to the instance dir
 *  unless already absolute) and keep only the ones present on disk. */
export async function buildNewsDeskPreview(
  components: ComponentDict[],
  instanceDir: string,
  fs: Fs,
  mediaRef: string | null,
  durationSec: number,
): Promise<NewsDeskPreviewResult> {
  const subtitlePaths: Record<string, string> = {};
  for (const c of components) {
    if (c["kind"] !== "subtitle") continue;
    const rel = String(c["srt_path"] ?? "").trim();
    if (!rel) continue;
    const abs = isAbsPath(rel) ? rel : `${instanceDir}/${rel}`;
    if ((await fs.stat(abs)).exists) subtitlePaths[rel] = abs;
  }
  return { mediaRef, durationSec, subtitlePaths };
}
