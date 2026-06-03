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
    return {
      userData: join(exeDir, "user_data"),
      sidecar: {
        command: join(res, "sidecar", "core_rpc.exe"),
        args: [],
        cwd: join(res, "sidecar"),
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
    sidecar: { command, args: ["-u", "-m", "core_rpc.server"], cwd: repoRoot },
  };
}
