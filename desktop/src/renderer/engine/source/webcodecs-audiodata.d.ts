/**
 * Minimal ambient `AudioData` — the only WebCodecs type missing from this
 * TypeScript DOM lib (AudioDecoder / AudioEncoder / EncodedAudioChunk / VideoFrame
 * are all present, but `AudioData` is absent). Declares just the surface the
 * engine uses: decode reads AudioData from the decoder; export constructs one to
 * feed AudioEncoder. No imports/exports → global script, so the interface is
 * visible everywhere (including the lib's AudioDecoder/AudioEncoder callbacks).
 */

type AudioSampleFormat =
  | "u8"
  | "s16"
  | "s32"
  | "f32"
  | "u8-planar"
  | "s16-planar"
  | "s32-planar"
  | "f32-planar";

interface AudioDataCopyToOptions {
  planeIndex: number;
  frameOffset?: number;
  frameCount?: number;
  format?: AudioSampleFormat;
}

interface AudioDataInit {
  format: AudioSampleFormat;
  sampleRate: number;
  numberOfFrames: number;
  numberOfChannels: number;
  timestamp: number;
  data: BufferSource;
  transfer?: ArrayBuffer[];
}

interface AudioData {
  readonly format: AudioSampleFormat | null;
  readonly sampleRate: number;
  readonly numberOfFrames: number;
  readonly numberOfChannels: number;
  readonly duration: number;
  readonly timestamp: number;
  allocationSize(options: AudioDataCopyToOptions): number;
  copyTo(destination: Float32Array, options: AudioDataCopyToOptions): void;
  clone(): AudioData;
  close(): void;
}

declare var AudioData: {
  prototype: AudioData;
  new (init: AudioDataInit): AudioData;
};
