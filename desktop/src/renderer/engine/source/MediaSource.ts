/**
 * Demuxed media file — encoded samples + decoder config + dimensions
 * (ported from Phase). Stateless container; doesn't decode. Multiple
 * ClipReaders can share one MediaSource (same raw mp4 referenced by N clips —
 * exactly the multi-segment concat case in Spike A).
 */

import { demux } from "./Demuxer";
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

  private constructor(init: {
    samples: SampleMeta[];
    config: VideoDecoderConfig;
    width: number;
    height: number;
    codec: string;
    durationUs: number;
  }) {
    this.samples = init.samples;
    this.index = new SampleIndex(init.samples);
    this.config = init.config;
    this.width = init.width;
    this.height = init.height;
    this.codec = init.codec;
    this.durationUs = init.durationUs;
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
    });
  }
}
