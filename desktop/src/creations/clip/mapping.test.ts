/**
 * Override-resolution tests — pin the override-wins semantics faithfully ported
 * from clip_tool.py::_effective_* so the Clips-tab detail editor reads exactly
 * what the original Tk workbench (and the render path) would.
 */

import { describe, expect, it } from "vitest";
import {
  parseTimestamp,
  formatTimestamp,
  resolveStartEnd,
  resolveHookText,
  resolveOutroText,
  resolveTitle,
  resolveTags,
  resolveCrop,
} from "./mapping.js";
import type { ClipOverride, HotclipCandidate } from "./types.js";

const CAND: HotclipCandidate = {
  start: "00:00:10.500",
  end: "00:00:25.000",
  duration_sec: 14,
  score: 8,
  hook: "AI hook",
  outro: "AI outro",
  suggested_title: "AI title",
  suggested_hashtags: ["#ai", "#clip"],
};

describe("parseTimestamp", () => {
  it("parses [HH:]MM:SS[.mmm] to seconds", () => {
    expect(parseTimestamp("00:00:10.500")).toBeCloseTo(10.5);
    expect(parseTimestamp("01:02:03")).toBe(3723);
    expect(parseTimestamp("02:05")).toBe(125); // MM:SS
    expect(parseTimestamp("garbage")).toBe(0);
  });
});

describe("formatTimestamp", () => {
  it("formats seconds as HH:MM:SS.mmm and round-trips", () => {
    expect(formatTimestamp(10.5)).toBe("00:00:10.500");
    expect(formatTimestamp(3723)).toBe("01:02:03.000");
    expect(formatTimestamp(-5)).toBe("00:00:00.000"); // clamped
    expect(parseTimestamp(formatTimestamp(125.25))).toBeCloseTo(125.25);
  });
});

describe("resolveStartEnd", () => {
  it("falls back to the candidate timestamps", () => {
    expect(resolveStartEnd(CAND)).toEqual([10.5, 25]);
  });
  it("lets the override win per field", () => {
    const ov: ClipOverride = { start_sec: 12, end_sec: 20 };
    expect(resolveStartEnd(CAND, ov)).toEqual([12, 20]);
    expect(resolveStartEnd(CAND, { start_sec: 12 })).toEqual([12, 25]);
  });
});

describe("resolveHookText / resolveOutroText", () => {
  it("override wins, else the AI line", () => {
    expect(resolveHookText(CAND)).toBe("AI hook");
    expect(resolveHookText(CAND, { hook_text: "mine" })).toBe("mine");
    expect(resolveOutroText(CAND)).toBe("AI outro");
    expect(resolveOutroText(CAND, { outro_text: "bye" })).toBe("bye");
  });
});

describe("resolveTitle", () => {
  it("override wins, else suggested_title", () => {
    expect(resolveTitle(CAND)).toBe("AI title");
    expect(resolveTitle(CAND, { title: "Custom" })).toBe("Custom");
  });
  it("treats an explicitly-empty override as set (key presence wins)", () => {
    // The panel deletes the key on empty input; an empty string present means
    // the user really cleared it, so it must win over the AI value.
    expect(resolveTitle(CAND, { title: "" })).toBe("");
  });
});

describe("resolveTags", () => {
  it("falls back to suggested_hashtags then hashtags", () => {
    expect(resolveTags(CAND)).toEqual(["#ai", "#clip"]);
    const noSuggested: HotclipCandidate = { start: "0", end: "1", hashtags: ["#x"] };
    expect(resolveTags(noSuggested)).toEqual(["#x"]);
    const noTags: HotclipCandidate = { start: "0", end: "1" };
    expect(resolveTags(noTags)).toEqual([]);
  });
  it("splits a string override on whitespace; keeps a list as-is", () => {
    expect(resolveTags(CAND, { hashtags: "#a  #b\n#c" })).toEqual(["#a", "#b", "#c"]);
    expect(resolveTags(CAND, { hashtags: ["#one", "#two"] })).toEqual(["#one", "#two"]);
    expect(resolveTags(CAND, { hashtags: "   " })).toEqual([]);
  });
});

describe("resolveCrop", () => {
  it("returns the override crop_rect, never a fallback", () => {
    expect(resolveCrop()).toBeNull();
    expect(resolveCrop({})).toBeNull();
    const rect = { x: 0.1, y: 0, w: 0.5, h: 1 };
    expect(resolveCrop({ crop_rect: rect })).toBe(rect);
  });
});
