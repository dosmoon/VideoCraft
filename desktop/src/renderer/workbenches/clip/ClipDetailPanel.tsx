/**
 * ClipDetailPanel — per-candidate detail editor (faithful port of
 * src/creations/clip/clip_editor.py::ClipDetailPanel).
 *
 * Shows the selected candidate's own preview (its own crop window), editable
 * start/end (with ±0.5s nudge + clamp), hook/outro/title/tags overrides, and a
 * read-only SRT cue list for the window. Every edit writes the candidate's
 * override via creation.update_config (clips_overrides_merge), then asks the
 * host to reload so the effective values + preview refresh — the new-arch
 * equivalent of the original's `_override` write + `_save_all` + re-push.
 *
 * Faithful semantics preserved verbatim from the Tk original:
 *   - time format "HH:MM:SS.mmm"; nudge step ±0.5s; clamp start<end-0.1, end>start+0.1.
 *   - text fields: empty input deletes the override key (absence = AI default),
 *     never stored as "".  tags split on whitespace into a list.
 *   - reset crop deletes crop_rect (→ centered default at render).
 *   - restore AI text deletes hook_text/outro_text/title/hashtags together.
 */

import { useCallback, useEffect, useState } from "react";
import { tr } from "../../i18n/tr";
import { rpc, RpcError, type Component } from "../../ipc/client";
import type { ClipOverride, HotclipCandidate } from "@creations/clip/types.js";
import type { SourceCue } from "@composition/components/index.js";
import {
  formatTimestamp,
  parseTimestamp,
  resolveStartEnd,
  resolveHookText,
  resolveOutroText,
  resolveTitle,
  resolveTags,
  resolveCrop,
} from "@creations/clip/mapping.js";
import { CropPreview } from "./CropPreview";
import type { CropRect } from "./cropEditor";

const NUDGE = 0.5; // seconds, mirrors clip_editor.py nudge buttons
const MIN_LEN = 0.1; // start < end - 0.1 invariant

export interface ClipDetailPanelProps {
  type: string;
  instance: string;
  candidateIndex: number;
  candidate: HotclipCandidate;
  override: ClipOverride | undefined;
  components: Component[];
  // Shared preview data (from useClipPreview) — source + SRT + geometry.
  srcPath: string;
  srtByLang: Record<string, readonly SourceCue[]>;
  lang: string;
  mode: "reframe" | "passthrough";
  aspect: { aw: number; ah: number };
  /** Called after any write so the host reloads config (refreshes overrides). */
  onChanged: () => void;
}

const FIELD_LABEL_STYLE: React.CSSProperties = {
  width: 56,
  display: "inline-block",
  color: "#999",
  fontSize: 12,
};
const ENTRY_STYLE: React.CSSProperties = {
  background: "#1a1a1e",
  color: "#ddd",
  border: "1px solid #333",
  borderRadius: 4,
  padding: "3px 6px",
  fontSize: 12,
};

export function ClipDetailPanel(props: ClipDetailPanelProps) {
  const {
    type,
    instance,
    candidateIndex,
    candidate,
    override,
    components,
    srcPath,
    srtByLang,
    lang,
    mode,
    aspect,
    onChanged,
  } = props;

  const [startSec, endSec] = resolveStartEnd(candidate, override);

  // Editable field state — typed freely, committed on blur/Enter. Reset to the
  // effective values whenever the candidate or its override changes.
  const [startText, setStartText] = useState("");
  const [endText, setEndText] = useState("");
  const [hookText, setHookText] = useState("");
  const [outroText, setOutroText] = useState("");
  const [titleText, setTitleText] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [cropRect, setCropRect] = useState<CropRect | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const [s, e] = resolveStartEnd(candidate, override);
    setStartText(formatTimestamp(s));
    setEndText(formatTimestamp(e));
    setHookText(resolveHookText(candidate, override));
    setOutroText(resolveOutroText(candidate, override));
    setTitleText(resolveTitle(candidate, override));
    setTagsText(resolveTags(candidate, override).join(" "));
    setCropRect(resolveCrop(override));
    setError("");
  }, [candidateIndex, candidate, override]);

  // Write this candidate's override (null values delete keys) → reload.
  const writeOverride = useCallback(
    async (patch: Record<string, unknown>) => {
      setError("");
      try {
        await rpc.updateConfig(type, instance, {
          clips_overrides_merge: { [String(candidateIndex)]: patch },
        });
        onChanged();
      } catch (err) {
        setError(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
      }
    },
    [type, instance, candidateIndex, onChanged],
  );

  // ── time entries (clamp mirrors clip_editor._on_time_entry_blur) ────────────
  const commitStart = useCallback(() => {
    let secs = parseTimestamp(startText);
    secs = Math.max(0, Math.min(endSec - MIN_LEN, secs));
    if (Math.abs(secs - startSec) < 1e-3) {
      setStartText(formatTimestamp(secs));
      return;
    }
    setStartText(formatTimestamp(secs));
    void writeOverride({ start_sec: secs });
  }, [startText, startSec, endSec, writeOverride]);

  const commitEnd = useCallback(() => {
    let secs = parseTimestamp(endText);
    secs = Math.max(startSec + MIN_LEN, secs);
    if (Math.abs(secs - endSec) < 1e-3) {
      setEndText(formatTimestamp(secs));
      return;
    }
    setEndText(formatTimestamp(secs));
    void writeOverride({ end_sec: secs });
  }, [endText, startSec, endSec, writeOverride]);

  const nudgeStart = useCallback(
    (delta: number) => {
      const v = Math.max(0, Math.min(endSec - MIN_LEN, startSec + delta));
      void writeOverride({ start_sec: v });
    },
    [startSec, endSec, writeOverride],
  );
  const nudgeEnd = useCallback(
    (delta: number) => {
      const v = Math.max(startSec + MIN_LEN, endSec + delta);
      void writeOverride({ end_sec: v });
    },
    [startSec, endSec, writeOverride],
  );

  // ── text entries (empty → delete key, mirrors _on_text_entry_blur) ──────────
  const commitText = useCallback(
    (key: "hook_text" | "outro_text" | "title", raw: string) => {
      void writeOverride({ [key]: raw.trim() ? raw : null });
    },
    [writeOverride],
  );
  const commitTags = useCallback(
    (raw: string) => {
      const tags = raw.split(/\s+/).filter((s) => s.length > 0);
      void writeOverride({ hashtags: tags.length ? tags : null });
    },
    [writeOverride],
  );

  // ── crop (per-candidate; reset deletes the key) ─────────────────────────────
  const onCropChange = useCallback(
    (rect: CropRect) => {
      setCropRect(rect);
      void writeOverride({ crop_rect: rect });
    },
    [writeOverride],
  );
  const onResetCrop = useCallback(() => {
    setCropRect(null); // → CropPreview re-centers
    void writeOverride({ crop_rect: null });
  }, [writeOverride]);

  // ── restore AI text (deletes the four text overrides together) ──────────────
  const onRestoreAiText = useCallback(() => {
    if (!window.confirm(tr("clip.detail.restore_ai_confirm"))) return;
    void writeOverride({ hook_text: null, outro_text: null, title: null, hashtags: null });
  }, [writeOverride]);

  // SRT cues overlapping the window, in source time (mirrors _cues_for_window).
  const cues = (srtByLang[lang] ?? []).filter((c) => c.sourceEnd > startSec && c.sourceStart < endSec);

  const scoreLabel = candidate.score ?? "-";

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
      <CropPreview
        srcPath={srcPath}
        candidate={candidate}
        {...(override ? { override } : {})}
        components={components}
        srtByLang={srtByLang}
        mode={mode}
        aspect={aspect}
        fullSource={false}
        showCards
        cropRect={cropRect}
        onCropChange={onCropChange}
      />

      {error && <p style={{ color: "#ff6b6b", fontSize: 12, margin: 0 }}>✗ {error}</p>}

      {/* Time row */}
      <fieldset style={{ border: "1px solid #2a2a2e", borderRadius: 6, padding: "8px 10px" }}>
        <legend style={{ color: "#888", fontSize: 11, padding: "0 4px" }}>{tr("clip.detail.time_legend")}</legend>
        {(
          [
            [tr("clip.detail.start_label"), startText, setStartText, commitStart, nudgeStart],
            [tr("clip.detail.end_label"), endText, setEndText, commitEnd, nudgeEnd],
          ] as const
        ).map(([label, value, setValue, commit, nudge]) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
            <span style={FIELD_LABEL_STYLE}>{label}</span>
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit();
              }}
              style={{ ...ENTRY_STYLE, width: 110, fontVariantNumeric: "tabular-nums" }}
            />
            <button onClick={() => nudge(-NUDGE)} style={nudgeBtn}>−0.5</button>
            <button onClick={() => nudge(+NUDGE)} style={nudgeBtn}>+0.5</button>
          </div>
        ))}
        <div style={{ color: "#777", fontSize: 12 }}>
          {tr("clip.detail.duration_score", { dur: (endSec - startSec).toFixed(1), score: String(scoreLabel) })}
        </div>
      </fieldset>

      {/* Text overrides */}
      <fieldset style={{ border: "1px solid #2a2a2e", borderRadius: 6, padding: "8px 10px" }}>
        <legend style={{ color: "#888", fontSize: 11, padding: "0 4px" }}>{tr("clip.detail.text_legend")}</legend>
        {(
          [
            ["Hook", hookText, setHookText, () => commitText("hook_text", hookText)],
            ["Outro", outroText, setOutroText, () => commitText("outro_text", outroText)],
            [tr("clip.detail.title_label"), titleText, setTitleText, () => commitText("title", titleText)],
            [tr("clip.detail.tags_label"), tagsText, setTagsText, () => commitTags(tagsText)],
          ] as const
        ).map(([label, value, setValue, commit]) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
            <span style={FIELD_LABEL_STYLE}>{label}</span>
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit();
              }}
              style={{ ...ENTRY_STYLE, flex: 1 }}
            />
          </div>
        ))}
      </fieldset>

      {/* SRT cue list (read-only, source time) */}
      <fieldset style={{ border: "1px solid #2a2a2e", borderRadius: 6, padding: "8px 10px" }}>
        <legend style={{ color: "#888", fontSize: 11, padding: "0 4px" }}>{tr("clip.detail.subtitles_legend")}</legend>
        <div
          style={{
            maxHeight: 130,
            overflow: "auto",
            background: "#161618",
            borderRadius: 4,
            padding: "6px 8px",
            fontFamily: "Consolas, monospace",
            fontSize: 12,
            color: "#bbb",
            whiteSpace: "pre-wrap",
          }}
        >
          {cues.length === 0 ? (
            <span style={{ color: "#666" }}>{tr("clip.detail.no_subtitles")}</span>
          ) : (
            cues.map((c, i) => (
              <div key={i}>
                [{formatTimestamp(c.sourceStart)}]&nbsp;&nbsp;{c.text}
              </div>
            ))
          )}
        </div>
      </fieldset>

      {/* Actions */}
      <div style={{ display: "flex", gap: 8 }}>
        {mode === "reframe" && (
          <button onClick={onResetCrop} style={actionBtn}>
            {tr("clip.detail.reset_crop")}
          </button>
        )}
        <button onClick={onRestoreAiText} style={actionBtn}>
          {tr("clip.detail.restore_ai_text")}
        </button>
      </div>
    </div>
  );
}

const nudgeBtn: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ccc",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "2px 8px",
  fontSize: 12,
  cursor: "pointer",
};
const actionBtn: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ddd",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "4px 12px",
  fontSize: 12,
  cursor: "pointer",
};
