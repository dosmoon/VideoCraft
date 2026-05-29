/**
 * Generate synthetic test media for the substrate spikes.
 *
 * The clip burns in its frame number (big, centred) and timecode (top-left)
 * so seek precision is verifiable by eye: seek to output time t, and the
 * frame number on screen must equal round(t * fps). Fixed 30-frame GOP
 * (-g 30 -sc_threshold 0) gives predictable keyframes for the seek spike.
 *
 * Requires ffmpeg on PATH. Run: `node spike-assets/gen-test-clips.mjs`
 * Output (.mp4) is gitignored; this script is the source of truth.
 */

import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
// Double-escaped colon: the filtergraph parser unescapes one level, so the
// drive colon needs "C\\:" to survive into the option value on Windows.
const font = "C\\\\:/Windows/Fonts/arial.ttf";

function clip(name, { size, rate, duration, source }) {
  const vf = [
    `drawtext=fontfile=${font}:text=%{eif\\\\:n\\\\:d}:fontsize=200:fontcolor=white:` +
      `x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5:boxborderw=28`,
    `drawtext=fontfile=${font}:text=%{pts\\\\:hms}:fontsize=56:fontcolor=yellow:` +
      `x=28:y=28:box=1:boxcolor=black@0.55:boxborderw=10`,
  ].join(",");
  const args = [
    "-y",
    "-f", "lavfi", "-i", `${source}=size=${size}:rate=${rate}:duration=${duration}`,
    "-vf", vf,
    "-c:v", "libx264", "-pix_fmt", "yuv420p",
    "-g", String(rate), "-keyint_min", String(rate), "-sc_threshold", "0",
    "-profile:v", "high", "-level", "4.0",
    "-movflags", "+faststart",
    join(here, name),
  ];
  console.log("ffmpeg", args.join(" "));
  const r = spawnSync("ffmpeg", args, { stdio: "inherit" });
  if (r.status !== 0) {
    console.error(`ffmpeg failed for ${name} (status ${r.status})`);
    process.exit(r.status ?? 1);
  }
}

// Primary clip: 1280x720, 30fps, 10s, testsrc2 background.
clip("test_clip.mp4", {
  size: "1280x720",
  rate: 30,
  duration: 10,
  source: "testsrc2",
});

// Second clip with a distinct look (smptebars) for the multi-segment concat
// spike — makes a cut between two sources obvious.
clip("test_clip_b.mp4", {
  size: "1280x720",
  rate: 30,
  duration: 10,
  source: "smptebars",
});

console.log("done");
