import { describe, it, expect } from "vitest";
import type { FieldSpec } from "@composition/components/fieldSpec.js";
import { readValue, fieldPresent, buildPatch } from "./nestedPatch";

const chapter = () => ({
  kind: "chapter",
  name: "章节",
  modes: { top_strip: true, start_card: false },
  style: {
    top_strip: { bg_color: "#1E40AF", text_color: "#FFFFFF", fontsize: 26 },
    start_card: { title_color: "#FFFFFF", title_fontsize: 40, bg_color: "#0F1B2C" },
  },
});

const flat: FieldSpec = { key: "name", control: "text", labelKey: "x" };
const mode: FieldSpec = { key: "modes.top_strip", path: ["modes", "top_strip"], control: "checkbox", labelKey: "x" };
const stripBg: FieldSpec = { key: "style.top_strip.bg_color", path: ["style", "top_strip", "bg_color"], control: "color", labelKey: "x" };

describe("nestedPatch", () => {
  it("readValue reads flat and nested", () => {
    expect(readValue(chapter(), flat)).toBe("章节");
    expect(readValue(chapter(), mode)).toBe(true);
    expect(readValue(chapter(), stripBg)).toBe("#1E40AF");
  });

  it("fieldPresent detects flat + nested presence and absence", () => {
    expect(fieldPresent(chapter(), stripBg)).toBe(true);
    const missing: FieldSpec = { key: "style.foo.bar", path: ["style", "foo", "bar"], control: "text", labelKey: "x" };
    expect(fieldPresent(chapter(), missing)).toBe(false);
  });

  it("buildPatch on a flat field patches the key", () => {
    expect(buildPatch(chapter(), flat, "new")).toEqual({ name: "new" });
  });

  it("buildPatch on a nested leaf re-sends the whole top-level object, siblings intact", () => {
    const patch = buildPatch(chapter(), stripBg, "#000000");
    // The whole `style` is re-sent so update_component's shallow merge keeps it.
    expect(patch).toEqual({
      style: {
        top_strip: { bg_color: "#000000", text_color: "#FFFFFF", fontsize: 26 },
        start_card: { title_color: "#FFFFFF", title_fontsize: 40, bg_color: "#0F1B2C" },
      },
    });
  });

  it("buildPatch toggling a mode preserves the sibling mode", () => {
    expect(buildPatch(chapter(), mode, false)).toEqual({ modes: { top_strip: false, start_card: false } });
  });

  it("buildPatch does not mutate the source component", () => {
    const c = chapter();
    buildPatch(c, stripBg, "#abcabc");
    expect(c.style.top_strip.bg_color).toBe("#1E40AF");
  });
});
