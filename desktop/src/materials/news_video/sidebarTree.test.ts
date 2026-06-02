import { describe, expect, it } from "vitest";

import type { SlotState } from "./model";
import { SLOT_NEWS_CONTEXT, SLOT_SOURCE, SLOT_SUBTITLES } from "./model";
import { buildMaterialTree } from "./sidebarTree";

const slot = (id: string, isFilled: boolean): SlotState => ({
  slotId: id as SlotState["slotId"],
  isLocked: false,
  isFilled,
});

describe("buildMaterialTree", () => {
  it("builds the three slots; subtitles nests langs, langs nest analyses", () => {
    const tree = buildMaterialTree({
      readiness: {
        [SLOT_SOURCE]: slot(SLOT_SOURCE, true),
        [SLOT_NEWS_CONTEXT]: slot(SLOT_NEWS_CONTEXT, false),
        [SLOT_SUBTITLES]: slot(SLOT_SUBTITLES, true),
      },
      langs: ["zh", "en"],
      analysesByLang: { zh: ["analysis", "hotclips"], en: [] },
    });

    expect(tree.map((n) => n.id)).toEqual([SLOT_SOURCE, SLOT_NEWS_CONTEXT, SLOT_SUBTITLES]);
    expect(tree[0]!.slot?.isFilled).toBe(true);

    const subs = tree[2]!;
    expect(subs.children.map((n) => n.id)).toEqual(["lang:zh", "lang:en"]);

    const zh = subs.children[0]!;
    expect(zh.kind).toBe("lang");
    expect(zh.lang).toBe("zh");
    expect(zh.children.map((n) => n.id)).toEqual(["analysis:zh:analysis", "analysis:zh:hotclips"]);
    expect(zh.children[0]!.analysisKind).toBe("analysis");

    expect(subs.children[1]!.children).toEqual([]); // en has no analyses
  });

  it("no langs → subtitles has no children", () => {
    const tree = buildMaterialTree({
      readiness: {
        [SLOT_SOURCE]: slot(SLOT_SOURCE, false),
        [SLOT_NEWS_CONTEXT]: slot(SLOT_NEWS_CONTEXT, false),
        [SLOT_SUBTITLES]: slot(SLOT_SUBTITLES, false),
      },
      langs: [],
      analysesByLang: {},
    });
    expect(tree[2]!.children).toEqual([]);
  });
});
