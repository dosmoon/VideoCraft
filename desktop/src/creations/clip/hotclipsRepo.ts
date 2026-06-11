/**
 * Hotclips data layer for the clip workbench (ADR-0008 TS port of
 * `src/creations/clip/candidates.py`).
 *
 * Owns the per-instance snapshot of upstream hotclips + SRT (snapshot principle,
 * ADR-0003): copy-once into the creation instance dir on first access, then read
 * ONLY from the snapshot so upstream regeneration can't corrupt this instance's
 * renders. All filesystem access goes through the injected `Fs` (Electron main).
 *
 * Upstream material access is abstracted behind `MaterialBridge` — in Phase A
 * the production binding resolves the bound material's subtitles dir via a bridge
 * RPC (the exact RPC is decided at workbench wiring, A4); in Phase B it is the TS
 * material model (materials/news_video/paths.ts). Keeping it injected makes the
 * snapshot logic unit-testable and defers the bridge-RPC shape.
 */

import type { Fs } from "../../renderer/ipc/fs";

/** Upstream (bound material) accessor. Phase A: bridge RPC; Phase B: TS model. */
export interface MaterialBridge {
  /** Abs path of the material's subtitles dir (where `<lang>.hotclips.json` and
   *  `<lang>.srt` live). */
  subtitlesDir(): Promise<string>;
}

const SNAPSHOT_RE = /^source-hotclips\.([^.]+)\.json$/;

export class HotclipsRepo {
  constructor(
    private readonly fs: Fs,
    private readonly instanceDir: string,
    private readonly bridge: MaterialBridge,
  ) {}

  hotclipsSnapshotPath(lang: string): string {
    return `${this.instanceDir}/source-hotclips.${lang}.json`;
  }
  srtSnapshotPath(lang: string): string {
    return `${this.instanceDir}/source-subtitles.${lang}.srt`;
  }

  /** Snapshot upstream hotclips + SRT into the instance dir if not yet present.
   *  Returns the hotclips snapshot path, or null when upstream hotclips is
   *  missing AND no prior snapshot exists. SRT snapshot is best-effort. */
  async ensureSnapshot(lang: string): Promise<string | null> {
    const subsDir = await this.bridge.subtitlesDir();

    const hotSnap = this.hotclipsSnapshotPath(lang);
    if (!(await this.fs.stat(hotSnap)).exists) {
      const upstream = `${subsDir}/${lang}.hotclips.json`;
      if (!(await this.fs.stat(upstream)).exists) return null;
      await this.fs.copy(upstream, hotSnap);
    }

    const srtSnap = this.srtSnapshotPath(lang);
    if (!(await this.fs.stat(srtSnap)).exists) {
      const upstreamSrt = `${subsDir}/${lang}.srt`;
      if ((await this.fs.stat(upstreamSrt)).exists) {
        await this.fs.copy(upstreamSrt, srtSnap);
      }
    }
    return hotSnap;
  }

  /** Languages already snapshotted into THIS instance (`source-hotclips.<lang>.json`),
   *  sorted. A snapshot's presence means the instance's candidate language was
   *  already decided — used to keep existing instances pinned when new upstream
   *  languages appear. */
  async listSnapshotLangs(): Promise<string[]> {
    const langs = new Set<string>();
    for (const e of await this.safeList(this.instanceDir)) {
      const m = SNAPSHOT_RE.exec(e.name);
      if (m) langs.add(m[1]!);
    }
    return [...langs].sort();
  }

  /** Languages with hotclips — union of instance snapshots and upstream
   *  `<lang>.hotclips.json`, sorted. */
  async listAvailableLangs(): Promise<string[]> {
    const langs = new Set<string>();
    for (const e of await this.safeList(this.instanceDir)) {
      const m = SNAPSHOT_RE.exec(e.name);
      if (m) langs.add(m[1]!);
    }
    const subsDir = await this.bridge.subtitlesDir();
    for (const e of await this.safeList(subsDir)) {
      if (e.name.endsWith(".hotclips.json")) langs.add(e.name.slice(0, -".hotclips.json".length));
    }
    return [...langs].sort();
  }

  /** Languages with an SRT — union of instance SRT snapshots and upstream
   *  `<lang>.srt`, sorted. Broader than listAvailableLangs (no hotclips needed). */
  async listSubtitleLangs(): Promise<string[]> {
    const langs = new Set<string>();
    for (const e of await this.safeList(this.instanceDir)) {
      if (e.name.startsWith("source-subtitles.") && e.name.endsWith(".srt")) {
        langs.add(e.name.slice("source-subtitles.".length, -".srt".length));
      }
    }
    const subsDir = await this.bridge.subtitlesDir();
    for (const e of await this.safeList(subsDir)) {
      if (e.name.endsWith(".srt")) langs.add(e.name.slice(0, -".srt".length));
    }
    return [...langs].sort();
  }

  /** Parse the snapshot hotclips JSON. null when missing/malformed. */
  async loadHotclips(lang: string): Promise<Record<string, unknown> | null> {
    const path = await this.ensureSnapshot(lang);
    if (path === null) return null;
    const data = await this.fs.readJson<Record<string, unknown>>(path);
    return data && typeof data === "object" ? data : null;
  }

  /** The instance's SRT snapshot path, falling back to upstream only when no
   *  snapshot exists yet (rare — ensureSnapshot fires on every language load). */
  async resolveSourceSrt(lang: string): Promise<string | null> {
    if (!lang) return null;
    const snap = this.srtSnapshotPath(lang);
    if ((await this.fs.stat(snap)).exists) return snap;
    const subsDir = await this.bridge.subtitlesDir();
    const upstream = `${subsDir}/${lang}.srt`;
    return (await this.fs.stat(upstream)).exists ? upstream : null;
  }

  private async safeList(dir: string): Promise<{ name: string; isDir: boolean }[]> {
    try {
      return await this.fs.list(dir);
    } catch {
      return [];
    }
  }
}
