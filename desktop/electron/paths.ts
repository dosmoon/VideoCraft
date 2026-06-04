/**
 * Filesystem layout for both dev and packaged runs (P3 packaging design §4).
 *
 * Single source of truth for "where do the sidecar, user data, and bundled
 * resources live". Every consumer (main.ts, sidecar.ts) reads from here so the
 * dev↔packaged seam exists in exactly ONE place — keyed on `app.isPackaged`.
 *
 * Dev   : spawn the repo's uv-managed venv python running `-m core_rpc.server`
 *         from the repo root; user_data is repo-local.
 * Packaged: spawn the PyInstaller onedir `core_rpc.exe` under resources/sidecar/;
 *         user_data is install-local (portable rule — never %APPDATA%).
 */

import { app } from "electron";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

/** How to launch the Python sidecar child process. */
export interface SidecarLaunch {
  command: string;
  args: string[];
  cwd: string;
  /**
   * Extra env vars merged into the sidecar's environment. Carries VC_USER_DATA:
   * the sidecar (core.user_data) resolves models / settings / py-extra under it.
   * REQUIRED packaged — there the frozen exe's __file__ sits in the sealed,
   * update-wiped resources/ tree, so it cannot guess the writable location.
   */
  env: Record<string, string>;
  /**
   * Directory prepended to the sidecar's PATH. Packaged: process.resourcesPath,
   * where the bundled ffmpeg.exe / ffprobe.exe live (extraResources) — so the
   * sidecar's `shutil.which("ffmpeg")` AND yt-dlp's auto FFmpegMerger (1080p =
   * separate DASH streams merged via ffmpeg) find them without a system install.
   * Omitted in dev: the dev machine's system ffmpeg on PATH is used.
   */
  extraPath?: string;
}

export interface AppPaths {
  /** Absolute path passed to app.setPath("userData"). */
  userData: string;
  /** How to launch the Python sidecar. */
  sidecar: SidecarLaunch;
}

/**
 * Resolve runtime paths. `mainDir` is the directory of the running main bundle
 * (out/main — the same relative layout in dev and packaged, per electron-vite).
 */
export function resolveAppPaths(mainDir: string): AppPaths {
  if (app.isPackaged) {
    // Packaged: the frozen onedir sidecar (carrying its own src/ + deps) lives
    // under resources/sidecar/; no repo, venv, or cwd-on-repo-root assumption.
    // user_data sits beside the app exe so all state stays install-local.
    const res = process.resourcesPath;
    const exeDir = dirname(app.getPath("exe"));
    const userData = join(exeDir, "user_data");
    return {
      userData,
      sidecar: {
        command: join(res, "sidecar", "core_rpc.exe"),
        args: [],
        cwd: join(res, "sidecar"),
        // Unify the frozen sidecar's user_data with Electron's — install-local,
        // writable, survives updates (the resources/ tree does not).
        env: { VC_USER_DATA: userData },
        // Bundled ffmpeg/ffprobe sit directly under resources/ (extraResources).
        extraPath: res,
      },
    };
  }

  // Dev: run the sidecar as a module from the repo root using the repo venv.
  // repoRoot = <mainDir>/../../../  (out/main → desktop → repo root, where
  // core_rpc/ + myenv/ live).
  const repoRoot = resolve(mainDir, "../../../");
  const venvPy =
    process.platform === "win32"
      ? join(repoRoot, "myenv", "Scripts", "python.exe")
      : join(repoRoot, "myenv", "bin", "python");
  const command = existsSync(venvPy)
    ? venvPy
    : process.platform === "win32"
      ? "python"
      : "python3";
  return {
    userData: resolve(mainDir, "../../user_data"),
    sidecar: {
      command,
      args: ["-u", "-m", "core_rpc.server"],
      cwd: repoRoot,
      // Pin the sidecar's user_data to the repo root — its own default in dev
      // (core.user_data resolves <repo>/user_data from __file__). Set explicitly
      // so the dev↔packaged seam for VC_USER_DATA lives only here, not implicitly.
      env: { VC_USER_DATA: join(repoRoot, "user_data") },
    },
  };
}
