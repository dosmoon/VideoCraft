/**
 * Dubbing component edit-UI fields. Unlike the overlay components, "dubbing" does
 * not compile to a visual track — the news_desk assembler consumes it to build
 * the audio track(s) (replace original audio, or mix under it). These specs only
 * drive the property panel (mode / gain / offset). The audio file itself is
 * imported (snapshotted) separately, like a subtitle's SRT.
 */

import type { FieldSpec } from "./fieldSpec.js";

export const dubbingFields: readonly FieldSpec[] = [
  {
    key: "mode",
    control: "select",
    labelKey: "news_desk.dub.field_mode",
    options: ["replace", "mix"],
    optionLabelKeys: {
      replace: "news_desk.dub.mode_replace",
      mix: "news_desk.dub.mode_mix",
    },
  },
  {
    key: "gain_db",
    control: "number",
    labelKey: "news_desk.dub.field_gain",
    step: 1,
    display: { factor: 1, step: 1, decimals: 0, suffix: "dB" },
  },
  {
    // Original-audio level — only meaningful in `mix` (replace drops the original).
    key: "source_gain_db",
    control: "number",
    labelKey: "news_desk.dub.field_source_gain",
    step: 1,
    display: { factor: 1, step: 1, decimals: 0, suffix: "dB" },
    visibleWhen: (c) => c.mode === "mix",
  },
  {
    key: "offset_sec",
    control: "number",
    labelKey: "news_desk.dub.field_offset",
    step: 0.1,
    display: { factor: 1, step: 0.1, decimals: 1, suffix: "s" },
  },
];
