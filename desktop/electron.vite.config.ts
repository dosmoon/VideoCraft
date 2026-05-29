import { resolve } from "node:path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import react from "@vitejs/plugin-react";

// Electron-minimal scaffold for the substrate round (foundation doc §10 step 0).
// Layout deviates from electron-vite's default `src/{main,preload,renderer}`:
// main/preload live under electron/, and the renderer shares `src/` with the
// substrate-free pure-logic layer (src/composition, src/creations) so the
// renderer can later import resolveFrameAt() directly. `server.fs.allow` is
// widened to the package root so the dev server can serve those modules.
export default defineConfig({
  // Main + preload emit CommonJS (.cjs). The package is ESM (`type: module`)
  // for the pure-logic layer + renderer, but the Electron entry is CJS: it's
  // the battle-tested path (`require('electron')` needs no ESM-interop hooks,
  // which Electron's bundled Node fails to install for an ESM `import`).
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: "out/main",
      rollupOptions: {
        input: { index: resolve(__dirname, "electron/main.ts") },
        output: { format: "cjs", entryFileNames: "[name].cjs" },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: "out/preload",
      rollupOptions: {
        input: { index: resolve(__dirname, "electron/preload.ts") },
        output: { format: "cjs", entryFileNames: "[name].cjs" },
      },
    },
  },
  renderer: {
    root: resolve(__dirname, "src/renderer"),
    plugins: [react()],
    resolve: {
      alias: {
        "@composition": resolve(__dirname, "src/composition"),
        "@creations": resolve(__dirname, "src/creations"),
      },
    },
    build: {
      outDir: "out/renderer",
      rollupOptions: { input: { index: resolve(__dirname, "src/renderer/index.html") } },
    },
    server: {
      port: 5174,
      fs: { allow: [resolve(__dirname)] },
    },
  },
});
