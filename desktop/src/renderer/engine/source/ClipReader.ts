/**
 * Real-time video clip reader (ported from Phase).
 *
 * Implements VideoSource for one media clip with optional in/out trim. Owns:
 *   - a long-lived VideoDecoder (created on first frameAt, kept alive across
 *     the session — the perf fix vs. "fresh decoder per call" which is O(N²)
 *     inside a GOP)
 *   - a FrameRingBuffer of decoded VideoFrames
 *   - an async pump feeding encoded samples to the decoder, back-pressured on
 *     buffer capacity
 *
 * Time domains:
 *   - frameAt(clipTimeUs): caller coords, [0, durationUs] where
 *     durationUs = sourceOut - sourceIn.
 *   - internally MEDIA coords (cts_us); mediaTime = sourceInUs + clipTime.
 *
 * Seek vs. play:
 *   - forward play within buffered range = no seek, just pickAt. Fast.
 *   - out-of-range target = seek: stop pump, dispose decoder, clear buffer,
 *     cursor to keyframe at-or-before target, start new pump.
 */

import { EngineError } from "../errors";
import type { TimeUs, VideoSource } from "../types";
import { FrameRingBuffer } from "./FrameRingBuffer";
import { MediaSource } from "./MediaSource";

const RING_CAPACITY = 8;
/** How far past the buffer's latest frame still counts as in-range before a seek. */
const FORWARD_LOOKAHEAD_US = 1_000_000; // 1s
/** Soft trim threshold: drop frames more than this far behind current target. */
const TRIM_BEHIND_US = 200_000; // 200ms
/** Max wait inside frameAt() for the pump to produce a usable frame. */
const FRAME_WAIT_BUDGET_MS = 150;
/** Max time for decoder.flush() before we give up on a seek. */
const FLUSH_TIMEOUT_MS = 2000;
/** Max wait inside frameAtExact() for the pump to reach the target frame. */
const EXACT_WAIT_BUDGET_MS = 3000;

interface SeekState {
  /** Sample index (decode order) the pump should feed next. */
  cursor: number;
  /** Sample index of the current keyframe so the first chunk is typed 'key'. */
  keyIdx: number;
  /** Target media time the seek was scheduled for (diagnostics). */
  targetMediaUs: TimeUs;
}

export class ClipReader implements VideoSource {
  readonly width: number;
  readonly height: number;
  readonly durationUs: TimeUs;

  private readonly mediaSource: MediaSource;
  private readonly sourceInUs: TimeUs;
  private readonly sourceOutUs: TimeUs;

  private decoder: VideoDecoder | null = null;
  private decoderError: Error | null = null;
  private buffer = new FrameRingBuffer(RING_CAPACITY);

  private seek: SeekState | null = null;
  private pumpRunning = false;
  /** Bumped on every seek; the pump samples this to know when to bail. */
  private generation = 0;

  private frameAvailableSubs = new Set<() => void>();
  private disposed = false;

  constructor(mediaSource: MediaSource, sourceInUs?: TimeUs, sourceOutUs?: TimeUs) {
    this.mediaSource = mediaSource;
    this.sourceInUs = clamp(sourceInUs ?? 0, 0, mediaSource.durationUs);
    this.sourceOutUs = clamp(
      sourceOutUs ?? mediaSource.durationUs,
      this.sourceInUs,
      mediaSource.durationUs,
    );
    this.width = mediaSource.width;
    this.height = mediaSource.height;
    this.durationUs = this.sourceOutUs - this.sourceInUs;
  }

  async frameAt(clipTimeUs: TimeUs): Promise<VideoFrame | null> {
    if (this.disposed) return null;
    if (this.decoderError) throw this.decoderError;

    const mediaTime = this.sourceInUs + clamp(clipTimeUs, 0, this.durationUs);

    if (this.needsRepositionFor(mediaTime)) {
      this.beginSeek(mediaTime);
    }

    this.startPumpIfIdle();

    let candidate = this.buffer.pickAt(mediaTime);
    if (candidate) {
      this.buffer.trimBefore(mediaTime - TRIM_BEHIND_US);
      return candidate;
    }

    candidate = await this.waitForFrameAt(mediaTime, FRAME_WAIT_BUDGET_MS);
    if (candidate) {
      this.buffer.trimBefore(mediaTime - TRIM_BEHIND_US);
      return candidate;
    }
    // Final fallback: caller asked for a time BEFORE the first producible
    // frame (e.g., target=0 on a video that starts at pts=266ms). Return the
    // earliest buffered frame so the consumer always sees something.
    if (this.buffer.size() > 0) {
      return this.buffer.pickEarliest();
    }
    return null;
  }

  /**
   * Export-mode fetch: like frameAt, but WAIT until the decoder has produced a
   * frame at-or-past the target, so pickAt returns the exact display frame for
   * `clipTimeUs` rather than the best-buffered-so-far. The playback frameAt
   * never blocks (smooth scrub, tolerates lag); export is not real-time and
   * needs the exact frame, so it waits here.
   */
  async frameAtExact(clipTimeUs: TimeUs): Promise<VideoFrame | null> {
    if (this.disposed) return null;
    if (this.decoderError) throw this.decoderError;
    const mediaTime = this.sourceInUs + clamp(clipTimeUs, 0, this.durationUs);

    if (this.needsRepositionFor(mediaTime)) this.beginSeek(mediaTime);
    this.startPumpIfIdle();

    const start = performance.now();
    while (!this.disposed && this.buffer.latestPts() < mediaTime) {
      if (this.decoderError) throw this.decoderError;
      // End of stream reached and pump idle → can't get any closer.
      if (this.seek && this.seek.cursor >= this.mediaSource.samples.length && !this.pumpRunning) {
        break;
      }
      if (performance.now() - start > EXACT_WAIT_BUDGET_MS) break;
      // Drain frames behind the target so the (capacity-bounded) pump always
      // has space to decode FORWARD toward the target — otherwise a full buffer
      // of sub-target frames deadlocks the pump and we'd spin to the budget.
      this.buffer.trimBefore(mediaTime - TRIM_BEHIND_US);
      this.startPumpIfIdle();
      // Wake on the next decoded frame (no 4ms poll clamp), with a short
      // fallback in case the pump momentarily stalls.
      await new Promise<void>((resolve) => {
        let done = false;
        const finish = () => {
          if (done) return;
          done = true;
          unsub();
          clearTimeout(timer);
          resolve();
        };
        const unsub = this.onFrameAvailable(finish);
        const timer = setTimeout(finish, 100);
      });
    }

    const candidate = this.buffer.pickAt(mediaTime) ?? this.buffer.pickEarliest();
    if (candidate) this.buffer.trimBefore(mediaTime - TRIM_BEHIND_US);
    return candidate;
  }

  onFrameAvailable(cb: () => void): () => void {
    this.frameAvailableSubs.add(cb);
    return () => {
      this.frameAvailableSubs.delete(cb);
    };
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.generation++;
    this.disposeDecoder();
    this.frameAvailableSubs.clear();
    this.buffer.dispose();
  }

  // ────────────────────────────────────────────────────────── internals

  private needsRepositionFor(mediaTime: TimeUs): boolean {
    if (!this.seek) return true;
    const earliest = this.buffer.earliestPts();
    const latest = this.buffer.latestPts();
    // Buffer empty AND a seek is in flight → no reposition; pump will produce.
    if (!Number.isFinite(earliest) && this.pumpRunning) return false;
    if (!Number.isFinite(earliest)) return true;
    if (mediaTime < earliest) return true;
    if (mediaTime > latest + FORWARD_LOOKAHEAD_US) return true;
    return false;
  }

  private beginSeek(mediaTime: TimeUs): void {
    this.generation++;
    this.disposeDecoder();
    this.buffer.clear();
    const keyIdx = this.mediaSource.index.findKeyframeAtOrBefore(mediaTime);
    this.seek = { cursor: keyIdx, keyIdx, targetMediaUs: mediaTime };
  }

  private startPumpIfIdle(): void {
    if (this.pumpRunning || this.disposed) return;
    if (!this.seek) return;
    if (this.seek.cursor >= this.mediaSource.samples.length) return;
    this.pumpRunning = true;
    void this.runPump(this.generation);
  }

  private async runPump(myGeneration: number): Promise<void> {
    try {
      if (!this.decoder) this.initDecoder();
      if (!this.decoder) return;

      while (
        !this.disposed &&
        this.generation === myGeneration &&
        this.seek &&
        this.seek.cursor < this.mediaSource.samples.length
      ) {
        if (!this.buffer.hasSpace()) {
          await this.buffer.awaitSpace();
          continue;
        }
        if (this.disposed || this.generation !== myGeneration || !this.seek) {
          break;
        }

        const samples = this.mediaSource.samples;
        const i = this.seek.cursor;
        const sample = samples[i]!;
        const isKey = i === this.seek.keyIdx;

        try {
          this.decoder.decode(
            new EncodedVideoChunk({
              type: isKey ? "key" : "delta",
              timestamp: sample.cts_us,
              duration: sample.duration_us,
              data: sample.data,
            }),
          );
        } catch (err) {
          this.decoderError = err instanceof Error ? err : new Error(String(err));
          break;
        }

        this.seek.cursor++;

        // Stop feeding past clip end, with a B-frame margin so output reaches
        // sourceOut.
        if (sample.cts_us >= this.sourceOutUs) {
          if (sample.cts_us >= this.sourceOutUs + 250_000) break;
        }

        // Yield occasionally so the output handler runs.
        if ((i & 0x7) === 0) {
          await new Promise<void>((res) => setTimeout(res, 0));
        }
      }
    } finally {
      this.pumpRunning = false;
    }
  }

  private initDecoder(): void {
    try {
      const decoder = new VideoDecoder({
        output: (frame) => {
          // Drop frames outside the clip window (with margin).
          if (
            frame.timestamp < this.sourceInUs - 100_000 ||
            frame.timestamp > this.sourceOutUs + 250_000
          ) {
            frame.close();
            return;
          }
          if (this.disposed || !this.buffer.hasSpace()) {
            frame.close();
            return;
          }
          this.buffer.push(frame);
          for (const cb of this.frameAvailableSubs) cb();
        },
        error: (e) => {
          this.decoderError = e instanceof Error ? e : new Error(String(e));
        },
      });
      decoder.configure(this.mediaSource.config);
      this.decoder = decoder;
    } catch (err) {
      this.decoderError = err instanceof Error ? err : new Error(String(err));
      this.decoder = null;
    }
  }

  private disposeDecoder(): void {
    if (this.decoder) {
      try {
        this.decoder.close();
      } catch {
        // ignore
      }
      this.decoder = null;
    }
    this.decoderError = null;
  }

  private async waitForFrameAt(
    mediaTime: TimeUs,
    budgetMs: number,
  ): Promise<VideoFrame | null> {
    const start = performance.now();
    while (!this.disposed) {
      const candidate = this.buffer.pickAt(mediaTime);
      if (candidate) return candidate;
      if (this.decoderError) throw this.decoderError;
      if (performance.now() - start > budgetMs) return null;
      await new Promise<void>((res) => setTimeout(res, 8));
    }
    return null;
  }

  /** Force a flush + return success or timeout (used by diagnostics/tests). */
  async flushDecoder(timeoutMs: number = FLUSH_TIMEOUT_MS): Promise<void> {
    const dec = this.decoder;
    if (!dec) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    try {
      await Promise.race([
        dec.flush(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => {
            reject(
              new EngineError(
                `decoder.flush() timed out after ${timeoutMs}ms`,
                "FLUSH_TIMEOUT",
              ),
            );
          }, timeoutMs);
        }),
      ]);
    } finally {
      if (timer !== null) clearTimeout(timer);
    }
  }
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
