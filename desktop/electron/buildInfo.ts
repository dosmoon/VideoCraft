/**
 * Build identity — the per-BUILD metadata (build number, git SHA, timestamp)
 * that the release VERSION does not carry (docs/versioning.md). Generated at
 * build time by packaging/generate_build_info.ps1 into a build-info.json shipped
 * beside the app (paths.ts buildInfoPath). The release `version` is NOT in that
 * file — main fills it from package.json via app.getVersion() (single source).
 */

import { readFile } from "node:fs/promises";

/** What the renderer's About card shows. `version` is filled in by main from
 *  app.getVersion(); the rest come from build-info.json (or a dev fallback). */
export interface BuildInfo {
  version: string;
  build: string;
  commit: string;
  builtAt: string;
}

/** The build-time-generated fields — everything except the package.json version. */
export type GeneratedBuildInfo = Omit<BuildInfo, "version">;

/**
 * Read build-info.json. Returns null when it is absent or malformed — the normal
 * case in `pnpm dev` (no build step ran), where main supplies a "dev" fallback
 * instead of failing.
 */
export async function readBuildInfo(path: string): Promise<GeneratedBuildInfo | null> {
  try {
    const parsed = JSON.parse(await readFile(path, "utf-8")) as Partial<GeneratedBuildInfo>;
    if (typeof parsed.build !== "string") return null;
    return {
      build: parsed.build,
      commit: typeof parsed.commit === "string" ? parsed.commit : "",
      builtAt: typeof parsed.builtAt === "string" ? parsed.builtAt : "",
    };
  } catch {
    return null;
  }
}
