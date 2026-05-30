/**
 * AudioReader — decodes a source file's audio to planar Float32 PCM.
 *
 * Decodes the whole track once: hot-clip sources are short, and both consumers
 * want the full PCM buffer — preview playback schedules it via Web Audio, export
 * slices + mixes it. `DecodedAudio` is the shared currency.
 *
 * We let the browser do the work via `decodeAudioData(fileBytes)`: it demuxes
 * the container, decodes the codec, and handles the AAC AudioSpecificConfig
 * internally. This is far more robust than hand-feeding raw AAC frames to
 * `AudioDecoder` with a manually-extracted esds `description` (which varies by
 * demuxer build and silently yields no output when wrong). A throwaway
 * AudioContext is created just to decode, then closed.
 */

import type { DecodedAudio } from "./sample-types";

export class AudioReader {
  /** @param url Fetchable source URL (e.g. vc-media://…), same the video uses. */
  constructor(private readonly url: string) {}

  /**
   * Decode the entire audio track to planar Float32 PCM. Returns null when the
   * file has no decodable audio track (silent source) — callers treat that as
   * "no audio", never an error.
   */
  async decodeAll(): Promise<DecodedAudio | null> {
    let bytes: ArrayBuffer;
    try {
      const resp = await fetch(this.url);
      if (!resp.ok) return null;
      bytes = await resp.arrayBuffer();
    } catch {
      return null;
    }

    const ctx = new AudioContext();
    try {
      const buf = await ctx.decodeAudioData(bytes);
      if (buf.numberOfChannels === 0 || buf.length === 0) return null;
      const channelData: Float32Array[] = [];
      for (let ch = 0; ch < buf.numberOfChannels; ch++) {
        // Copy out of the AudioBuffer so the PCM survives the context close.
        channelData.push(new Float32Array(buf.getChannelData(ch)));
      }
      return {
        sampleRate: buf.sampleRate,
        numberOfChannels: buf.numberOfChannels,
        length: buf.length,
        channelData,
      };
    } catch {
      return null; // no audio track / undecodable → silent
    } finally {
      void ctx.close();
    }
  }
}
