/**
 * Native ffmpeg encode jobs (main process). The renderer renders frames on the
 * GPU and pipes RAW pixels here; ffmpeg encodes them with h264_nvenc (hardware,
 * the route around Chromium's software-only WebCodecs encoder) and pulls AUDIO
 * straight from the source file. mirrors the writeStreams .part→rename discipline
 * in main.ts and the spawn pattern in sidecar.ts.
 *
 * Frame transport is renderer→main IPC (rawvideo, ~240 MB/s @1080p30); writeFrame
 * honors ffmpeg stdin backpressure (the 'drain' event) so memory stays bounded.
 */

import { spawn, spawnSync, type ChildProcessByStdio } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, rename, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { Readable, Writable } from "node:stream";

/** stdio ["pipe","ignore","pipe"]: stdin in, stdout ignored, stderr captured. */
type FfmpegProc = ChildProcessByStdio<Writable, null, Readable>;

export interface FfmpegStartParams {
  /** Final output path; ffmpeg writes "<path>.part" then close renames it. */
  outputPath: string;
  width: number;
  height: number;
  fps: number;
  /** Target video bitrate (bps). */
  bitrate: number;
  /** Raw input pixel format from the GPU readback ("bgra" on Windows / "rgba"). */
  pixfmt: "bgra" | "rgba";
  /** Source file to pull the audio track from (omit for silent output). */
  sourcePath?: string;
  /** Audio in-point (sec) for a clip window; omit for full-source. */
  audioStartSec?: number;
}

interface FfmpegJob {
  proc: FfmpegProc;
  tmp: string;
  final: string;
  stderrTail: string[];
  /** Set when ffmpeg exits before finish() — writeFrame rejects rather than hangs. */
  exited?: boolean;
}

const jobs = new Map<number, FfmpegJob>();
let nextJobId = 1;

let ffmpegPathCache: string | null | undefined;
let probeCache: { ffmpeg: boolean; nvenc: boolean } | undefined;

/** Resolve the ffmpeg binary: a bundled copy (packaged app) else PATH lookup. */
export function resolveFfmpeg(): string | null {
  if (ffmpegPathCache !== undefined) return ffmpegPathCache;
  const exe = process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg";
  const bundled = join(process.resourcesPath || "", exe);
  if (process.resourcesPath && existsSync(bundled)) {
    ffmpegPathCache = bundled;
    return bundled;
  }
  // Dev / system install: rely on PATH. Confirm it runs.
  const r = spawnSync("ffmpeg", ["-version"], { encoding: "utf-8" });
  ffmpegPathCache = r.status === 0 ? "ffmpeg" : null;
  return ffmpegPathCache;
}

/** Is ffmpeg present, and does it have a working h264_nvenc encoder? Cached. */
export function probeFfmpeg(): { ffmpeg: boolean; nvenc: boolean } {
  if (probeCache !== undefined) return probeCache;
  const ff = resolveFfmpeg();
  if (!ff) {
    probeCache = { ffmpeg: false, nvenc: false };
    return probeCache;
  }
  let nvenc = false;
  const list = spawnSync(ff, ["-hide_banner", "-encoders"], { encoding: "utf-8" });
  if (list.status === 0 && /h264_nvenc/.test(list.stdout)) {
    // Built with nvenc — confirm it actually initializes on this box (driver/GPU).
    // Use testsrc @256² (nullsrc / tiny sizes can fail NVENC init).
    const test = spawnSync(
      ff,
      ["-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=256x256:rate=30:duration=1",
       "-frames:v", "1", "-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", "-f", "null", "-"],
      { encoding: "utf-8" },
    );
    nvenc = test.status === 0;
    if (!nvenc) console.error("[ffmpeg] nvenc probe failed:", (test.stderr || "").trim() || `status=${test.status}`);
  }
  console.log(`[ffmpeg] probe: ffmpeg=true nvenc=${nvenc} (${ff})`);
  probeCache = { ffmpeg: true, nvenc };
  return probeCache;
}

export async function startJob(p: FfmpegStartParams): Promise<number> {
  const ff = resolveFfmpeg();
  if (!ff) throw new Error("ffmpeg not found");
  const { nvenc } = probeFfmpeg();
  await mkdir(dirname(p.outputPath), { recursive: true });
  const tmp = p.outputPath + ".part";

  const args = [
    "-y", "-hide_banner", "-loglevel", "error",
    // Raw video from the renderer over stdin.
    "-f", "rawvideo", "-pix_fmt", p.pixfmt, "-s", `${p.width}x${p.height}`, "-r", String(p.fps), "-i", "pipe:0",
  ];
  if (p.sourcePath) {
    if (p.audioStartSec && p.audioStartSec > 0) args.push("-ss", String(p.audioStartSec));
    args.push("-i", p.sourcePath);
  }
  args.push("-map", "0:v:0");
  if (p.sourcePath) args.push("-map", "1:a:0?"); // optional — tolerate silent source
  args.push(
    "-c:v", nvenc ? "h264_nvenc" : "libx264",
    "-preset", nvenc ? "p4" : "veryfast",
    "-b:v", String(p.bitrate),
    "-pix_fmt", "yuv420p",
  );
  if (p.sourcePath) args.push("-c:a", "aac", "-b:a", "192k");
  // Explicit muxer: the ".part" temp extension hides the format from ffmpeg's
  // extension-based detection ("Unable to choose an output format").
  args.push("-shortest", "-movflags", "+faststart", "-f", "mp4", tmp);

  console.log(`[ffmpeg] start ${ff} ${args.join(" ")}`);
  const proc = spawn(ff, args, { stdio: ["pipe", "ignore", "pipe"] }) as FfmpegProc;
  const job: FfmpegJob = { proc, tmp, final: p.outputPath, stderrTail: [] };
  proc.stderr.setEncoding("utf-8");
  proc.stderr.on("data", (chunk: string) => {
    for (const line of chunk.split("\n")) {
      if (line.trim()) {
        job.stderrTail.push(line);
        console.error("[ffmpeg]", line);
      }
    }
    if (job.stderrTail.length > 50) job.stderrTail.splice(0, job.stderrTail.length - 50);
  });
  proc.on("error", (e) => console.error("[ffmpeg] spawn error:", e));
  proc.on("close", (code) => {
    job.exited = true;
    console.log(`[ffmpeg] exit ${code}`);
  });
  // Surface a spawn/stdin error so writeFrame/finish reject rather than hang.
  proc.stdin.on("error", () => {/* swallowed; finish() reports via exit code */});

  const id = nextJobId++;
  jobs.set(id, job);
  return id;
}

/** Write one raw frame to ffmpeg's stdin, honoring backpressure. */
export function writeFrame(id: number, bytes: Uint8Array): Promise<void> {
  const job = jobs.get(id);
  if (!job) return Promise.reject(new Error(`ffmpeg job ${id} not open`));
  if (job.exited) {
    return Promise.reject(new Error(`ffmpeg exited early: ${job.stderrTail.join("\n") || "(no stderr)"}`));
  }
  const buf = Buffer.from(bytes);
  return new Promise<void>((resolve, reject) => {
    const onErr = (e: Error) => reject(e);
    job.proc.stdin.once("error", onErr);
    const ok = job.proc.stdin.write(buf, () => job.proc.stdin.removeListener("error", onErr));
    if (ok) resolve();
    else job.proc.stdin.once("drain", () => resolve());
  });
}

/** Close stdin, await ffmpeg exit; on success rename .part → final and return it. */
export function finishJob(id: number): Promise<string> {
  const job = jobs.get(id);
  if (!job) return Promise.reject(new Error(`ffmpeg job ${id} not open`));
  return new Promise<string>((resolve, reject) => {
    job.proc.once("close", (code) => {
      jobs.delete(id);
      if (code === 0) {
        rename(job.tmp, job.final).then(() => resolve(job.final), reject);
      } else {
        void rm(job.tmp).catch(() => {});
        reject(new Error(`ffmpeg exited ${code}: ${job.stderrTail.join("\n") || "(no stderr)"}`));
      }
    });
    job.proc.stdin.end();
  });
}

/** Kill the job and discard the partial file (cancel/error). */
export async function abortJob(id: number): Promise<void> {
  const job = jobs.get(id);
  if (!job) return;
  jobs.delete(id);
  try {
    job.proc.kill();
  } catch {
    /* already gone */
  }
  try {
    await rm(job.tmp);
  } catch {
    /* nothing to remove */
  }
}

/** Kill every live job (app quit). */
export function killAllFfmpeg(): void {
  for (const [, job] of jobs) {
    try {
      job.proc.kill();
    } catch {
      /* ignore */
    }
  }
  jobs.clear();
}
