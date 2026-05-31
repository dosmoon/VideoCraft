import { describe, it, expect } from "vitest";
import { validateTimeline, type Clip, type Track } from "../../composition/ir.js";
import { resolveAudioSegments } from "../../composition/compositor/resolveAudio.js";
import type { SourceCue } from "../../composition/components/index.js";
import {
  newsDeskSubtitleToInstance,
  newsDeskImageWatermarkToInstance,
  newsDeskChapterToInstance,
} from "./mapping.js";
import { buildNewsDeskTimeline } from "./assemble.js";
import type {
  NewsDeskChapterConfig,
  NewsDeskImageWatermarkConfig,
  NewsDeskSubtitleConfig,
} from "./types.js";

function clipsOf(track: Track): Clip[] {
  return track.children.filter((c): c is Clip => c.type === "clip");
}

function subtitleConfig(over: Partial<NewsDeskSubtitleConfig> = {}): NewsDeskSubtitleConfig {
  return {
    kind: "subtitle",
    enabled: true,
    srt_path: "source-subtitles.en.srt",
    position: "bottom",
    block_margin_pct: 9,
    fontsize_pct: 0.026,
    color: "#FFFF00",
    is_chinese: true,
    stroke_color: "#000000",
    stroke_pct: 0.002,
    bg_enabled: true,
    bg_color: "#000000",
    bg_opacity: 55,
    ...over,
  };
}

function chapterConfig(over: Partial<NewsDeskChapterConfig> = {}): NewsDeskChapterConfig {
  return {
    kind: "chapter",
    enabled: true,
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
    schedule: [
      { start_sec: 0, end_sec: 30, title: "Intro", refined: "the intro", key_points: [] },
      { start_sec: 30, end_sec: 90, title: "Body", refined: "the body", key_points: [] },
    ],
    ...over,
  };
}

// --- conversions: the int% -> fraction normalisation ----------------------

describe("news_desk conversions onto the shared canonical schema", () => {
  it("subtitle: integer block_margin_pct becomes a fraction; bg_enabled folds into opacity", () => {
    const inst = newsDeskSubtitleToInstance(subtitleConfig({ block_margin_pct: 9 }));
    expect(inst.blockMarginPct).toBeCloseTo(0.09);
    expect(inst.bgOpacity).toBe(55);
    // canonical-only fields news_desk doesn't expose get neutral defaults
    expect(inst.bold).toBe(false);
    expect(inst.bgPaddingXPct).toBe(0);

    const off = newsDeskSubtitleToInstance(subtitleConfig({ bg_enabled: false, bg_opacity: 55 }));
    expect(off.bgOpacity).toBe(0);
  });

  it("image watermark: scale_pct/100 clamps to [0.02, 0.50]", () => {
    const cfg = (scale: number): NewsDeskImageWatermarkConfig => ({
      kind: "image_watermark",
      enabled: true,
      image_path: "logo.png",
      scale_pct: scale,
      opacity: 100,
      position: "top-right",
      margin_x_pct: 2,
      margin_y_pct: 2,
    });
    expect(newsDeskImageWatermarkToInstance(cfg(15)).imageScale).toBeCloseTo(0.15);
    expect(newsDeskImageWatermarkToInstance(cfg(80)).imageScale).toBe(0.5); // clamped
    expect(newsDeskImageWatermarkToInstance(cfg(1)).imageScale).toBe(0.02); // clamped
    expect(newsDeskImageWatermarkToInstance(cfg(15)).marginXPct).toBeCloseTo(0.02);
  });

  it("chapter: schedule + nested style map onto the canonical instance", () => {
    const inst = newsDeskChapterToInstance(chapterConfig());
    expect(inst.schedule).toHaveLength(2);
    expect(inst.schedule[0]).toEqual({ startSec: 0, endSec: 30, title: "Intro", refined: "the intro", keyPoints: [] });
    expect(inst.style.topStrip.bgColor).toBe("#1E40AF");
    expect(inst.style.startCard.durationSec).toBe(6);
  });
});

// --- assembly over the full video (identity TimeMap) ----------------------

describe("buildNewsDeskTimeline", () => {
  const cuesBySrtPath: Record<string, SourceCue[]> = {
    "source-subtitles.en.srt": [
      { sourceStart: 5, sourceEnd: 8, text: "headline" },
      { sourceStart: 40, sourceEnd: 43, text: "detail" },
    ],
  };

  it("assembles a validated timeline over the full source (no cut)", () => {
    const timeline = buildNewsDeskTimeline({
      components: [subtitleConfig(), chapterConfig()],
      durationSec: 120,
      cuesBySrtPath,
      mediaRef: "source.mp4",
    });
    expect(timeline.durationSec).toBe(120);
    expect(validateTimeline(timeline, { sourceDurations: { "source.mp4": 120 } })).toEqual([]);

    const videoClip = clipsOf(timeline.tracks[0]!)[0]!;
    expect(videoClip.sourceStart).toBe(0);
    expect(videoClip.durationSec).toBe(120);
  });

  // Regression guard: news_desk must emit a full-source audio track at unity
  // gain (no cut). Mirrors the clip lost-edit guard — see task.md 续16.
  it("emits a full-source audio track (lost-edit guard)", () => {
    const timeline = buildNewsDeskTimeline({
      components: [subtitleConfig()],
      durationSec: 120,
      cuesBySrtPath,
      mediaRef: "source.mp4",
    });
    expect(timeline.tracks[1]!.kind).toBe("audio");

    const segments = resolveAudioSegments(timeline);
    expect(segments).toHaveLength(1);
    expect(segments[0]).toMatchObject({
      mediaRef: "source.mp4",
      outStartSec: 0,
      outEndSec: 120,
      sourceStartSec: 0, // full source, no cut
      gain: 1,
    });
  });

  it("under identity TimeMap, source-anchored times are output times", () => {
    const timeline = buildNewsDeskTimeline({
      components: [subtitleConfig()],
      durationSec: 120,
      cuesBySrtPath,
      mediaRef: "source.mp4",
    });
    // tracks = [video, audio, ...overlays]; first overlay is at index 2.
    const subTrack = timeline.tracks[2]!;
    const cues = clipsOf(subTrack);
    expect(cues.map((c) => c.data.text)).toEqual(["headline", "detail"]);
    // first cue at source 5 -> output 5, so leading gap is 5s
    expect((subTrack.children[0] as { durationSec: number }).durationSec).toBe(5);
  });

  it("chapter with both layers emits two overlay tracks (strip + hero card)", () => {
    const timeline = buildNewsDeskTimeline({
      components: [chapterConfig({ modes: { top_strip: true, start_card: true } })],
      durationSec: 120,
      cuesBySrtPath,
      mediaRef: "source.mp4",
    });
    // video + audio + strip track + hero-card track
    expect(timeline.tracks).toHaveLength(4);
    const stripKinds = clipsOf(timeline.tracks[2]!).map((c) => c.kind);
    const cardKinds = clipsOf(timeline.tracks[3]!).map((c) => c.kind);
    expect(stripKinds).toEqual(["topic_strip", "topic_strip"]);
    expect(cardKinds).toEqual(["chapter_hero_card", "chapter_hero_card"]);
    // hero card capped at 6s within each chapter window
    expect(clipsOf(timeline.tracks[3]!)[0]!.durationSec).toBe(6);
    expect(validateTimeline(timeline, { sourceDurations: { "source.mp4": 120 } })).toEqual([]);
  });

  it("proves dedup: the same canonical subtitle component serves both plugins", () => {
    // news_desk subtitle config -> canonical SubtitleInstance -> shared component
    const inst = newsDeskSubtitleToInstance(subtitleConfig());
    expect(inst.fontsizePct).toBe(0.026); // news_desk value, canonical field
    expect(inst.color).toBe("#FFFF00");
  });

  it("tolerates a preset chapter with no schedule (no throw → preview stays live)", () => {
    // A saved preset drops per-project content, so an applied chapter has no
    // `schedule`. buildNewsDeskTimeline must not throw — a throw took the whole
    // timeline (and the preview canvas) down, black-screening on preset apply.
    const ch = chapterConfig();
    delete (ch as { schedule?: unknown }).schedule;
    const timeline = buildNewsDeskTimeline({
      components: [ch],
      durationSec: 120,
      cuesBySrtPath: {},
      mediaRef: "source.mp4",
    });
    // The video + audio tracks always build; the schedule-less chapter just
    // contributes no overlay clips (its rows get imported per-instance later).
    expect(timeline.tracks[0]!.kind).toBe("video");
    expect(clipsOf(timeline.tracks[0]!).length).toBe(1);
    expect(resolveAudioSegments(timeline).length).toBe(1);
    expect(validateTimeline(timeline, { sourceDurations: { "source.mp4": 120 } })).toEqual([]);
  });
});
