/**
 * AudioPlayback — Web Audio scheduling of a timeline's audio for preview.
 *
 * Schedules each resolved AudioSegment as an AudioBufferSourceNode placed on the
 * shared AudioContext clock, with a per-segment GainNode. Both this and the
 * export mixer walk the SAME resolveAudioSegments output, so preview and render
 * agree on timing + gain (preview≡render extended to audio).
 *
 * Master-clock role: `currentTime` returns the output-timeline position derived
 * from AudioContext.currentTime. The preview's video loop reads this so frames
 * chase the audio (the standard NLE arrangement: audio is sample-accurate and
 * must not stutter; video tolerates a dropped frame). When the timeline has no
 * audio, the caller falls back to its wall-clock and never constructs this.
 *
 * Lifecycle: build(segments, sources) once per timeline; play(fromSec) / pause()
 * / seek(sec) drive transport; dispose() releases the context. Re-scheduling on
 * every play/seek (cheap: BufferSourceNodes are one-shot) keeps state simple and
 * avoids the drift a single long-lived node would accumulate across seeks.
 */

import type { DecodedAudio } from "../source/sample-types";
import type { AudioSegment } from "@composition/compositor/resolveAudio.js";

interface PreparedSegment {
  buffer: AudioBuffer;
  outStartSec: number;
  outEndSec: number;
  sourceStartSec: number;
  gain: number;
}

export class AudioPlayback {
  private ctx: AudioContext;
  private segments: PreparedSegment[] = [];
  private active: AudioBufferSourceNode[] = [];
  private playing = false;
  /** Output-timeline second the current play run started from. */
  private startOffsetSec = 0;
  /** ctx.currentTime captured when the current play run began. */
  private startCtxTime = 0;
  /** Last known position when paused (output-timeline seconds). */
  private pausedAtSec = 0;
  private readonly durationSec: number;

  constructor(durationSec: number) {
    this.ctx = new AudioContext();
    this.durationSec = durationSec;
  }

  /**
   * Convert decoded PCM + resolved segments into AudioBuffers ready to schedule.
   * Sources are keyed by mediaRef (same map the export mixer takes). Segments
   * whose source is missing/empty are dropped.
   */
  build(segments: readonly AudioSegment[], sources: ReadonlyMap<string, DecodedAudio>): void {
    const prepared: PreparedSegment[] = [];
    const bufferCache = new Map<string, AudioBuffer>();
    for (const seg of segments) {
      const src = sources.get(seg.mediaRef);
      if (!src || src.length === 0) continue;
      let buffer = bufferCache.get(seg.mediaRef);
      if (!buffer) {
        buffer = this.ctx.createBuffer(src.numberOfChannels, src.length, src.sampleRate);
        for (let ch = 0; ch < src.numberOfChannels; ch++) {
          // getChannelData().set avoids copyToChannel's strict
          // Float32Array<ArrayBuffer> variance vs our ArrayBufferLike planes.
          buffer.getChannelData(ch).set(src.channelData[ch]!);
        }
        bufferCache.set(seg.mediaRef, buffer);
      }
      prepared.push({
        buffer,
        outStartSec: seg.outStartSec,
        outEndSec: seg.outEndSec,
        sourceStartSec: seg.sourceStartSec,
        gain: seg.gain,
      });
    }
    this.segments = prepared;
  }

  get hasAudio(): boolean {
    return this.segments.length > 0;
  }

  /** Output-timeline position now (seconds), clamped to [0, durationSec]. */
  get currentTime(): number {
    const t = this.playing
      ? this.startOffsetSec + (this.ctx.currentTime - this.startCtxTime)
      : this.pausedAtSec;
    return Math.max(0, Math.min(this.durationSec, t));
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  /**
   * Start playback from `fromSec` (output-timeline seconds). Async: the
   * AudioContext is created suspended (no user gesture at build time), so we
   * MUST await resume() before scheduling — otherwise currentTime is frozen and
   * the nodes are scheduled against a stopped clock (silent). Callers may
   * fire-and-forget; the master clock (`currentTime`) only advances once resumed.
   */
  async play(fromSec: number): Promise<void> {
    this.stopActive();
    const from = Math.max(0, Math.min(this.durationSec, fromSec));
    this.startOffsetSec = from;
    this.startCtxTime = this.ctx.currentTime; // provisional (corrected post-resume)
    this.playing = true;
    this.pausedAtSec = from;
    try {
      await this.ctx.resume();
    } catch (e) {
      console.warn("[AudioPlayback] ctx.resume failed:", e);
    }
    if (!this.playing) return; // paused while resuming
    this.startCtxTime = this.ctx.currentTime;
    this.scheduleFrom(from);
  }

  /** Stop playback, remembering the position for a later resume. */
  pause(): void {
    if (!this.playing) return;
    this.pausedAtSec = this.currentTime;
    this.playing = false;
    this.stopActive();
  }

  /** Reposition; keeps playing if it was playing, else just records position. */
  seek(sec: number): void {
    const to = Math.max(0, Math.min(this.durationSec, sec));
    if (this.playing) {
      void this.play(to);
    } else {
      this.pausedAtSec = to;
    }
  }

  dispose(): void {
    this.stopActive();
    void this.ctx.close();
  }

  // ─────────────────────────────────────────────────────────── internals

  /** Schedule every segment overlapping [fromSec, durationSec) on the ctx clock. */
  private scheduleFrom(fromSec: number): void {
    const now = this.ctx.currentTime;
    for (const seg of this.segments) {
      if (seg.outEndSec <= fromSec) continue; // fully in the past
      // When does this segment start relative to `now`?
      const segStartFromNow = seg.outStartSec - fromSec; // may be negative (already underway)
      const playWhen = now + Math.max(0, segStartFromNow);
      // Offset into the source: skip the part already elapsed when seeking in.
      const intoSeg = Math.max(0, fromSec - seg.outStartSec);
      const sourceOffset = seg.sourceStartSec + intoSeg;
      const playDur = seg.outEndSec - Math.max(seg.outStartSec, fromSec);
      if (playDur <= 0) continue;

      const node = this.ctx.createBufferSource();
      node.buffer = seg.buffer;
      const gainNode = this.ctx.createGain();
      gainNode.gain.value = seg.gain;
      node.connect(gainNode).connect(this.ctx.destination);
      // Clamp the source offset to the buffer length (guards float rounding).
      const safeOffset = Math.max(0, Math.min(seg.buffer.duration, sourceOffset));
      node.start(playWhen, safeOffset, playDur);
      this.active.push(node);
    }
  }

  private stopActive(): void {
    for (const node of this.active) {
      try {
        node.stop();
        node.disconnect();
      } catch {
        /* already stopped */
      }
    }
    this.active = [];
  }
}
