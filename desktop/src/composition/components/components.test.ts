import { describe, it, expect } from "vitest";
import { validateTimeline, type Clip, type Timeline, type Track } from "../ir.js";
import { buildTimeMap, identityTimeMap } from "../timemap.js";
import { clip } from "../ir.js";
import type { CompileContext } from "./contract.js";
import { subtitle } from "./subtitle.js";
import { textWatermark, imageWatermark } from "./watermark.js";
import { hookCard, outroCard } from "./card.js";
import { chapter } from "./chapter.js";

function ctx(durationSec: number, over: Partial<CompileContext> = {}): CompileContext {
  return { durationSec, timeMap: identityTimeMap(durationSec), ...over };
}

/** Pull the clips out of a track (skip gaps). */
function clipsOf(track: Track): Clip[] {
  return track.children.filter((c): c is Clip => c.type === "clip");
}

// --- subtitle -------------------------------------------------------------

describe("subtitle component", () => {
  it("emits one overlay track of subtitle_cue clips with inlined style", () => {
    const inst = subtitle.defaultInstance();
    inst.color = "#FFFF00";
    const tracks = subtitle.compile(inst, ctx(30, {
      cues: [
        { sourceStart: 1, sourceEnd: 3, text: "hello" },
        { sourceStart: 5, sourceEnd: 6, text: "world" },
      ],
    }));
    expect(tracks).toHaveLength(1);
    const clips = clipsOf(tracks[0]!);
    expect(clips.map((c) => c.kind)).toEqual(["subtitle_cue", "subtitle_cue"]);
    expect(clips[0]!.data).toEqual({ text: "hello" });
    expect(clips[0]!.style.color).toBe("#FFFF00");
    expect(clips[0]!.style.fontsize_pct).toBe(0.05);
  });

  it("ripples cues through a cutting TimeMap (drops cut cues)", () => {
    // assembly keeps source [0,10) and [30,40); cue at source 15 is cut.
    const videoTrack: Track = {
      kind: "video",
      z: 0,
      enabled: true,
      children: [
        clip({ kind: "video", durationSec: 10, sourceStart: 0, mediaRef: "src", style: {}, data: {} }),
        clip({ kind: "video", durationSec: 10, sourceStart: 30, mediaRef: "src", style: {}, data: {} }),
      ],
    };
    const tm = buildTimeMap(videoTrack);
    const tracks = subtitle.compile(subtitle.defaultInstance(), {
      durationSec: 20,
      timeMap: tm,
      cues: [
        { sourceStart: 2, sourceEnd: 4, text: "kept" },
        { sourceStart: 15, sourceEnd: 18, text: "cut" },
        { sourceStart: 32, sourceEnd: 34, text: "rippled" },
      ],
    });
    const clips = clipsOf(tracks[0]!);
    expect(clips.map((c) => c.data.text)).toEqual(["kept", "rippled"]);
  });

  it("returns nothing when disabled or cue-less", () => {
    expect(subtitle.compile(subtitle.defaultInstance(), ctx(30))).toEqual([]);
    const off = subtitle.defaultInstance();
    off.enabled = false;
    expect(subtitle.compile(off, ctx(30, { cues: [{ sourceStart: 0, sourceEnd: 1, text: "x" }] }))).toEqual([]);
  });
});

// --- watermarks -----------------------------------------------------------

describe("watermark components", () => {
  it("text watermark spans the full duration with primitive-aligned style keys", () => {
    const inst = textWatermark.defaultInstance();
    inst.text = "@channel";
    const [track] = textWatermark.compile(inst, ctx(42));
    const c = clipsOf(track!)[0]!;
    expect(c.kind).toBe("text_watermark");
    expect(c.durationSec).toBe(42);
    expect(Object.keys(c.style).sort()).toEqual(
      ["text_fontsize_pct", "text_color", "text_opacity", "position", "margin_x_pct", "margin_y_pct"].sort(),
    );
    expect(c.data).toEqual({ text: "@channel" });
  });

  it("text watermark is empty when text is blank", () => {
    expect(textWatermark.compile(textWatermark.defaultInstance(), ctx(42))).toEqual([]);
  });

  it("image watermark spans the full duration and carries the path", () => {
    const inst = imageWatermark.defaultInstance();
    inst.imagePath = "logo.png";
    const [track] = imageWatermark.compile(inst, ctx(42));
    const c = clipsOf(track!)[0]!;
    expect(c.kind).toBe("image_watermark");
    expect(c.durationSec).toBe(42);
    expect(c.style.image_scale).toBe(0.15);
    expect(c.data).toEqual({ image_path: "logo.png" });
  });

  it("image watermark is empty when path is blank", () => {
    expect(imageWatermark.compile(imageWatermark.defaultInstance(), ctx(42))).toEqual([]);
  });
});

// --- hook / outro cards ---------------------------------------------------

describe("card components", () => {
  it("hook card pins to the start, capped at its duration", () => {
    const inst = hookCard.defaultInstance();
    inst.text = "watch this";
    inst.durationSec = 5;
    const [track] = hookCard.compile(inst, ctx(60));
    // Overlay tracks aren't padded to the full timeline: a start-pinned card
    // is just the clip (no trailing gap), so the track is 5s while the video is 60s.
    expect(track!.children).toHaveLength(1);
    const c = clipsOf(track!)[0]!;
    expect(c.kind).toBe("hook_text");
    expect(c.durationSec).toBe(5);
    expect(c.style.hook_position).toBe("upper-third");
    expect(c.style.hook_duration_sec).toBe(5);
    expect("outro_position" in c.style).toBe(false);
  });

  it("hook card is capped by a short composition", () => {
    const inst = hookCard.defaultInstance();
    inst.text = "x";
    inst.durationSec = 10;
    const c = clipsOf(hookCard.compile(inst, ctx(3))[0]!)[0]!;
    expect(c.durationSec).toBe(3);
  });

  it("outro card pins to the end", () => {
    const inst = outroCard.defaultInstance();
    inst.text = "subscribe";
    inst.durationSec = 5;
    const [track] = outroCard.compile(inst, ctx(60));
    // leading gap [0,55) then outro clip [55,60)
    expect(track!.children.map((c) => c.type)).toEqual(["gap", "clip"]);
    const c = clipsOf(track!)[0]!;
    expect(c.kind).toBe("outro_text");
    expect(c.durationSec).toBe(5);
    expect(c.style.outro_position).toBe("lower-third");
    expect("hook_position" in c.style).toBe(false);
  });

  it("cards are empty when text is blank or duration ≤ 0", () => {
    expect(hookCard.compile(hookCard.defaultInstance(), ctx(60))).toEqual([]);
    const z = outroCard.defaultInstance();
    z.text = "x";
    z.durationSec = 0;
    expect(outroCard.compile(z, ctx(60))).toEqual([]);
  });
});

// --- chapter (two overlapping layers -> two tracks) -----------------------

describe("chapter component", () => {
  const schedule = [
    { startSec: 0, endSec: 20, title: "Intro", refined: "the intro", keyPoints: [] },
    { startSec: 20, endSec: 50, title: "Body", refined: "the body", keyPoints: [] },
  ];

  it("emits a single strip track by default (start_card off)", () => {
    const inst = chapter.defaultInstance();
    inst.schedule = schedule;
    const tracks = chapter.compile(inst, ctx(50));
    expect(tracks).toHaveLength(1);
    const clips = clipsOf(tracks[0]!);
    expect(clips.map((c) => c.kind)).toEqual(["topic_strip", "topic_strip"]);
    expect(clips[0]!.data).toEqual({ topic_text: "Intro" });
    expect(clips[0]!.style.bg_color).toBe("#1E40AF"); // inlined, no registry
  });

  it("emits two tracks when both layers are on (strip + hero card overlap)", () => {
    const inst = chapter.defaultInstance();
    inst.modes.startCard = true;
    inst.schedule = schedule;
    const tracks = chapter.compile(inst, ctx(50));
    expect(tracks).toHaveLength(2);
    const cardClips = clipsOf(tracks[1]!);
    expect(cardClips.map((c) => c.kind)).toEqual(["chapter_hero_card", "chapter_hero_card"]);
    // hero card capped at start_card.durationSec (6) within the chapter window
    expect(cardClips[0]!.durationSec).toBe(6);
    expect(cardClips[0]!.data).toEqual({ title: "Intro", body: "the intro" });
  });

  it("returns nothing for an empty schedule", () => {
    expect(chapter.compile(chapter.defaultInstance(), ctx(50))).toEqual([]);
  });
});

// --- integration: a full multi-track timeline validates -------------------

describe("integration — components compose into a valid timeline", () => {
  it("video + subtitle + watermark + hook compile into a valid OTIO timeline", () => {
    const durationSec = 60;
    const videoTrack: Track = {
      kind: "video",
      z: 0,
      enabled: true,
      children: [clip({ kind: "video", durationSec, sourceStart: 0, mediaRef: "src", style: {}, data: {} })],
    };
    const c = ctx(durationSec, {
      cues: [
        { sourceStart: 2, sourceEnd: 5, text: "one" },
        { sourceStart: 8, sourceEnd: 10, text: "two" },
      ],
    });

    const sub = subtitle.defaultInstance();
    const wm = textWatermark.defaultInstance();
    wm.text = "@me";
    const hook = hookCard.defaultInstance();
    hook.text = "hi";

    const overlayTracks = [
      ...subtitle.compile(sub, c),
      ...textWatermark.compile(wm, c),
      ...hookCard.compile(hook, c),
    ];

    // Re-stack overlay z by order (host's job in the real assembler).
    overlayTracks.forEach((t, i) => (t.z = 10 + i));

    const timeline: Timeline = {
      durationSec,
      tracks: [videoTrack, ...overlayTracks],
    };
    expect(validateTimeline(timeline, { sourceDurations: { src: 120 } })).toEqual([]);
    expect(overlayTracks).toHaveLength(3);
  });
});
