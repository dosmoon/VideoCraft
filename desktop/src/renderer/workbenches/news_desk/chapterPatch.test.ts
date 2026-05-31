/**
 * Guards the chapter patch builders: editing one nested field must re-send the
 * WHOLE nested object so creation.update_component's shallow merge doesn't drop
 * the sibling (the exact trap behind nested-config editing).
 */

import type { Component } from "../../ipc/client";
import { patchMode, patchStrip, patchCard, readStrip, readCard } from "./chapterPatch";

function chapter(over: Record<string, unknown> = {}): Component {
  return {
    id: "chap",
    kind: "chapter",
    modes: { top_strip: true, start_card: false },
    style: {
      top_strip: { bg_color: "#1E40AF", text_color: "#FFFFFF", fontsize: 26 },
      start_card: {
        title_color: "#FFFFFF",
        title_fontsize: 40,
        body_color: "#E5E7EB",
        body_fontsize: 22,
        bg_color: "#0F1B2C",
        bg_opacity: 55,
        accent_color: "#DC2626",
        duration_sec: 6,
      },
    },
    ...over,
  };
}

describe("chapter patch builders", () => {
  it("patchMode toggles one mode, preserves the other", () => {
    const p = patchMode(chapter(), "start_card", true) as { modes: { top_strip: boolean; start_card: boolean } };
    expect(p.modes).toEqual({ top_strip: true, start_card: true });
  });

  it("patchStrip changes a strip field and keeps start_card intact", () => {
    const p = patchStrip(chapter(), "bg_color", "#000000") as {
      style: { top_strip: { bg_color: string }; start_card: { title_color: string } };
    };
    expect(p.style.top_strip.bg_color).toBe("#000000");
    // start_card must survive (shallow-merge would drop it if we sent only top_strip).
    expect(p.style.start_card.title_color).toBe("#FFFFFF");
  });

  it("patchCard changes a card field and keeps top_strip intact", () => {
    const p = patchCard(chapter(), "title_fontsize", 64) as {
      style: { top_strip: { bg_color: string }; start_card: { title_fontsize: number } };
    };
    expect(p.style.start_card.title_fontsize).toBe(64);
    expect(p.style.top_strip.bg_color).toBe("#1E40AF");
  });

  it("fills defaults when the component's style is partial/empty", () => {
    const bare = { id: "chap", kind: "chapter" } as Component;
    expect(readStrip(bare).bg_color).toBe("#1E40AF");
    expect(readCard(bare).duration_sec).toBe(6);
    // A patch off a bare component still emits a complete nested object.
    const p = patchCard(bare, "bg_opacity", 80) as { style: { start_card: StartCardLike } };
    expect(p.style.start_card.bg_opacity).toBe(80);
    expect(p.style.start_card.title_color).toBe("#FFFFFF");
  });
});

interface StartCardLike {
  bg_opacity: number;
  title_color: string;
}
