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

import { app, BrowserWindow, dialog, ipcMain, protocol, shell } from "electron";
import { createReadStream, existsSync, writeFileSync } from "node:fs";
import {
  copyFile,
  mkdir,
  open,
  readFile,
  readdir,
  rename,
  rm,
  stat,
  writeFile,
  type FileHandle,
} from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import { release } from "node:os";
import { Readable } from "node:stream";
import { Sidecar, SidecarError } from "./sidecar";
import { resolveAppPaths } from "./paths";
import { readBuildInfo, type BuildInfo } from "./buildInfo";
import { readAppInfo, type AppInfo } from "./appInfo";
import { applyAppMenu, DEFAULT_MENU_LABELS, type MenuLabels } from "./menu";
import * as ffmpeg from "./ffmpeg";

// Extension → MIME for the vc-media:// server (video for <video>/mp4box, images
// for the watermark picker). Unknown falls back to octet-stream.
const MEDIA_MIME: Record<string, string> = {
  ".mp4": "video/mp4",
  ".m4v": "video/mp4",
  ".webm": "video/webm",
  ".mkv": "video/x-matroska",
  ".mov": "video/quicktime",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
};
function mediaMime(path: string): string {
  const dot = path.lastIndexOf(".");
  return (dot >= 0 && MEDIA_MIME[path.slice(dot).toLowerCase()]) || "application/octet-stream";
}

// CJS bundle (see electron.vite.config.ts) — __dirname is available.
const here = __dirname;
// Resolve the dev↔packaged filesystem layout (sidecar launch + userData) in one
// place (packaging-design.md §4). `here` = out/main in both dev and packaged.
const appPaths = resolveAppPaths(here);

// Single Python sidecar for the whole app (migration doc §2.3: one in-memory
// owner of project/material state; disk is the source of truth).
const sidecar = new Sidecar(appPaths.sidecar);

// Build identity for the About card. The release `version` is the single source
// in package.json (app.getVersion()); build number / git SHA / timestamp come
// from the build-time build-info.json (paths.ts), with a "dev" fallback when it
// is absent (e.g. `pnpm dev`). Cached on first read. See docs/versioning.md.
let buildInfoCache: BuildInfo | null = null;
async function getBuildInfo(): Promise<BuildInfo> {
  if (!buildInfoCache) {
    const gen = await readBuildInfo(appPaths.buildInfoPath);
    buildInfoCache = {
      version: app.getVersion(),
      build: gen?.build ?? "dev",
      commit: gen?.commit ?? "",
      builtAt: gen?.builtAt ?? "",
    };
  }
  return buildInfoCache;
}
ipcMain.handle("vc:buildInfo", () => getBuildInfo());

// App brand identity (author / org / license / homepage), read from package.json
// once. Feeds the About card + the native Help → About dialog. See appInfo.ts.
let appInfoCache: AppInfo | null = null;
function appInfo(): AppInfo {
  return (appInfoCache ??= readAppInfo());
}
ipcMain.handle("vc:appInfo", () => appInfo());

// Native Help → About dialog: brand identity (appInfo) + build identity (buildInfo).
function showAboutDialog(): void {
  const ai = appInfo();
  void getBuildInfo().then((bi) => {
    const detail = [
      `v${bi.version} · build ${bi.build}${bi.commit ? ` · ${bi.commit}` : ""}`,
      ai.org ? `${ai.author} · ${ai.org}` : ai.author,
      [ai.copyright, ai.license].filter(Boolean).join(" · "),
      ai.homepage,
    ]
      .filter(Boolean)
      .join("\n");
    void dialog.showMessageBox({ type: "info", title: ai.name, message: ai.name, detail, buttons: ["OK"], noLink: true });
  });
}

// Install the app menu. Labels arrive localised from the renderer (vc:setMenu);
// DEFAULT_MENU_LABELS (English) is the pre-renderer fallback. See menu.ts.
function applyMenu(labels: MenuLabels): void {
  const repoUrl = appInfo().homepage || "https://github.com/dosmoon/VideoCraft";
  applyAppMenu(labels, { onAbout: showAboutDialog, repoUrl, issuesUrl: `${repoUrl}/issues` });
}
ipcMain.handle("vc:setMenu", (_e, labels: MenuLabels) => applyMenu(labels));

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
app.setPath("userData", appPaths.userData);
app.commandLine.appendSwitch("disable-gpu-shader-disk-cache");
// The GPU process intermittently crashed at startup with "Buffer handle is
// null / SharedImage failed" (a GPU-sandbox shared-memory failure in this
// launch context). Relaxing the GPU sandbox keeps hardware WebGPU working and
// makes launches deterministic. Dev concession; revisit for packaging.
app.commandLine.appendSwitch("disable-gpu-sandbox");

// ── Win11 Build 26200 sandbox-incompat workaround (TEMPORARY) ────────────────
// Windows 11 Build 26200 (2026-05 cumulative update) changed low-level sandbox
// behaviour in a way incompatible with the Electron 39-42 process-sandbox
// implementation: sandboxed child processes die with exit_code -2147483645
// (0x80000003). It's INTERMITTENT and cross-app (VS Code / Notion / GitHub
// Desktop hit it too); no local fix, only bypass.
//
// It bites not only at launch (GPU process) but at RUNTIME: opening a <video>
// source preview spawns an audio/video-decode Utility process that hits it, and
// the reactive relaunch then restarts the whole app mid-action — losing the
// user's project + open view, which reads as a hard crash (this is exactly the
// "click source → app died" report). So instead of waiting for the crash, we
// drop the sandbox UP-FRONT on the affected build family.
//
// Decision (any ⇒ start --no-sandbox; all win32-only):
//   1. build >= 26200          — known-affected family; avoids the crash entirely
//   2. no-sandbox.flag present  — a prior session already saw the signature
//   3. relaunch argv flag       — we ARE the reactive relaunch (legacy safety net)
// Remove this whole block once upstream Electron fixes the Build 26200 incompat.
//   (Alternative considered: pin to a pre-incompat Electron major — rejected:
//    that major is EOL and lags ~10 Chromium versions on the WebGPU/WebCodecs
//    APIs the compositor depends on.)
const SANDBOX_CRASH_CODE = -2147483645;
const RELAUNCHED_FLAG = "--vc-no-sandbox-relaunch";
const isSandboxRelaunch = process.argv.includes(RELAUNCHED_FLAG);
// Persisted across sessions in user_data (preserved by the NSIS macro) so an
// affected box doesn't crash + relaunch on every single launch.
const noSandboxFlag = join(appPaths.userData, "no-sandbox.flag");

function win11SandboxAffected(): boolean {
  if (process.platform !== "win32") return false;
  // os.release() → "10.0.26200" on Win11; the build is the 3rd dotted component.
  const build = parseInt(release().split(".")[2] ?? "0", 10);
  return build >= 26200;
}

if (
  process.platform === "win32" &&
  (isSandboxRelaunch || existsSync(noSandboxFlag) || win11SandboxAffected())
) {
  app.commandLine.appendSwitch("no-sandbox");
}

function relaunchWithoutSandbox(tag: string): void {
  if (process.platform !== "win32" || isSandboxRelaunch) return; // retry once only
  // Persist the decision so the NEXT launch starts unsandboxed up-front instead
  // of crashing + relaunching again (build detection covers >= 26200; this also
  // self-heals any other affected build we didn't anticipate).
  try {
    writeFileSync(noSandboxFlag, "1");
  } catch {
    /* best-effort: persistence is an optimization, not required for correctness */
  }
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
    // Runtime window / taskbar icon (independent of the exe-embedded icon, which
    // needs winCodeSign — disabled here, restored in CI). Guard so a missing
    // build/icon.ico in a partial dev tree doesn't warn.
    ...(existsSync(appPaths.iconPath) ? { icon: appPaths.iconPath } : {}),
    webPreferences: {
      preload: join(here, "../preload/index.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      // backgroundThrottling was tried (a3669ff) to keep backgrounded exports at
      // full speed, then reverted (acf066a) and left at the Electron default.
      // NOTE: it was NOT the cause of the 60fps preview stutter — that was the
      // preview wrongly using the blocking frameAtExact (fixed in the preview
      // components). If backgrounded-export speed ever matters, measure first;
      // don't reach for a global throttling flag without evidence.
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
    // `activate: false` — open DevTools in the background. A detached DevTools
    // window that grabs focus on launch steals keyboard focus from the main
    // window, so its <input>s can't be focused/typed until DevTools is closed.
    win.webContents.openDevTools({ mode: "detach", activate: false });
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
      // host "local" = an absolute path on disk.
      if (url.host !== "local") return new Response(null, { status: 404 });
      const absPath = decodeURIComponent(url.pathname.replace(/^\//, ""));
      if (!absPath) return new Response(null, { status: 404 });

      const size = (await stat(absPath)).size;
      const type = mediaMime(absPath);
      // Serve byte ranges ourselves (HTTP 206). net.fetch(file://) did NOT forward
      // the incoming Range header, so it always returned the whole file (200) with
      // no Accept-Ranges — which left the <video> scrubber unable to seek past the
      // buffered region. Honouring Range here makes both <video> seeking and the
      // mp4box pull work.
      const range = req.headers.get("Range");
      if (range) {
        const m = /bytes=(\d*)-(\d*)/.exec(range);
        let start = m && m[1] ? parseInt(m[1], 10) : 0;
        let end = m && m[2] ? parseInt(m[2], 10) : size - 1;
        if (!Number.isFinite(start) || start < 0) start = 0;
        if (!Number.isFinite(end) || end >= size) end = size - 1;
        if (start > end) {
          return new Response(null, {
            status: 416,
            headers: { "Content-Range": `bytes */${size}` },
          });
        }
        const body = Readable.toWeb(createReadStream(absPath, { start, end })) as unknown as ReadableStream;
        return new Response(body, {
          status: 206,
          headers: {
            "Content-Type": type,
            "Content-Range": `bytes ${start}-${end}/${size}`,
            "Accept-Ranges": "bytes",
            "Content-Length": String(end - start + 1),
          },
        });
      }

      const body = Readable.toWeb(createReadStream(absPath)) as unknown as ReadableStream;
      return new Response(body, {
        status: 200,
        headers: {
          "Content-Type": type,
          "Accept-Ranges": "bytes",
          "Content-Length": String(size),
        },
      });
    } catch (err) {
      console.error("vc-media handler failed:", err);
      return new Response(null, { status: 404 });
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
// defaultPath (optional) starts the dialog at a location — used by New Project to
// land in the parent of the most-recent project.
ipcMain.handle("vc:pickFolder", async (_e, defaultPath?: string) => {
  const r = await dialog.showOpenDialog({
    properties: ["openDirectory"],
    ...(defaultPath ? { defaultPath } : {}),
  });
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

// ── vc:writeStream:* — positional streaming write to disk ────────────────────
// Used by the mp4 export path: a full-source render is too large to hold in one
// in-memory ArrayBuffer (let alone copy it over IPC), so the muxer streams 16 MiB
// chunks here as they're produced. Writes go to "<path>.part" at the muxer-given
// byte position (mp4-muxer seeks back once to patch the mdat size), then close
// renames into place (atomic) and abort discards the partial file.
const writeStreams = new Map<number, { fh: FileHandle; tmp: string; final: string }>();
let nextWriteStreamId = 1;

ipcMain.handle("vc:writeStream:open", async (_e, absPath: string) => {
  await mkdir(resolve(absPath, ".."), { recursive: true });
  const tmp = absPath + ".part";
  const fh = await open(tmp, "w");
  const id = nextWriteStreamId++;
  writeStreams.set(id, { fh, tmp, final: absPath });
  return id;
});

ipcMain.handle(
  "vc:writeStream:write",
  async (_e, id: number, position: number, bytes: Uint8Array) => {
    const s = writeStreams.get(id);
    if (!s) throw new Error(`write stream ${id} not open`);
    await s.fh.write(Buffer.from(bytes), 0, bytes.byteLength, position);
  },
);

ipcMain.handle("vc:writeStream:close", async (_e, id: number) => {
  const s = writeStreams.get(id);
  if (!s) throw new Error(`write stream ${id} not open`);
  await s.fh.close();
  writeStreams.delete(id);
  await rename(s.tmp, s.final);
  return s.final;
});

ipcMain.handle("vc:writeStream:abort", async (_e, id: number) => {
  const s = writeStreams.get(id);
  if (!s) return;
  writeStreams.delete(id);
  try {
    await s.fh.close();
  } catch {
    /* already closed */
  }
  try {
    await rm(s.tmp);
  } catch {
    /* nothing to remove */
  }
});

// ── vc:ffmpegEncode:* — native ffmpeg (NVENC) encode jobs ────────────────────
// The renderer renders frames on the GPU and pipes raw pixels here; ffmpeg
// encodes (h264_nvenc, hardware) + pulls audio from the source file. See
// electron/ffmpeg.ts.
ipcMain.handle("vc:ffmpegEncode:probe", () => ffmpeg.probeFfmpeg());
ipcMain.handle("vc:ffmpegEncode:start", (_e, params: ffmpeg.FfmpegStartParams) => ffmpeg.startJob(params));
ipcMain.handle("vc:ffmpegEncode:writeFrame", (_e, id: number, bytes: Uint8Array) => ffmpeg.writeFrame(id, bytes));
ipcMain.handle("vc:ffmpegEncode:finish", (_e, id: number) => ffmpeg.finishJob(id));
ipcMain.handle("vc:ffmpegEncode:abort", (_e, id: number) => ffmpeg.abortJob(id));
// Publish-side per-chapter split: stream-copy the rendered mp4 into chapters/*.mp4.
ipcMain.handle("vc:splitChapters", (_e, params: ffmpeg.SplitChaptersParams) => ffmpeg.splitChapters(params));

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
// The global preset store dir (cross-project), the second allowed fs root.
ipcMain.handle("vc:fs:presetsDir", () => join(app.getPath("userData"), "presets"));

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
  applyMenu(DEFAULT_MENU_LABELS); // English fallback; Shell re-sends localised labels on mount
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
app.on("before-quit", () => {
  ffmpeg.killAllFfmpeg();
  sidecar.dispose();
});
