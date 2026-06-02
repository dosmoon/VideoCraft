/**
 * News-video sidebar node tree (ADR-0008 B3.2 sidebar-driven redesign).
 *
 * Pure model: given an instance's resolved data (slot readiness + subtitle
 * languages + per-language analysis artifacts), produce the tree of selectable
 * nodes the Hub renders. Each node carries the FACTS the renderer needs (slot
 * state, lang code, analysis kind/artifact); rendering (icon, tr() label, inline
 * action buttons) lives in the sidebar component, keyed off `kind`. Selecting a
 * node (by `id`) drives the right-panel detail view.
 *
 *   source · news_context · subtitles      (the three slots)
 *     subtitles
 *       └ lang:<iso>                        (one per subtitle language)
 *           └ analysis:<iso>:<kind>         (one per existing analysis artifact)
 */

import type { SlotState } from "./model";
import { SLOT_NEWS_CONTEXT, SLOT_SOURCE, SLOT_SUBTITLES, type SlotId } from "./model";

export type MaterialNodeKind = "source" | "news_context" | "subtitles" | "lang" | "analysis";

export interface MaterialNode {
  /** Stable selection key: "source" | "news_context" | "subtitles" |
   * "lang:<iso>" | "analysis:<iso>:<kind>". */
  id: string;
  kind: MaterialNodeKind;
  slot?: SlotState; // source / news_context / subtitles
  lang?: string; // lang / analysis
  analysisKind?: string; // analysis — renderer looks up icon/label via analysisType()
  children: MaterialNode[];
}

export interface MaterialTreeInput {
  readiness: Record<SlotId, SlotState>;
  langs: string[]; // subtitle languages present (sorted)
  analysesByLang: Record<string, string[]>; // lang → existing analysis kinds (registry order)
}

/** Build the slot-level node tree for one news_video instance (pure). */
export function buildMaterialTree(input: MaterialTreeInput): MaterialNode[] {
  const { readiness, langs, analysesByLang } = input;

  const langNodes: MaterialNode[] = langs.map((l) => ({
    id: `lang:${l}`,
    kind: "lang",
    lang: l,
    children: (analysesByLang[l] ?? []).map((kind) => ({
      id: `analysis:${l}:${kind}`,
      kind: "analysis",
      lang: l,
      analysisKind: kind,
      children: [],
    })),
  }));

  return [
    { id: SLOT_SOURCE, kind: "source", slot: readiness[SLOT_SOURCE], children: [] },
    { id: SLOT_NEWS_CONTEXT, kind: "news_context", slot: readiness[SLOT_NEWS_CONTEXT], children: [] },
    { id: SLOT_SUBTITLES, kind: "subtitles", slot: readiness[SLOT_SUBTITLES], children: langNodes },
  ];
}
