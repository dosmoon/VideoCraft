/**
 * Electron main-process entry for the VideoCraft desktop app.
 *
 * Responsibilities:
 *   - register the vc-media:// scheme (must precede app.whenReady)
 *   - spawn + own the Python core sidecar and bridge business RPC to it
 *   - create the main window pointing at the renderer
 *   - serve local media bytes with HTTP range support so the renderer's
 *     mp4box + WebCodecs pipeline can pull a source clip incrementally
 */

import { app, BrowserWindow, dialog, ipcMain, net, protocol, shell } from "electron";
import {
  copyFile,
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { Sidecar, SidecarError } from "./sidecar";

// CJS bundle (see electron.vite.config.ts) — __dirname is available.
const here = __dirname;
// here = out/main in both dev and packaged; ../../ is the desktop repo dir,
// ../../../ is the VideoCraft repo root (where core_rpc/ + myenv/ live).
const repoRoot = resolve(here, "../../../");

// Single Python sidecar for the whole app (migration doc §2.3: one in-memory
// owner of project/material state; disk is the source of truth).
const sidecar = new Sidecar({ repoRoot });

// ── Generic file I/O for the renderer (ADR-0008 architecture pivot) ──────────
// Plugins are moving to pure TS: their config/preset/data files are read+written
// by the renderer through these handlers (Node fs in the main process), instead
// of through per-plugin Python. `assertInProject` is the security boundary — a
// renderer-supplied absolute path is only honoured if it resolves inside the
// open project root or <userData>/presets (the global preset store). The project
// root is learned by snooping proxied project.open/close in the vc:rpc handler
// (single source of truth; no duplicate state).
let currentProjectRoot: string | null = null;

function assertInProject(absPath: string): string {
  const resolved = resolve(absPath);
  const roots = [
    ...(currentProjectRoot ? [currentProjectRoot] : []),
    join(app.getPath("userData"), "presets"),
  ].map((r) => resolve(r));
  // Windows paths are case-insensitive; compare normalized. Use a trailing sep
  // so "/proj" doesn't match "/project2".
  const norm = (p: string) => (process.platform === "win32" ? p.toLowerCase() : p);
  const target = norm(resolved);
  const ok = roots.some((root) => {
    const r = norm(root);
    return target === r || target.startsWith(r + sep);
  });
  if (!ok) {
    throw new Error(`vc:fs path outside allowed roots: ${absPath}`);
  }
  return resolved;
}

const isENOENT = (err: unknown): boolean =>
  (err as NodeJS.ErrnoException)?.code === "ENOENT";

// Portable data (project rule [[feedback_portable_data]]): keep all app state
// inside the repo, never %APPDATA%. Also gives a fresh GPU shader cache, which
// dodges the access-denied/corruption seen when a crashed instance left a
// locked cache in %APPDATA%.
app.setPath("userData", resolve(here, "../../user_data"));
app.commandLine.appendSwitch("disable-gpu-shader-disk-cache");
// The GPU process intermittently crashed at startup with "Buffer handle is
// null / SharedImage failed" (a GPU-sandbox shared-memory failure in this
// launch context). Relaxing the GPU sandbox keeps hardware WebGPU working and
// makes launches deterministic. Dev concession; revisit for packaging.
app.commandLine.appendSwitch("disable-gpu-sandbox");

// ── Win11 Build 26200 sandbox-incompat workaround (TEMPORARY) ────────────────
// Windows 11 Build 26200 (2026-05 cumulative update) changed low-level sandbox
// behaviour in a way incompatible with the Electron 39-42 process-sandbox
// implementation: child (GPU/renderer) processes crash on launch with
// exit_code -2147483645 (0x80000003) — "GPU process isn't usable. Goodbye." /
// render-process-gone { reason:'crashed' }. It's a cross-app upstream incident
// (VS Code / Notion / GitHub Desktop hit it too); no local fix, only bypass.
//
// We do NOT drop the sandbox unconditionally (keep its security on healthy
// boxes). Instead: when a process dies with that exact signature, relaunch ONCE
// with --no-sandbox. A flag on the relaunch argv prevents an infinite loop.
// Remove this whole block once upstream Electron fixes the Build 26200 incompat.
//   (Alternative considered: pin to a pre-incompat Electron major — rejected:
//    that major is EOL and lags ~10 Chromium versions on the WebGPU/WebCodecs
//    APIs the compositor depends on.)
const SANDBOX_CRASH_CODE = -2147483645;
const RELAUNCHED_FLAG = "--vc-no-sandbox-relaunch";
const isSandboxRelaunch = process.argv.includes(RELAUNCHED_FLAG);

if (process.platform === "win32" && isSandboxRelaunch) {
  // We are the relaunched instance: the sandbox is the suspected culprit, so
  // run this session without it.
  app.commandLine.appendSwitch("no-sandbox");
}

function relaunchWithoutSandbox(tag: string): void {
  if (process.platform !== "win32" || isSandboxRelaunch) return; // retry once only
  console.error(
    `[sandbox] ${tag} crashed (exit ${SANDBOX_CRASH_CODE}); relaunching with ` +
      "--no-sandbox (Win11 Build 26200 workaround)",
  );
  app.relaunch({ args: process.argv.slice(1).concat(RELAUNCHED_FLAG) });
  app.exit(0);
}

// A renderer dying with the sandbox signature ⇒ relaunch unsandboxed.
app.on("render-process-gone", (_e, _wc, details) => {
  if (details.reason === "crashed" && details.exitCode === SANDBOX_CRASH_CODE) {
    relaunchWithoutSandbox("render-process");
  }
});
// Same for GPU/utility child processes ("GPU process isn't usable. Goodbye.").
app.on("child-process-gone", (_e, details) => {
  if (details.reason === "crashed" && details.exitCode === SANDBOX_CRASH_CODE) {
    relaunchWithoutSandbox(`child-process(${details.type})`);
  }
});

function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    show: false,
    title: "VideoCraft",
    webPreferences: {
      preload: join(here, "../preload/index.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  win.once("ready-to-show", () => win.show());
  win.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  // electron-vite injects ELECTRON_RENDERER_URL in dev.
  const devServerUrl = process.env["ELECTRON_RENDERER_URL"];
  if (!app.isPackaged && devServerUrl) {
    void win.loadURL(devServerUrl);
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    void win.loadFile(resolve(here, "../renderer/index.html"));
  }

  return win;
}

// vc-media://local/<percent-encoded absolute path> → the file's bytes.
// `standard + secure + stream + supportFetchAPI` lets the renderer fetch()
// it and lets net.fetch honour Range requests (mp4box pulls byte ranges).
protocol.registerSchemesAsPrivileged([
  {
    scheme: "vc-media",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
      bypassCSP: true,
      // Electron 42 / Chromium ~140 tightened cross-origin fetch of custom
      // schemes: fetching vc-media:// from the http://localhost dev origin is
      // CORS-blocked unless the scheme is registered CORS-enabled. (Electron 33
      // didn't require this — surfaced by the 33→42 bump.)
      corsEnabled: true,
    },
  },
]);

function registerMediaProtocol(): void {
  protocol.handle("vc-media", async (req) => {
    try {
      const url = new URL(req.url);
      const rel = decodeURIComponent(url.pathname.replace(/^\//, ""));
      if (!rel) return new Response(null, { status: 404 });
      // host "local" = an absolute path on disk.
      if (url.host !== "local") return new Response(null, { status: 404 });
      const absPath = rel;
      // net.fetch honours Range so the renderer's mp4box pipeline can stream.
      return await net.fetch(pathToFileURL(absPath).toString());
    } catch (err) {
      console.error("vc-media handler failed:", err);
      return new Response(null, { status: 500 });
    }
  });
}

// Real-video smoke test: pick an arbitrary local video to load via vc-media://.
ipcMain.handle("vc:pickVideo", async () => {
  const r = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [{ name: "Video", extensions: ["mp4", "mov", "m4v", "webm", "mkv"] }],
  });
  return r.canceled ? null : (r.filePaths[0] ?? null);
});

// Pick a local image file (image-watermark path) to load via vc-media://.
ipcMain.handle("vc:pickImage", async () => {
  const r = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [{ name: "Image", extensions: ["png", "jpg", "jpeg", "webp", "gif", "bmp"] }],
  });
  return r.canceled ? null : (r.filePaths[0] ?? null);
});

// Hub launcher: pick a project folder to open (project.open takes a folder path).
ipcMain.handle("vc:pickFolder", async () => {
  const r = await dialog.showOpenDialog({ properties: ["openDirectory"] });
  return r.canceled ? null : (r.filePaths[0] ?? null);
});

// Pick an external SRT to import into a material's subtitles slot.
ipcMain.handle("vc:pickSubtitle", async () => {
  const r = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [{ name: "Subtitle", extensions: ["srt"] }],
  });
  return r.canceled ? null : (r.filePaths[0] ?? null);
});

// Write bytes to an absolute path (rendered clips → the creation instance dir;
// the path is computed by the Python sidecar, which owns naming/locations).
ipcMain.handle("vc:writeFile", async (_e, absPath: string, bytes: Uint8Array) => {
  await mkdir(resolve(absPath, ".."), { recursive: true });
  await writeFile(absPath, Buffer.from(bytes));
  return absPath;
});

// ── vc:fs:* — generic project-scoped file I/O (ADR-0008) ─────────────────────
// readJson/readText/list/stat degrade to null/[]/{exists:false} on a missing
// path (a clean "not there yet" signal for TS owners). writeJson/writeText are
// atomic (.tmp + rename, mkdir -p) and match Python *.save() byte-for-byte:
// 2-space indent, no trailing newline, non-ASCII kept raw (JSON.stringify ==
// json.dump(ensure_ascii=False, indent=2)).
ipcMain.handle("vc:fs:readJson", async (_e, absPath: string) => {
  const p = assertInProject(absPath);
  try {
    return JSON.parse(await readFile(p, "utf-8"));
  } catch (err) {
    if (isENOENT(err)) return null;
    throw err;
  }
});
ipcMain.handle("vc:fs:writeJson", async (_e, absPath: string, value: unknown) => {
  const p = assertInProject(absPath);
  await mkdir(dirname(p), { recursive: true });
  const tmp = p + ".tmp";
  await writeFile(tmp, JSON.stringify(value, null, 2), { encoding: "utf-8" });
  await rename(tmp, p);
  return p;
});
ipcMain.handle("vc:fs:readText", async (_e, absPath: string) => {
  const p = assertInProject(absPath);
  try {
    return await readFile(p, "utf-8");
  } catch (err) {
    if (isENOENT(err)) return null;
    throw err;
  }
});
ipcMain.handle("vc:fs:writeText", async (_e, absPath: string, text: string) => {
  const p = assertInProject(absPath);
  await mkdir(dirname(p), { recursive: true });
  const tmp = p + ".tmp";
  await writeFile(tmp, text, { encoding: "utf-8" });
  await rename(tmp, p);
  return p;
});
ipcMain.handle("vc:fs:list", async (_e, absDir: string) => {
  const p = assertInProject(absDir);
  try {
    const entries = await readdir(p, { withFileTypes: true });
    return entries.map((e) => ({ name: e.name, isDir: e.isDirectory() }));
  } catch (err) {
    if (isENOENT(err)) return [];
    throw err;
  }
});
// copy: snapshot a file INTO the project (ADR-0003 — copy, not reference). Only
// the destination is constrained; the source may be a user-picked external file
// (e.g. an imported SRT) or a material file, and is read-only.
ipcMain.handle("vc:fs:copy", async (_e, srcAbs: string, destAbs: string) => {
  const dest = assertInProject(destAbs);
  await mkdir(dirname(dest), { recursive: true });
  await copyFile(resolve(srcAbs), dest);
  return dest;
});
ipcMain.handle("vc:fs:remove", async (_e, absPath: string) => {
  const p = assertInProject(absPath);
  await rm(p, { recursive: true, force: true });
});
ipcMain.handle("vc:fs:stat", async (_e, absPath: string) => {
  const p = assertInProject(absPath);
  try {
    const s = await stat(p);
    return { exists: true, isDir: s.isDirectory(), size: s.size, mtimeMs: s.mtimeMs };
  } catch (err) {
    if (isENOENT(err)) return { exists: false };
    throw err;
  }
});

// OS integration for the Export tab's row actions.
ipcMain.handle("vc:showInFolder", async (_e, absPath: string) => {
  shell.showItemInFolder(absPath);
});
ipcMain.handle("vc:openPath", async (_e, absPath: string) => {
  return shell.openPath(absPath); // "" on success, else an error string
});
ipcMain.handle("vc:openExternal", async (_e, url: string) => {
  // Only http(s) — never let the renderer hand an arbitrary scheme to the OS.
  if (/^https?:\/\//i.test(url)) void shell.openExternal(url);
});

// Business RPC bridge: renderer → Python sidecar. We return a tagged result
// rather than throwing, because ipcMain.handle's error serialization drops the
// JSON-RPC error code/data; the renderer client unwraps this back into a value
// or a typed error.
type RpcReply =
  | { ok: true; result: unknown }
  | { ok: false; code: number; message: string; data?: unknown };

ipcMain.handle(
  "vc:rpc",
  async (_e, method: string, params?: Record<string, unknown>): Promise<RpcReply> => {
    try {
      const result = await sidecar.call(method, params);
      // Snoop project lifecycle so assertInProject knows the active root
      // (single source of truth — the renderer already drives these).
      if (method === "project.open" && typeof params?.["folder"] === "string") {
        currentProjectRoot = resolve(params["folder"] as string);
      } else if (method === "project.close") {
        currentProjectRoot = null;
      }
      return { ok: true, result };
    } catch (err) {
      if (err instanceof SidecarError) {
        return { ok: false, code: err.code, message: err.message, data: err.data };
      }
      return { ok: false, code: -1, message: err instanceof Error ? err.message : String(err) };
    }
  },
);

// Fan server→client notifications (events + job progress) out to all windows.
sidecar.onNotification((method, params) => {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) win.webContents.send("vc:rpc:notification", method, params);
  }
});

void app.whenReady().then(() => {
  registerMediaProtocol();
  sidecar.start();
  createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// Tear the sidecar down with the app so no orphaned python child lingers.
app.on("before-quit", () => sidecar.dispose());
