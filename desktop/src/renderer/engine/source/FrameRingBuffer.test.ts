import { describe, it, expect } from "vitest";
import { FrameRingBuffer } from "./FrameRingBuffer";

/**
 * Fake VideoFrame: the ring only touches `.timestamp`, `.close()`, `.clone()`.
 * `_closed` lets tests assert the buffer releases the underlying frame.
 */
function makeFrame(timestamp: number): VideoFrame & { _closed: boolean } {
  const f = {
    timestamp,
    _closed: false,
    close(this: { _closed: boolean }): void {
      this._closed = true;
    },
    clone(): VideoFrame {
      return makeFrame(timestamp);
    },
  };
  return f as unknown as VideoFrame & { _closed: boolean };
}

describe("FrameRingBuffer.dropOldest", () => {
  it("drops + closes the oldest frame and frees a slot", () => {
    const buf = new FrameRingBuffer(4);
    const f0 = makeFrame(0);
    const f1 = makeFrame(100);
    const f2 = makeFrame(200);
    buf.push(f0);
    buf.push(f1);
    buf.push(f2);
    expect(buf.size()).toBe(3);
    expect(buf.earliestPts()).toBe(0);

    expect(buf.dropOldest()).toBe(true);
    expect(f0._closed).toBe(true);
    expect(buf.size()).toBe(2);
    expect(buf.earliestPts()).toBe(100);
    // Survivors untouched.
    expect(f1._closed).toBe(false);
    expect(f2._closed).toBe(false);
  });

  it("returns false and closes nothing on an empty buffer", () => {
    const buf = new FrameRingBuffer(4);
    expect(buf.dropOldest()).toBe(false);
    expect(buf.size()).toBe(0);
  });

  it("signals space so a blocked awaitSpace() resolves", async () => {
    const buf = new FrameRingBuffer(2);
    buf.push(makeFrame(0));
    buf.push(makeFrame(100));
    expect(buf.hasSpace()).toBe(false);

    let resolved = false;
    const waiter = buf.awaitSpace().then(() => {
      resolved = true;
    });
    // Still pending until something frees a slot.
    await Promise.resolve();
    expect(resolved).toBe(false);

    buf.dropOldest();
    await waiter;
    expect(resolved).toBe(true);
    expect(buf.hasSpace()).toBe(true);
  });

  it("can drain to empty via repeated dropOldest", () => {
    const buf = new FrameRingBuffer(4);
    const frames = [makeFrame(0), makeFrame(10), makeFrame(20)];
    for (const f of frames) buf.push(f);
    while (buf.dropOldest()) {
      /* drain */
    }
    expect(buf.size()).toBe(0);
    expect(frames.every((f) => f._closed)).toBe(true);
  });
});
