# Substrate spike findings (2026-05-29)

> Running log for the substrate round (Electron renderer + WebGPU compositor +
> 3 spikes). Source plan: `composition-otio-foundation.md` §9/§10. Code lives in
> `desktop/`. Finalised into the foundation doc / an ADR at wrap-up.

## Environment notes (agent-launched Electron)

- **`ELECTRON_RUN_AS_NODE=1`** is set in the agent shell → Electron runs as plain
  Node, no GUI APIs. Launch with `env -u ELECTRON_RUN_AS_NODE pnpm dev`. (User's
  own terminal needs no workaround.) See [[reference_electron_run_as_node]].
- Electron `userData` pinned to repo-local `desktop/user_data` (portable-data
  rule) — also gave a fresh GPU shader cache after a corrupted-cache crash.
- GPU process intermittently crashed at startup (`exit_code=-1073741819`,
  "Buffer handle is null / SharedImage failed" = GPU-sandbox shared-memory
  failure in this launch context). Fixed deterministically with
  `--disable-gpu-sandbox` (hardware WebGPU still used). Dev/spike concession;
  revisit before packaging.

## Stack decisions confirmed

- electron-vite 2.3 + vite 6 + electron 33 + React 19 (mirrors Phase). Peer
  warning (electron-vite wants vite ≤5) is benign.
- **Main + preload emit CommonJS (.cjs)** even though the package is ESM — ESM
  main hit a Node `cjsPreparseModuleExports` crash importing `electron`. CJS is
  the bulletproof path.
- Renderer imports the substrate-free pure-logic layer via `@composition/*` /
  `@creations/*` aliases (tsconfig `paths` + vite alias). Vite 6 resolves the
  `.js`→`.ts` extension imports automatically — no plugin needed.
- mp4box 2.3 for demux (same as Phase).

## Phase 0 — scaffold ✅

Electron-minimal window + WebGPU probe. WebGPU available, hardware adapter
(nvidia / lovelace). Tests (69) + typecheck + build green.

## Phase 1 — decode → WebGPU draw ✅

Ported Phase's Demuxer / SampleIndex / FrameRingBuffer / MediaSource / ClipReader
+ a WebGPU Backend (`importExternalTexture` video-frame pipeline). Synthetic
test clip (`testsrc2`, 1280×720, 30fps, burned frame# + timecode) decodes and
plays on the WebGPU canvas; aspect-correct; play + scrub work.

## Phase 2 — FrameSlice draw layer ✅

`drawFrameSlice(resolveFrameAt(timeline, t))` dispatches by `Clip.kind`: media →
external-texture video draw; text/card overlays → canvas2D → RGBA texture →
alpha-blended overlay-texture pipeline, painted z-ascending. Fed by a timeline
built from the REAL shared components (`hookCard`/`outroCard`.compile → OTIO) —
proves the GPU layer consumes genuine pure-logic output. Hook/outro cards
composite correctly over video, z-order correct. **Python untouched.**

## Spike A — multi-segment concat + seek ✅ (de-risk met)

Single video track, 3 segments slicing one source with **non-monotonic
sourceStart** (each cut forces a backward seek across a GOP). Verified via
burned frame# vs a HUD showing the resolver's expected source frame (`exp src`)
and the decoded frame's actual pts (`decoded`).

**Result: seek lands in the correct GOP and decodes faithfully across cuts; no
crash, no frame tearing between segments.** Two small, understood, non-blocking
gaps:

1. **`decoded − burned# ≈ +2` (constant)** — test-asset artifact, NOT engine.
   The clip has B-frames (H.264 High), so container pts is offset ~2 frames from
   drawtext's content-order number. The engine reads container pts faithfully;
   real footage has no "burned number" to mismatch.
2. **`exp src − decoded ≈ 1–3` (varies)** — the ported ClipReader is a
   *playback* reader: `pickAt` returns the nearest decoded frame at-or-before
   the target (non-blocking, tolerates a few frames of lag for smooth scrub).
   Acceptable for preview. **Frame-exact decode is the export path's job** —
   Spike C must decode precisely to the target frame, not use the ring-buffer
   best-available.

Decision (user): accept as passed; exact-frame deferred to Spike C.

## Spike B — libass-wasm subtitle layer ⚠️ (highest-risk; integration unproven)

Tried **jassub 2.5.1** (maintained libass→wasm). Two blocking findings:

1. **Architecturally unfit for our single compositor.** jassub *unconditionally*
   `canvas.transferControlToOffscreen()` and renders in a worker via its own
   WebGL/WebGPU. The main thread can't read its pixels → we cannot upload its
   output into our WebGPU frame, and an export pass can't capture it. It only
   works as a DOM overlay stacked on the video — which breaks preview≡render
   (subtitles would be a separate path from the compositor).
2. **Broken in our Electron+Vite renderer.** jassub passes
   `proxy(font => this._getLocalFont(font))` to its worker unconditionally
   (independent of `queryFonts`), and its `abslink` (comlink-style) layer fails
   to proxy that function here → `DataCloneError: ... could not be cloned`. Also
   needed `worker.format: 'es'` + `optimizeDeps.exclude:['jassub']` +
   `include` of its CJS dep `throughput`, and it still doesn't run.

**libass quality itself is not in doubt** (it's what ffmpeg uses today). The real
risk this spike surfaces: **getting libass RGBA *into our compositor* is the
biggest unproven integration.** Viable paths for a focused follow-on:
- **SubtitlesOctopus / libass-wasm@4 JS-blend mode** — posts ImageData to the
  main thread → readable → upload to our overlay texture (the P2 path). Older,
  but emits bitmaps (the property we need).
- **Custom libass-wasm worker** exposing `ass_render_frame` → RGBA we postMessage
  back. Most control, most work.

**Resolution (✅ de-risk met):** Looked at how Phase plans subtitles —
dosmoon-phase `docs/design/02-architecture.md` chose **Canvas 2D rasterisation →
texture**, NOT libass. So subtitles go through the canvas2D→texture overlay path
we already built + proved in Phase 2 (the card overlays). Added `subtitle_cue`
to that renderer (bottom-anchored, `fontsize_pct`/`block_margin_pct`/bold/CJK
font). The subtitle timeline (real `subtitle.compile` output, sample cues incl.
CJK) renders **in the single compositor** — CJK confirmed on screen,
preview≡render + export-ready. 3 headless tests pin `isCanvas2dOverlay` + the
cue resolve + drawOverlayClip so it can't regress.

So: **subtitles = canvas2D→texture (no libass needed for the core path).** jassub
ruled out (display-only + broken here). libass only required for full ASS-tag
fidelity (karaoke `\t`, complex transforms) — a future bitmap-emitting-libass
task, not a blocker.

> Dev gotcha that cost time here: this environment's Vite HMR served **stale
> module bundles** repeatedly (edits not reaching the running window), and an
> early edit landed in a **duplicate** `overlay/canvas2d.ts` while `draw.ts`
> imported `engine/overlay/canvas2d.ts`. Lesson: after non-trivial renderer
> edits, do a full dev restart + clear `node_modules/.vite` rather than trust
> HMR; and watch for path duplication.

## Spike C — WebCodecs export ✅

Path: per output frame, `resolveFrameAt` → `prepareFrame`/`paintPreparedFrame`
(the SAME functions preview uses) → render to an **offscreen** target →
`copyTextureToBuffer` readback → `VideoFrame` from bytes → `VideoEncoder` (avc) →
`mp4-muxer` → bytes handed to main (`ipcMain "vc:writeExport"`) → written under
`user_data/exports/`.

**Key gotcha:** first attempt captured `new VideoFrame(canvas)` from the WebGPU
swapchain → produced **solid green** (zeroed YUV) because WebGPU canvases don't
preserve the drawing buffer. Fix = render to an offscreen `GPUTexture`
(RENDER_ATTACHMENT|COPY_SRC) and read it back; the swapchain is never the export
source. (At 1280 width, `bytesPerRow = 1280*4 = 5120` is already 256-aligned.)

**Result:** valid 300-frame / 10s / ~5.2 Mbps H.264 mp4; extracted frames show
the testsrc2 video + burned frame#/timecode + the CJK subtitle all composited —
**preview≡render confirmed** (same prepare/paint path, verified by frame
extraction). encode + mux + fs-write all work. `avc: { format: "avc" }` (AVCC) +
`mp4-muxer.addVideoChunk(chunk, meta)` is the working combo.

**Three bugs hit + fixed (all verified by frame extraction):**
1. **green frames** — `new VideoFrame(canvas)` from the WebGPU swapchain reads
   nothing (no preserved drawing buffer) → render to an offscreen target +
   `copyTextureToBuffer` instead.
2. **stale/jumping video** — the playback ClipReader returns best-buffered-so-far
   (output frame 30 showed source frame 7). Added `ClipReader.frameAtExact` that
   WAITS for the exact target frame; export uses `prepareFrame(slice, deps, true)`,
   preview keeps the non-blocking path.
3. **~5s per frame** — `frameAtExact` waited for the pump but only trimmed the
   ring buffer AFTER waiting → a full buffer of sub-target frames deadlocked the
   (capacity-bounded) pump until the 3s budget. Fix: trim *inside* the wait loop
   so the pump always has space to decode forward, and wake event-driven on each
   decoded frame (no 4ms poll clamp).

After fixes: export is fast and video tracks output monotonically (output 30 →
src 25, output 270 → src 268, with HOOK/OUTRO cards burned in correctly).
Residual ±2–5 frame offset = `pickAt` at-or-before + the test asset's B-frame /
edit-list cts-vs-burned-counter offset — harmless; true bit-exact decode +
audio mux are documented refinements.

---

## Round verdict ✅

Self-built GPU compositor minimal closed loop **stands**: decode → GPU composite
(video external-texture + canvas2D overlays/subtitle, z-ordered alpha) → the SAME
prepare/paint feeds **preview (swapchain) and export (offscreen→WebCodecs→mp4)**.
The foundation-doc bet (one compositor, preview≡render, self-built on WebGPU +
WebCodecs, ffmpeg demoted) is de-risked. libass not needed for the core subtitle
path. Remaining refinements (not blockers): exact-frame decode for export, audio
mux, full overlay-kind coverage, libass-RGBA only if full ASS fidelity is later
required.
