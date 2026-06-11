/**
 * Clip preview-data builder (ADR-0008 B4 TS port of `src/creations/clip/preview.py`).
 *
 * Pure logic: given the loaded config owner and a HotclipsRepo bound to the
 * creation's instance dir + the upstream material, produce exactly the shape the
 * old preview_provider returned (the workbench's RawPreviewData) — candidates +
 * selected index + per-language snapshot SRTs + the selected candidate's override.
 *
 * Snapshot principle ([[project_snapshot_principle]]): candidates + SRT come from
 * the instance's own snapshot via the repo, never live upstream. The bound-material
 * resolution (repo construction) lives in clientBackend (it needs an RPC); this
 * module is injectable so vitest can drive it with an in-memory repo.
 */

import type { ComponentDict } from "./componentDefs";
import type { ClipConfigOwner } from "./configOwner";
import type { HotclipsRepo } from "./hotclipsRepo";

export interface ClipPreviewResult {
  lang: string;
  candidates: Record<string, unknown>[];
  selectedIndex: number;
  subtitlePath: string | null;
  subtitlePaths: Record<string, string>;
  override: ComponentDict | null;
  availableLangs: string[];
  subtitleLangs: string[];
  /** True when several hotclips languages exist and the instance hasn't picked
   *  one yet — the workbench must ask the user (candidate language is a
   *  one-time human decision; it is never inferred from the source language). */
  needsLangChoice: boolean;
}

export function emptyClipPreview(lang: string): ClipPreviewResult {
  return {
    lang,
    candidates: [],
    selectedIndex: 0,
    subtitlePath: null,
    subtitlePaths: {},
    override: null,
    availableLangs: [],
    subtitleLangs: [],
    needsLangChoice: false,
  };
}

/** Build the preview payload for a bound clip creation. `repo` must already be
 *  bound to this instance's dir + the upstream material's subtitles dir. */
export async function buildClipPreview(
  owner: ClipConfigOwner,
  repo: HotclipsRepo,
): Promise<ClipPreviewResult> {
  const avail = await repo.listAvailableLangs();

  // Candidate-language resolution. The language is a one-time HUMAN decision —
  // never derived from the source language (translated subtitles exist exactly
  // to produce clips in another language):
  //   1. config source_subtitle set → use it (locked)
  //   2. an instance snapshot exists → that language was already decided; pin it
  //      so new upstream languages can't silently flip this instance
  //   3. exactly one hotclips language upstream → nothing to choose; take it
  //   4. several languages, none decided → ask the user (needsLangChoice)
  let lang = owner.sourceSubtitle;
  let needsLangChoice = false;
  if (!lang) {
    const snaps = await repo.listSnapshotLangs();
    if (snaps.length === 1) lang = snaps[0]!;
    else if (snaps.length === 0 && avail.length <= 1) lang = avail[0] ?? "";
    else needsLangChoice = true;
  }

  let candidates: Record<string, unknown>[] = [];
  if (!needsLangChoice && lang) {
    const data = (await repo.loadHotclips(lang)) ?? {};
    const rawClips = (data as { clips?: unknown }).clips;
    candidates = Array.isArray(rawClips)
      ? rawClips.filter((c): c is Record<string, unknown> => !!c && typeof c === "object")
      : [];
  }

  let sel = owner.selectedClipIndices[0] ?? 0;
  if (sel < 0 || sel >= candidates.length) sel = 0;

  // Snapshot every SUBTITLE language's SRT so bilingual clips work: each subtitle
  // component resolves its own language against this map (subtitle langs ≠
  // candidate/hotclip langs — a video can have en+zh subs but only zh hotclips).
  const subLangs = await repo.listSubtitleLangs();
  const subPaths: Record<string, string> = {};
  for (const l of subLangs) {
    const p = await repo.resolveSourceSrt(l);
    if (p) subPaths[l] = p;
  }

  return {
    lang,
    candidates,
    selectedIndex: sel,
    subtitlePath: subPaths[lang] ?? null,
    subtitlePaths: subPaths,
    override: owner.clipsOverrides[String(sel)] ?? null,
    availableLangs: avail,
    subtitleLangs: subLangs,
    needsLangChoice,
  };
}
