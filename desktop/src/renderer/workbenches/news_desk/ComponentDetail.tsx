/**
 * Read-only detail lists for the news_desk Style tab — the views the generic
 * primitive PropertyPanel can't render, filling the gap the legacy Tk panels
 * had (task.md 续28):
 *   - SubtitleCueList — the selected subtitle's snapshot SRT cues (start · text).
 *   - ChapterScheduleList — the imported chapter rows (start · title).
 *
 * Both rows are click-to-seek. news_desk composes the WHOLE source (identity
 * time map), so a cue/chapter's source-time start is also its output-time
 * position — seeking straight to it is correct. Per-row editing is deferred
 * (the read-only + seek step called out in 续28); this is display only.
 */

import type { SourceCue } from "@composition/components/index.js";
import type { NewsDeskChapterRow } from "@creations/news_desk/types.js";
import { formatTimestamp } from "@creations/clip/mapping.js";

const panel: React.CSSProperties = {
  border: "1px solid #2a2a2e",
  borderRadius: 6,
  padding: "8px 10px",
  marginTop: 12,
};
const legendStyle: React.CSSProperties = { color: "#888", fontSize: 11, padding: "0 4px" };
const listBox: React.CSSProperties = {
  maxHeight: 180,
  overflow: "auto",
  background: "#161618",
  borderRadius: 4,
  padding: "2px 0",
};
const rowBtn: React.CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "baseline",
  width: "100%",
  textAlign: "left",
  background: "transparent",
  border: "none",
  borderBottom: "1px solid #1f1f22",
  padding: "4px 8px",
  cursor: "pointer",
  fontSize: 12,
  color: "#ccc",
};
const tsCol: React.CSSProperties = {
  flex: "0 0 auto",
  color: "#6fa8ff",
  fontFamily: "Consolas, monospace",
  fontVariantNumeric: "tabular-nums",
};
const textCol: React.CSSProperties = {
  flex: 1,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const emptyStyle: React.CSSProperties = { color: "#666", fontSize: 12, padding: "6px 8px" };

/** Selected subtitle's cue list (read-only, click row to seek). */
export function SubtitleCueList(props: {
  cues: readonly SourceCue[] | undefined;
  onSeek: (sec: number) => void;
}) {
  const { cues, onSeek } = props;
  return (
    <fieldset style={panel}>
      <legend style={legendStyle}>字幕{cues && cues.length ? `（${cues.length}）` : ""}</legend>
      <div style={listBox}>
        {!cues || cues.length === 0 ? (
          <div style={emptyStyle}>（未导入字幕）</div>
        ) : (
          cues.map((c, i) => (
            <button key={i} onClick={() => onSeek(c.sourceStart)} style={rowBtn} title="跳到此处">
              <span style={tsCol}>{formatTimestamp(c.sourceStart)}</span>
              <span style={textCol}>{c.text}</span>
            </button>
          ))
        )}
      </div>
    </fieldset>
  );
}

/** Imported chapter schedule (read-only, click row to seek). */
export function ChapterScheduleList(props: {
  schedule: NewsDeskChapterRow[] | undefined;
  onSeek: (sec: number) => void;
}) {
  const { schedule, onSeek } = props;
  return (
    <fieldset style={panel}>
      <legend style={legendStyle}>章节{schedule && schedule.length ? `（${schedule.length}）` : ""}</legend>
      <div style={listBox}>
        {!schedule || schedule.length === 0 ? (
          <div style={emptyStyle}>（未导入章节）</div>
        ) : (
          schedule.map((row, i) => (
            <button key={i} onClick={() => onSeek(row.start_sec)} style={rowBtn} title="跳到此处">
              <span style={tsCol}>{formatTimestamp(row.start_sec)}</span>
              <span style={textCol}>{row.title || "（无标题）"}</span>
            </button>
          ))
        )}
      </div>
    </fieldset>
  );
}
