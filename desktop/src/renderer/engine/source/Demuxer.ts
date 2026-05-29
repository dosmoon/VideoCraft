/**
 * mp4box-based demuxer (ported from Phase).
 *
 * Whole-file demux up front: simple and reliable for moov-at-end files. The
 * host provides a fetchable URL (we use vc-media:// in this app); the engine
 * fetches via the standard fetch API. Returns raw encoded samples plus a
 * VideoDecoderConfig validated by VideoDecoder.isConfigSupported.
 */

import {
  createFile,
  DataStream,
  Endianness,
  MP4BoxBuffer,
  type ISOFile,
  type Sample,
  type Track,
} from "mp4box";

import { EngineError } from "../errors";
import type { SampleMeta } from "./sample-types";

export interface DemuxResult {
  samples: SampleMeta[];
  config: VideoDecoderConfig;
  track: Track;
  width: number;
  height: number;
  durationUs: number;
}

interface AvcSampleEntryLike {
  avcC?: { write: (s: DataStream) => void } | null;
}
interface HvcSampleEntryLike {
  hvcC?: { write: (s: DataStream) => void } | null;
}
interface Av1SampleEntryLike {
  av1C?: { write: (s: DataStream) => void } | null;
}

export function isSupportedCodec(codec: string): boolean {
  return (
    codec.startsWith("avc1") ||
    codec.startsWith("avc3") ||
    codec.startsWith("hvc1") ||
    codec.startsWith("hev1") ||
    codec.startsWith("av01")
  );
}

function writeBoxPayload(box: { write: (s: DataStream) => void }): Uint8Array {
  const stream = new DataStream(undefined, 0, Endianness.BIG_ENDIAN);
  box.write(stream);
  const buf = stream.buffer as ArrayBufferLike;
  return new Uint8Array(buf.slice(8));
}

function buildDescription(
  file: ISOFile,
  trackId: number,
  codec: string,
): Uint8Array | undefined {
  const trak = file.getTrackById(trackId);
  if (!trak) throw new EngineError("trakBox missing", "DEMUX_FAILED");
  const entry = trak.mdia.minf.stbl.stsd.entries[0];
  if (!entry) throw new EngineError("No sample entry in stsd", "DEMUX_FAILED");

  if (codec.startsWith("avc1") || codec.startsWith("avc3")) {
    const e = entry as unknown as AvcSampleEntryLike;
    if (!e.avcC) throw new EngineError("Source has no avcC box", "DEMUX_FAILED");
    return writeBoxPayload(e.avcC);
  }
  if (codec.startsWith("hvc1") || codec.startsWith("hev1")) {
    const e = entry as unknown as HvcSampleEntryLike;
    if (!e.hvcC) throw new EngineError("Source has no hvcC box", "DEMUX_FAILED");
    return writeBoxPayload(e.hvcC);
  }
  if (codec.startsWith("av01")) {
    // av1C is optional; Chromium accepts AV1 with in-band OBU sequence headers.
    const e = entry as unknown as Av1SampleEntryLike;
    return e.av1C ? writeBoxPayload(e.av1C) : undefined;
  }
  throw new EngineError(`Codec ${codec} not supported`, "UNSUPPORTED_CODEC");
}

/** Fetch the URL and extract the first video track's samples + config. */
export async function demux(url: string): Promise<DemuxResult> {
  const file: ISOFile = createFile();
  let trackInfo: Track | undefined;
  let config: VideoDecoderConfig | undefined;
  let videoW = 0;
  let videoH = 0;
  const collected: SampleMeta[] = [];
  let earlyError: Error | null = null;

  return new Promise<DemuxResult>((resolve, reject) => {
    file.onError = (msg: string) => {
      earlyError = new EngineError(msg, "DEMUX_FAILED");
    };

    file.onReady = (info) => {
      const track: Track | undefined = info.videoTracks[0];
      if (!track) {
        earlyError = new EngineError("No video track", "NO_VIDEO_TRACK");
        return;
      }
      if (!isSupportedCodec(track.codec)) {
        earlyError = new EngineError(
          `Codec ${track.codec} not supported`,
          "UNSUPPORTED_CODEC",
        );
        return;
      }
      const video = track.video;
      if (!video) {
        earlyError = new EngineError("Track has no video config", "NO_VIDEO_TRACK");
        return;
      }
      let description: Uint8Array | undefined;
      try {
        description = buildDescription(file, track.id, track.codec);
      } catch (err) {
        earlyError = err instanceof Error ? err : new Error(String(err));
        return;
      }
      trackInfo = track;
      videoW = video.width;
      videoH = video.height;
      config = {
        codec: track.codec,
        codedWidth: video.width,
        codedHeight: video.height,
        ...(description ? { description } : {}),
      };
      file.setExtractionOptions(track.id, null, { nbSamples: 1024 });
      file.start();
    };

    file.onSamples = (_id: number, _user: unknown, samples: Sample[]) => {
      for (const s of samples) {
        if (!s.data) continue;
        collected.push({
          data: new Uint8Array(s.data),
          cts_us: Math.round((s.cts * 1_000_000) / s.timescale),
          dts_us: Math.round((s.dts * 1_000_000) / s.timescale),
          duration_us: Math.round((s.duration * 1_000_000) / s.timescale),
          is_sync: !!s.is_sync,
        });
      }
    };

    void (async () => {
      try {
        const resp = await fetch(url);
        if (!resp.ok) {
          throw new EngineError(`fetch failed: ${resp.status}`, "DEMUX_FAILED");
        }
        const ab = await resp.arrayBuffer();
        file.appendBuffer(MP4BoxBuffer.fromArrayBuffer(ab, 0));
        file.flush();
      } catch (err) {
        return reject(err instanceof Error ? err : new Error(String(err)));
      }

      if (earlyError) return reject(earlyError);
      if (!trackInfo || !config) {
        return reject(
          new EngineError("mp4box never reported a video track", "DEMUX_FAILED"),
        );
      }
      if (collected.length === 0) {
        return reject(new EngineError("No samples extracted", "NO_SAMPLES"));
      }
      collected.sort((a, b) => a.dts_us - b.dts_us);

      try {
        const probe = await VideoDecoder.isConfigSupported(config);
        if (!probe.supported) {
          return reject(
            new EngineError(
              `WebCodecs reports config not supported: codec=${config.codec}`,
              "INVALID_CONFIG",
            ),
          );
        }
      } catch (err) {
        return reject(err instanceof Error ? err : new Error(String(err)));
      }

      const durationUs = (trackInfo.duration * 1_000_000) / trackInfo.timescale;
      resolve({
        samples: collected,
        config,
        track: trackInfo,
        width: videoW,
        height: videoH,
        durationUs,
      });
    })();
  });
}
