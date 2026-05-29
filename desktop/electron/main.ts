/**
 * Electron main-process entry for the VideoCraft substrate scaffold.
 *
 * Substrate round scope (foundation doc §10 step 0): just enough shell to host
 * the WebGPU/WebCodecs spikes in a real Chromium renderer. No Python sidecar,
 * no business IPC yet (that's the migration doc's M0/M1, a later round).
 *
 * Responsibilities:
 *   - register the vc-media:// scheme (must precede app.whenReady)
 *   - create the main window pointing at the renderer
 *   - serve local media bytes with HTTP range support so the renderer's
 *     mp4box + WebCodecs pipeline can pull a source clip incrementally
 */

import { app, BrowserWindow, ipcMain, net, protocol, shell } from "electron";
import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

// CJS bundle (see electron.vite.config.ts) — __dirname is available.
const here = __dirname;
// here = out/main in both dev and packaged; ../../ is the desktop repo dir.
const spikeAssetsDir = resolve(here, "../../spike-assets");
const exportDir = resolve(here, "../../user_data/exports");

// Portable data (project rule [[feedback_portable_data]]): keep all app state
// inside the repo, never %APPDATA%. Also gives a fresh GPU shader cache, which
// dodges the access-denied/corruption seen when a crashed instance left a
// locked cache in %APPDATA%.
app.setPath("userData", resolve(here, "../../user_data"));
app.commandLine.appendSwitch("disable-gpu-shader-disk-cache");
// The GPU process intermittently crashed at startup with "Buffer handle is
// null / SharedImage failed" (a GPU-sandbox shared-memory failure in this
// launch context). Relaxing the GPU sandbox keeps hardware WebGPU working and
// makes launches deterministic. Dev/spike concession; revisit for packaging.
app.commandLine.appendSwitch("disable-gpu-sandbox");

function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    show: false,
    title: "VideoCraft (substrate spike)",
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
    },
  },
]);

function registerMediaProtocol(): void {
  protocol.handle("vc-media", async (req) => {
    try {
      const url = new URL(req.url);
      const rel = decodeURIComponent(url.pathname.replace(/^\//, ""));
      if (!rel) return new Response(null, { status: 404 });
      // host "local" = absolute path; host "spike" = relative to spike-assets/.
      let absPath: string;
      if (url.host === "local") absPath = rel;
      else if (url.host === "spike") absPath = join(spikeAssetsDir, rel);
      else return new Response(null, { status: 404 });
      // net.fetch honours Range so the renderer's mp4box pipeline can stream.
      return await net.fetch(pathToFileURL(absPath).toString());
    } catch (err) {
      console.error("vc-media handler failed:", err);
      return new Response(null, { status: 500 });
    }
  });
}

// Spike C export sink: the renderer can't write files; it hands muxed mp4
// bytes here for the main process to persist under user_data/exports.
ipcMain.handle("vc:writeExport", async (_e, name: string, bytes: Uint8Array) => {
  await mkdir(exportDir, { recursive: true });
  const out = join(exportDir, name);
  await writeFile(out, Buffer.from(bytes));
  return out;
});

void app.whenReady().then(() => {
  registerMediaProtocol();
  createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
