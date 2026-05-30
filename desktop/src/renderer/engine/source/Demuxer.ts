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
import type { SampleMeta, AudioTrackMeta } from "./sample-types";

/** First audio track's samples + decoder config, when the file has audio. */
export interface AudioDemux {
  meta: AudioTrackMeta;
  config: AudioDecoderConfig;
  samples: SampleMeta[];
}

export interface DemuxResult {
  samples: SampleMeta[];
  config: VideoDecoderConfig;
  track: Track;
  width: number;
  height: number;
  durationUs: number;
  /** Null when the file has no decodable audio track. */
  audio: AudioDemux | null;
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

/**
 * Extract the AudioSpecificConfig (esds DecoderSpecificInfo) for an AAC track —
 * what AudioDecoder.configure needs as `description`. Defensive: the descriptor
 * tree shape varies by mp4box build, so we recursively search for the
 * descriptor tagged 5 (DecoderSpecificInfo), falling back to the deepest `data`
 * leaf. Returns undefined when absent (e.g. some non-AAC codecs need none).
 */
function buildAudioDescription(file: ISOFile, trackId: number): Uint8Array | undefined {
  try {
    const trak = file.getTrackById(trackId);
    const entry = trak?.mdia?.minf?.stbl?.stsd?.entries?.[0] as unknown;
    const esds = (entry as { esds?: unknown } | undefined)?.esds;
    const found = findDescriptorData(esds);
    return found ?? undefined;
  } catch {
    return undefined;
  }
}

/** Recursively find an esds DecoderSpecificInfo payload (the ASC bytes). */
function findDescriptorData(node: unknown): Uint8Array | undefined {
  if (!node || typeof node !== "object") return undefined;
  const obj = node as Record<string, unknown>;
  if (obj.tag === 5 && obj.data instanceof Uint8Array) return obj.data;
  // Walk known nesting points: esds.esd, then any `descs` arrays.
  const esd = obj.esd;
  if (esd) {
    const hit = findDescriptorData(esd);
    if (hit) return hit;
  }
  const descs = obj.descs;
  if (Array.isArray(descs)) {
    for (const d of descs) {
      const hit = findDescriptorData(d);
      if (hit) return hit;
    }
    for (const d of descs) {
      const dd = (d as Record<string, unknown>)?.data;
      if (dd instanceof Uint8Array) return dd;
    }
  }
  return undefined;
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

  // Audio (optional): first audio track only. Routed by track id in onSamples.
  let audioInfo: Track | undefined;
  let audioConfig: AudioDecoderConfig | undefined;
  let audioId = -1;
  const audioCollected: SampleMeta[] = [];

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

      // Optional audio track: pull config + samples too. Failures here never
      // block video — audio simply stays null.
      const atrack: Track | undefined = info.audioTracks[0];
      const ainfo = atrack?.audio;
      if (atrack && ainfo) {
        audioId = atrack.id;
        audioInfo = atrack;
        const adesc = buildAudioDescription(file, atrack.id);
        audioConfig = {
          codec: atrack.codec,
          sampleRate: ainfo.sample_rate,
          numberOfChannels: ainfo.channel_count,
          ...(adesc ? { description: adesc } : {}),
        };
        file.setExtractionOptions(atrack.id, null, { nbSamples: 4096 });
      }

      file.start();
    };

    file.onSamples = (id: number, _user: unknown, samples: Sample[]) => {
      const bucket = id === audioId ? audioCollected : collected;
      const isAudio = id === audioId;
      for (const s of samples) {
        if (!s.data) continue;
        bucket.push({
          data: new Uint8Array(s.data),
          cts_us: Math.round((s.cts * 1_000_000) / s.timescale),
          dts_us: Math.round((s.dts * 1_000_000) / s.timescale),
          duration_us: Math.round((s.duration * 1_000_000) / s.timescale),
          // AAC frames are individually decodable; force sync for audio.
          is_sync: isAudio ? true : !!s.is_sync,
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

      let audio: AudioDemux | null = null;
      if (audioInfo && audioConfig && audioCollected.length > 0) {
        audioCollected.sort((a, b) => a.dts_us - b.dts_us);
        audio = {
          meta: {
            id: audioInfo.id,
            sampleRate: audioConfig.sampleRate,
            numberOfChannels: audioConfig.numberOfChannels,
            codec: audioConfig.codec,
            nbSamples: audioCollected.length,
            durationUs: (audioInfo.duration * 1_000_000) / audioInfo.timescale,
          },
          config: audioConfig,
          samples: audioCollected,
        };
      }

      resolve({
        samples: collected,
        config,
        track: trackInfo,
        width: videoW,
        height: videoH,
        durationUs,
        audio,
      });
    })();
  });
}
