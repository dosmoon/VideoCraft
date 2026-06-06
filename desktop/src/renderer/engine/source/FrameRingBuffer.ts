/**
 * Bounded buffer of decoded VideoFrames, ordered by presentation time
 * (ported from Phase). Bridges the async decode pump (producer) and the
 * per-tick frameAt() consumer. Small capacity (~8) so we don't pin too many
 * GPU surfaces; the pump back-pressures via awaitSpace().
 */
export class FrameRingBuffer {
  private frames: VideoFrame[] = [];
  private waiters: Array<() => void> = [];
  private closed = false;

  constructor(public readonly capacity: number) {}

  size(): number {
    return this.frames.length;
  }

  hasSpace(): boolean {
    return !this.closed && this.frames.length < this.capacity;
  }

  /** Earliest buffered pts, or +∞ if empty. */
  earliestPts(): number {
    return this.frames[0]?.timestamp ?? Number.POSITIVE_INFINITY;
  }

  /** Latest buffered pts, or -∞ if empty. */
  latestPts(): number {
    const last = this.frames[this.frames.length - 1];
    return last?.timestamp ?? Number.NEGATIVE_INFINITY;
  }

  /** Insert keeping pts-ascending order. Caller must check hasSpace() first. */
  push(frame: VideoFrame): void {
    if (this.closed) {
      frame.close();
      return;
    }
    let i = this.frames.length;
    while (i > 0 && this.frames[i - 1]!.timestamp > frame.timestamp) i--;
    this.frames.splice(i, 0, frame);
  }

  /**
   * Largest-pts frame whose pts ≤ targetUs. Returns a CLONE; the original
   * stays buffered. Caller closes the clone.
   */
  pickAt(targetUs: number): VideoFrame | null {
    let best: VideoFrame | null = null;
    for (const f of this.frames) {
      if (f.timestamp <= targetUs) best = f;
      else break;
    }
    return best ? best.clone() : null;
  }

  /**
   * Earliest-pts frame regardless of target — fallback when pickAt returns
   * null because the requested time is before the first available frame
   * (common when a video doesn't start at pts=0). Returns a CLONE.
   */
  pickEarliest(): VideoFrame | null {
    return this.frames[0]?.clone() ?? null;
  }

  /** Drop frames with pts < threshold. Returns count dropped. */
  trimBefore(thresholdUs: number): number {
    let i = 0;
    while (i < this.frames.length && this.frames[i]!.timestamp < thresholdUs) {
      i++;
    }
    if (i === 0) return 0;
    for (let j = 0; j < i; j++) this.frames[j]!.close();
    this.frames.splice(0, i);
    this.signalSpace();
    return i;
  }

  /**
   * Drop the single oldest frame (closing it) and signal space. Returns true if
   * one was dropped. The export-exact fetch uses this to guarantee forward
   * progress: the time-based trimBefore() window can hold more frames than the
   * ring can fit for high-fps sources (200ms × 60fps = 12 > capacity 8), which
   * would otherwise leave a full ring with nothing trimmable and deadlock the
   * decode pump on awaitSpace().
   */
  dropOldest(): boolean {
    const f = this.frames.shift();
    if (!f) return false;
    f.close();
    this.signalSpace();
    return true;
  }

  /** Drop everything (e.g., on seek). */
  clear(): void {
    for (const f of this.frames) f.close();
    this.frames = [];
    this.signalSpace();
  }

  /** Resolves once there's space (or the buffer is closed). */
  awaitSpace(): Promise<void> {
    if (this.hasSpace() || this.closed) return Promise.resolve();
    return new Promise<void>((res) => this.waiters.push(res));
  }

  dispose(): void {
    this.closed = true;
    this.clear();
    this.signalSpace();
  }

  private signalSpace(): void {
    while (this.waiters.length > 0 && (this.hasSpace() || this.closed)) {
      const w = this.waiters.shift()!;
      w();
    }
  }
}
