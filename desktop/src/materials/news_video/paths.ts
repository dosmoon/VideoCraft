/**
 * News-video material on-disk path resolution (ADR-0008 TS port of
 * `src/materials/news_video/paths.py`).
 *
 * The ONE place that knows the on-disk layout of a news_video instance. Given an
 * instance's absolute directory (resolved via the `project.material_instance_dir`
 * RPC — the framework dir owner; paths here never rebuild that layout), these
 * derive the source/ + subtitles/ slots and their well-known files. Pure string
 * joins (forward-slash, like schema.ts — the main-process fs normalizes for
 * Windows); `sourceStatus` is the only Fs-backed helper since it stats the file.
 *
 * Python's default-instance resolution (first-on-disk) is intentionally NOT
 * ported here: in TS the bound instance id is always explicit, so the model
 * resolves the instance dir via RPC before calling these helpers.
 */

import type { Fs } from "../../renderer/ipc/fs";

export const SOURCE_VIDEO_FILENAME = "video.mp4";
export const SOURCE_META_FILENAME = "meta.json";

export const sourceDir = (instanceDir: string): string => `${instanceDir}/source`;
export const subtitlesDir = (instanceDir: string): string => `${instanceDir}/subtitles`;
export const sourceVideoPath = (instanceDir: string): string =>
  `${sourceDir(instanceDir)}/${SOURCE_VIDEO_FILENAME}`;
export const sourceMetaPath = (instanceDir: string): string =>
  `${sourceDir(instanceDir)}/${SOURCE_META_FILENAME}`;

/** "ready" if source/video.mp4 is a non-empty file, else "missing". */
export async function sourceStatus(fs: Fs, instanceDir: string): Promise<"ready" | "missing"> {
  const st = await fs.stat(sourceVideoPath(instanceDir));
  return st.exists && !st.isDir && (st.size ?? 0) > 0 ? "ready" : "missing";
}
