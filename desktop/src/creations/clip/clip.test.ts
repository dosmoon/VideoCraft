import { describe, it, expect } from "vitest";
import { validateTimeline, type Clip, type Track } from "../../composition/ir.js";
import { resolveAudioSegments } from "../../composition/compositor/resolveAudio.js";
import type { SourceCue } from "../../composition/components/index.js";
import {
  parseTimestamp,
  resolveStartEnd,
  clipSubtitleToInstance,
  stackSubtitleMargins,
} from "./mapping.js";
import { buildClipTimeline } from "./assemble.js";
import type {
  ClipCardConfig,
  ClipDubbingConfig,
  ClipSubtitleConfig,
  ClipTextWatermarkConfig,
  HotclipCandidate,
} from "./types.js";

function dubbingConfig(over: Partial<ClipDubbingConfig> = {}): ClipDubbingConfig {
  return {
    kind: "clip_dubbing",
    enabled: true,
    audio_path: "source-dub.en.mp3",
    gain_db: 0,
    source_gain_db: 0,
    offset_sec: 0,
    mode: "replace",
    ...over,
  };
}

function subtitleConfig(over: Partial<ClipSubtitleConfig> = {}): ClipSubtitleConfig {
  return {
    kind: "clip_subtitle",
    enabled: true,
    language: "en",
    fontsize_pct: 0.05,
    color: "#FFFFFF",
    bold: false,
    is_chinese: false,
    bg_color: "#000000",
    bg_opacity: 0,
    bg_padding_x_pct: 0,
    stroke_color: "#000000",
    stroke_pct: 0.002,
    position: "bottom",
    block_margin_pct: 0.09,
    ...over,
  };
}

function clipsOf(track: Track): Clip[] {
  return track.children.filter((c): c is Clip => c.type === "clip");
}

// --- timestamp + window ---------------------------------------------------

describe("parseTimestamp", () => {
  it("parses [HH:]MM:SS[.mmm]", () => {
    expect(parseTimestamp("00:01:30")).toBe(90);
    expect(parseTimestamp("1:02:03")).toBe(3723);
    expect(parseTimestamp("00:00:02.500")).toBe(2.5);
    expect(parseTimestamp("garbage")).toBe(0);
  });
});

describe("resolveStartEnd", () => {
  const candidate: HotclipCandidate = { start: "00:01:00", end: "00:01:30" };
  it("uses candidate timestamps by default", () => {
    expect(resolveStartEnd(candidate)).toEqual([60, 90]);
  });
  it("lets an override win per field", () => {
    expect(resolveStartEnd(candidate, { start_sec: 65 })).toEqual([65, 90]);
  });
});

// --- adapters + stacking --------------------------------------------------

describe("clipSubtitleToInstance", () => {
  it("renames snake_case config to the canonical camelCase instance", () => {
    const inst = clipSubtitleToInstance(subtitleConfig({ color: "#FFFF00", block_margin_pct: 0.12 }));
    expect(inst.color).toBe("#FFFF00");
    expect(inst.blockMarginPct).toBe(0.12);
    expect(inst.fontsizePct).toBe(0.05);
  });
});

describe("stackSubtitleMargins", () => {
  it("stacks same-position renderable subtitles in order", () => {
    const a = clipSubtitleToInstance(subtitleConfig({ block_margin_pct: 0.09 }));
    const b = clipSubtitleToInstance(subtitleConfig({ block_margin_pct: 0.09 }));
    const c = clipSubtitleToInstance(subtitleConfig({ position: "top", block_margin_pct: 0.05 }));
    stackSubtitleMargins([
      { instance: a, hasCues: true },
      { instance: b, hasCues: true },
      { instance: c, hasCues: true },
    ]);
    expect(a.blockMarginPct).toBe(0.09); // first at bottom
    expect(b.blockMarginPct).toBeCloseTo(0.13); // second at bottom: +0.04
    expect(c.blockMarginPct).toBe(0.05); // alone at top
  });

  it("ignores disabled or cue-less subtitles when stacking", () => {
    const a = clipSubtitleToInstance(subtitleConfig({ block_margin_pct: 0.09 }));
    const b = clipSubtitleToInstance(subtitleConfig({ block_margin_pct: 0.09 }));
    stackSubtitleMargins([
      { instance: a, hasCues: false },
      { instance: b, hasCues: true },
    ]);
    expect(b.blockMarginPct).toBe(0.09); // b is the first renderable one
  });
});

// --- full assembly --------------------------------------------------------

describe("buildClipTimeline", () => {
  const candidate: HotclipCandidate = {
    start: "00:01:00",
    end: "00:01:30",
    hook: "wait for it",
    outro: "follow for more",
  };
  // Source-time SRT: one cue inside the window, one outside.
  const srtByLang: Record<string, SourceCue[]> = {
    en: [
      { sourceStart: 65, sourceEnd: 67, text: "inside" },
      { sourceStart: 200, sourceEnd: 202, text: "outside" },
    ],
  };

  const textWm: ClipTextWatermarkConfig = {
    kind: "clip_text_watermark",
    enabled: true,
    text: "@channel",
    text_fontsize_pct: 0.033,
    text_color: "#FFFFFF",
    text_opacity: 70,
    position: "top-right",
    margin_x_pct: 0.025,
    margin_y_pct: 0.025,
  };
  const hookCardCfg: ClipCardConfig = {
    kind: "clip_hook_card",
    enabled: true,
    text: "", // empty -> filled from candidate.hook
    font: "Microsoft YaHei",
    size_pct: 0.05,
    color: "#FFFFFF",
    bg_color: "#000000",
    bg_opacity: 70,
    stroke_color: "#000000",
    stroke_pct: 0.003,
    box_padding_pct: 0.012,
    position: "upper-third",
    duration_sec: 5,
  };

  it("assembles a validated multi-track OTIO timeline", () => {
    const timeline = buildClipTimeline({
      components: [subtitleConfig(), textWm, hookCardCfg],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
    });

    expect(timeline.durationSec).toBe(30);
    expect(validateTimeline(timeline, { sourceDurations: { "source.mp4": 600 } })).toEqual([]);

    // Track 0 = video; the rest are overlays.
    expect(timeline.tracks[0]!.kind).toBe("video");
    const videoClip = clipsOf(timeline.tracks[0]!)[0]!;
    expect(videoClip.sourceStart).toBe(60);
    expect(videoClip.durationSec).toBe(30);
  });

  it("sets crop on the video clip when a reframe rect is given (else omits it)", () => {
    const base = { components: [subtitleConfig()], candidate, srtByLang, mediaRef: "source.mp4" };
    // Default: no crop on the video clip (passthrough/letterbox).
    expect(clipsOf(buildClipTimeline(base).tracks[0]!)[0]!.crop).toBeUndefined();
    // Reframe: the rect rides on the video clip; the audio clip never carries one.
    const crop = { x: 0.2, y: 0, w: 0.6, h: 1 };
    const reframed = buildClipTimeline({ ...base, cropRect: crop });
    expect(clipsOf(reframed.tracks[0]!)[0]!.crop).toEqual(crop);
    expect(clipsOf(reframed.tracks[1]!)[0]!.crop).toBeUndefined();
    expect(validateTimeline(reframed, { sourceDurations: { "source.mp4": 600 } })).toEqual([]);
  });

  // Regression guard: the clip assembler MUST emit an audio track windowed to
  // the candidate. This exact edit was lost across a git-checkout and shipped
  // green (typecheck + tests passed) because nothing asserted the audio track
  // existed — preview/export were silently mute. See task.md 续16 + memory
  // feedback_restored_files_lost_edits.
  it("emits an audio track over the candidate window (lost-edit guard)", () => {
    const timeline = buildClipTimeline({
      components: [subtitleConfig()],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
    });
    expect(timeline.tracks[1]!.kind).toBe("audio");

    const segments = resolveAudioSegments(timeline);
    expect(segments).toHaveLength(1);
    expect(segments[0]).toMatchObject({
      mediaRef: "source.mp4",
      outStartSec: 0,
      outEndSec: 30,
      sourceStartSec: 60, // candidate starts at 00:01:00
      gain: 1, // 0 dB = unity
    });
  });

  // Dubbing: the dub file is full-source aligned, so each candidate slices the
  // SAME window (sourceStart = the candidate's cut start) as the source audio.
  it("dub replace: swaps the source audio for the dub track, windowed to the candidate", () => {
    const timeline = buildClipTimeline({
      components: [subtitleConfig(), dubbingConfig({ mode: "replace" })],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
      dubbingAudioRef: "dub.mp3",
    });
    const segments = resolveAudioSegments(timeline);
    expect(segments).toHaveLength(1);
    expect(segments[0]).toMatchObject({
      mediaRef: "dub.mp3",
      outStartSec: 0,
      outEndSec: 30,
      sourceStartSec: 60, // same candidate window as the source audio
      gain: 1,
    });
    expect(validateTimeline(timeline, { sourceDurations: { "source.mp4": 600, "dub.mp3": 600 } })).toEqual([]);
  });

  it("dub mix: keeps the ducked source + adds the dub track, both windowed", () => {
    const timeline = buildClipTimeline({
      components: [dubbingConfig({ mode: "mix", gain_db: -3, source_gain_db: -10 })],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
      dubbingAudioRef: "dub.mp3",
    });
    const segments = resolveAudioSegments(timeline);
    expect(segments.map((s) => s.mediaRef)).toEqual(["source.mp4", "dub.mp3"]);
    expect(segments.every((s) => s.sourceStartSec === 60)).toBe(true);
    expect(segments[0]!.gain).toBeCloseTo(Math.pow(10, -10 / 20));
    expect(segments[1]!.gain).toBeCloseTo(Math.pow(10, -3 / 20));
  });

  it("dub offset: delays the dub via a leading gap; track total stays the window", () => {
    const timeline = buildClipTimeline({
      components: [dubbingConfig({ mode: "replace", offset_sec: 5 })],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
      dubbingAudioRef: "dub.mp3",
    });
    expect(timeline.durationSec).toBe(30);
    const seg = resolveAudioSegments(timeline)[0]!;
    expect(seg).toMatchObject({ mediaRef: "dub.mp3", outStartSec: 5, outEndSec: 30, sourceStartSec: 60 });
  });

  it("disabled or unresolved dub falls back to the source audio", () => {
    const disabled = buildClipTimeline({
      components: [dubbingConfig({ enabled: false })],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
      dubbingAudioRef: "dub.mp3",
    });
    expect(resolveAudioSegments(disabled)[0]!.mediaRef).toBe("source.mp4");

    const noRef = buildClipTimeline({
      components: [dubbingConfig()],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
    });
    expect(resolveAudioSegments(noRef)[0]!.mediaRef).toBe("source.mp4");
  });

  it("ripples the in-window SRT cue and drops the out-of-window one", () => {
    const timeline = buildClipTimeline({
      components: [subtitleConfig()],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
    });
    // tracks = [video, audio, ...overlays]; first overlay is at index 2.
    const subTrack = timeline.tracks[2]!;
    const cues = clipsOf(subTrack);
    expect(cues).toHaveLength(1);
    expect(cues[0]!.data).toEqual({ text: "inside" });
    // source 65 in window [60,90] → clip-relative output time 5.
    expect(subTrack.children[0]!.type).toBe("gap");
    expect((subTrack.children[0] as { durationSec: number }).durationSec).toBe(5);
  });

  it("fills hook text from the candidate when the card text is empty", () => {
    const timeline = buildClipTimeline({
      components: [hookCardCfg],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
    });
    const hookClip = clipsOf(timeline.tracks[2]!)[0]!;
    expect(hookClip.kind).toBe("hook_text");
    expect(hookClip.data).toEqual({ text: "wait for it" });
  });

  it("honours list order as z-order (earlier component = higher z)", () => {
    const timeline = buildClipTimeline({
      components: [subtitleConfig(), textWm, hookCardCfg],
      candidate,
      srtByLang,
      mediaRef: "source.mp4",
    });
    // Drop video + audio (both z=0); the rest are the overlay tracks.
    const overlays = timeline.tracks.filter((t) => t.kind === "overlay");
    expect(overlays.map((t) => t.z)).toEqual([3, 2, 1]); // subtitle top, hook bottom
  });
});
