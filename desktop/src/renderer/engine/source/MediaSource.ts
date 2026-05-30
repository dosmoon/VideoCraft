/**
 * Demuxed media file — encoded samples + decoder config + dimensions
 * (ported from Phase). Stateless container; doesn't decode. Multiple
 * ClipReaders can share one MediaSource (same raw mp4 referenced by N clips —
 * exactly the multi-segment concat case in Spike A).
 */

import { demux, type AudioDemux } from "./Demuxer";
import { SampleIndex } from "./SampleIndex";
import type { SampleMeta } from "./sample-types";

export class MediaSource {
  readonly samples: ReadonlyArray<SampleMeta>;
  readonly index: SampleIndex;
  readonly config: VideoDecoderConfig;
  readonly width: number;
  readonly height: number;
  readonly codec: string;
  readonly durationUs: number;
  /** First audio track's samples + config, or null when the file has no audio. */
  readonly audio: AudioDemux | null;

  private constructor(init: {
    samples: SampleMeta[];
    config: VideoDecoderConfig;
    width: number;
    height: number;
    codec: string;
    durationUs: number;
    audio: AudioDemux | null;
  }) {
    this.samples = init.samples;
    this.index = new SampleIndex(init.samples);
    this.config = init.config;
    this.width = init.width;
    this.height = init.height;
    this.codec = init.codec;
    this.durationUs = init.durationUs;
    this.audio = init.audio;
  }

  /** True when the source carries a decodable audio track. */
  get hasAudio(): boolean {
    return this.audio != null;
  }

  static async open(url: string): Promise<MediaSource> {
    const r = await demux(url);
    return new MediaSource({
      samples: r.samples,
      config: r.config,
      width: r.width,
      height: r.height,
      codec: r.track.codec,
      durationUs: r.durationUs,
      audio: r.audio,
    });
  }
}
