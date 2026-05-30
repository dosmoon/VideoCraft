/**
 * AudioReader — decodes a source's audio track to planar Float32 PCM.
 *
 * Unlike the video path (frames decoded on demand for seeking), audio is decoded
 * in full once: hot-clip sources are short, and both consumers want the whole
 * PCM buffer — preview playback schedules it via Web Audio, export slices + mixes
 * it. `DecodedAudio` is the shared currency.
 *
 * AAC packets are individually decodable, so there is no keyframe seek; we feed
 * every sample in presentation order and concatenate the decoder's output.
 */

import type { AudioDemux } from "./Demuxer";
import type { DecodedAudio } from "./sample-types";

interface DecodedChunk {
  timestamp: number;
  planes: Float32Array[];
}

export class AudioReader {
  constructor(private readonly audio: AudioDemux) {}

  /** Decode the entire audio track to planar Float32 PCM at the source rate. */
  async decodeAll(): Promise<DecodedAudio> {
    const { meta, config, samples } = this.audio;
    const chunks: DecodedChunk[] = [];
    let decodeError: Error | null = null;

    const decoder = new AudioDecoder({
      output: (data: AudioData) => {
        try {
          const channels = data.numberOfChannels;
          const frames = data.numberOfFrames;
          const planes: Float32Array[] = [];
          for (let ch = 0; ch < channels; ch++) {
            const plane = new Float32Array(frames);
            data.copyTo(plane, { planeIndex: ch, format: "f32-planar" });
            planes.push(plane);
          }
          chunks.push({ timestamp: data.timestamp, planes });
        } finally {
          data.close();
        }
      },
      error: (e) => {
        decodeError = e instanceof Error ? e : new Error(String(e));
      },
    });

    decoder.configure(config);
    for (const s of samples) {
      decoder.decode(
        new EncodedAudioChunk({
          type: "key",
          timestamp: s.cts_us,
          duration: s.duration_us,
          data: s.data,
        }),
      );
    }

    await decoder.flush().catch(() => {});
    try {
      decoder.close();
    } catch {
      /* already closed */
    }
    if (decodeError) throw decodeError;

    return assemble(chunks, meta.numberOfChannels, meta.sampleRate);
  }
}

/** Concatenate decoded chunks (presentation order) into one planar PCM buffer. */
function assemble(
  chunks: DecodedChunk[],
  numberOfChannels: number,
  sampleRate: number,
): DecodedAudio {
  chunks.sort((a, b) => a.timestamp - b.timestamp);
  const total = chunks.reduce((n, c) => n + (c.planes[0]?.length ?? 0), 0);
  const channelData: Float32Array[] = [];
  for (let ch = 0; ch < numberOfChannels; ch++) {
    channelData.push(new Float32Array(total));
  }
  let offset = 0;
  for (const c of chunks) {
    const frames = c.planes[0]?.length ?? 0;
    for (let ch = 0; ch < numberOfChannels; ch++) {
      // Mono source feeding a stereo request: replicate the last available plane.
      const src = c.planes[ch] ?? c.planes[c.planes.length - 1];
      if (src) channelData[ch]!.set(src.subarray(0, frames), offset);
    }
    offset += frames;
  }
  return { sampleRate, numberOfChannels, length: total, channelData };
}
