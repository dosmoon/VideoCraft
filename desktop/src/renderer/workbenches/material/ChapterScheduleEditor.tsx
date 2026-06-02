/**
 * ChapterScheduleEditor — edit a material's analysis.json chapter schedule. Loads
 * the raw envelope (material.read_analysis), lets the user edit each chapter's
 * start time + title, and saves through material.save_chapters (the server
 * normalizes: sort / end=next.start / drop degenerate / synth 00:00 + preserves
 * titles[] and per-chapter refined/key_points).
 *
 * refined / key_points are shown read-only and carried through on save (so edits
 * to start/title don't lose the AI narrative). Faithful to the Tk chapter_editor;
 * the seek-to-time video preview is deferred.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { rpc, RpcError } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { ArrowLeft } from "../../ui/icons";

// "HH:MM:SS" / "MM:SS" → seconds (0 on parse failure).
function parseHMS(s: string): number {
  const parts = (s || "").trim().split(":").map(Number);
  if (parts.some((n) => Number.isNaN(n))) return 0;
  if (parts.length === 3) return parts[0]! * 3600 + parts[1]! * 60 + parts[2]!;
  if (parts.length === 2) return parts[0]! * 60 + parts[1]!;
  return parts[0] ?? 0;
}

// seconds → "HH:MM:SS".
function fmtHMS(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

interface Chapter {
  start: string;
  start_sec?: number;
  end?: string;
  title: string;
  refined?: string;
  key_points?: string[];
  [key: string]: unknown;
}

const INPUT: React.CSSProperties = {
  padding: "3px 6px",
  background: "#1a1a1e",
  color: "#ddd",
  border: "1px solid #333",
  borderRadius: 3,
  fontSize: 12,
};
const BTN: React.CSSProperties = {
  padding: "5px 14px",
  background: "#2d6cdf",
  color: "#fff",
  border: "none",
  borderRadius: 5,
  fontSize: 13,
  cursor: "pointer",
};
const BTN_GHOST: React.CSSProperties = { ...BTN, background: "#2a2a2e", color: "#ddd" };

function fmt(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

export function ChapterScheduleEditor(props: {
  type: string;
  instance: string;
  filename: string;
  lang: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { type, instance, filename, lang, onClose, onSaved } = props;
  const [chapters, setChapters] = useState<Chapter[] | null>(null);
  const [srcUrl, setSrcUrl] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const env = await rpc.readAnalysis(type, instance, filename);
        const chs = (env["chapters"] as Chapter[]) ?? [];
        if (alive) setChapters(chs);
        // Source video for seek-preview (optional — editor still works without it).
        const path = await rpc.getArtifact(type, instance, "source");
        if (alive) setSrcUrl(path ? window.vc.mediaUrl(path) : "");
      } catch (err) {
        if (alive) setError(fmt(err));
      }
    })();
    return () => {
      alive = false;
    };
  }, [type, instance, filename]);

  const edit = useCallback((i: number, field: "start" | "title", value: string) => {
    setChapters((prev) => (prev ? prev.map((c, j) => (j === i ? { ...c, [field]: value } : c)) : prev));
    setDirty(true);
  }, []);

  // Seek the preview video to a chapter's start.
  const seekTo = useCallback((c: Chapter) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = typeof c.start_sec === "number" ? c.start_sec : parseHMS(c.start);
  }, []);

  // Set a chapter's start to the video's current playback position.
  const takeCurrent = useCallback(
    (i: number) => {
      const v = videoRef.current;
      if (!v) return;
      edit(i, "start", fmtHMS(v.currentTime));
    },
    [edit],
  );

  const save = useCallback(async () => {
    if (!chapters) return;
    setSaving(true);
    setError("");
    try {
      // Send start/title/refined/key_points; the server normalizes the rest.
      const payload = chapters.map((c) => ({
        start: c.start,
        title: c.title,
        refined: c.refined ?? "",
        key_points: c.key_points ?? [],
      }));
      const env = await rpc.saveChapters(type, instance, filename, payload, lang);
      setChapters((env["chapters"] as Chapter[]) ?? []);
      setDirty(false);
      onSaved();
    } catch (err) {
      setError(fmt(err));
    } finally {
      setSaving(false);
    }
  }, [chapters, type, instance, filename, lang, onSaved]);

  return (
    <div style={{ maxWidth: 720 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <button onClick={onClose} style={{ ...BTN_GHOST, display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px" }}>
          <ArrowLeft size={14} strokeWidth={2} />
          {tr("material.back_btn_text")}
        </button>
        <strong style={{ fontSize: 13 }}>{filename}</strong>
        <span style={{ color: "#777", fontSize: 12 }}>{tr("material.chapters.schedule_label")}</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {saving && <span style={{ fontSize: 11, color: "#4a9eff" }}>{tr("material.chapters.saving")}</span>}
          {dirty && !saving && <span style={{ fontSize: 11, color: "#d9a441" }}>{tr("material.chapters.unsaved")}</span>}
          <button onClick={() => void save()} disabled={saving || !dirty} style={BTN}>
            {tr("common.save")}
          </button>
        </div>
      </div>

      {error && <div style={{ color: "#ff6b6b", fontSize: 12, marginBottom: 8 }}>✗ {error}</div>}

      {srcUrl && (
        <video
          ref={videoRef}
          src={srcUrl}
          controls
          style={{ display: "block", width: "100%", maxHeight: 280, marginBottom: 10, borderRadius: 4, background: "#000" }}
        />
      )}

      {chapters === null ? (
        <div style={{ color: "#666", fontSize: 13 }}>{tr("common.loading")}</div>
      ) : chapters.length === 0 ? (
        <div style={{ color: "#666", fontSize: 13 }}>{tr("material.chapters.none")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {chapters.map((c, i) => (
            <div
              key={i}
              style={{ padding: "8px 10px", background: "#1c1c20", border: "1px solid #2a2a2e", borderRadius: 5 }}
            >
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input
                  value={c.start ?? ""}
                  disabled={saving}
                  onChange={(e) => edit(i, "start", e.target.value)}
                  style={{ ...INPUT, width: 92 }}
                  title={tr("material.chapters.start_time_title")}
                />
                {srcUrl && (
                  <>
                    <button
                      onClick={() => seekTo(c)}
                      disabled={saving}
                      style={{ ...BTN_GHOST, padding: "3px 8px", fontSize: 11 }}
                      title={tr("material.chapters.seek_title")}
                    >
                      {tr("material.chapters.seek_btn")}
                    </button>
                    <button
                      onClick={() => takeCurrent(i)}
                      disabled={saving}
                      style={{ ...BTN_GHOST, padding: "3px 8px", fontSize: 11 }}
                      title={tr("material.chapters.take_current_title")}
                    >
                      {tr("material.chapters.take_current_btn")}
                    </button>
                  </>
                )}
                <input
                  value={c.title ?? ""}
                  disabled={saving}
                  onChange={(e) => edit(i, "title", e.target.value)}
                  style={{ ...INPUT, flex: 1 }}
                  title={tr("material.chapters.title_field_title")}
                />
              </div>
              {(c.refined || (c.key_points && c.key_points.length > 0)) && (
                <div style={{ marginTop: 4, paddingLeft: 2, color: "#888", fontSize: 11 }}>
                  {c.refined}
                  {c.key_points && c.key_points.length > 0 && (
                    <ul style={{ margin: "2px 0 0", paddingLeft: 16 }}>
                      {c.key_points.map((kp, k) => (
                        <li key={k}>{kp}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          ))}
          <p style={{ color: "#666", fontSize: 11, marginTop: 4 }}>
            {tr("material.chapters.save_hint")}
          </p>
        </div>
      )}
    </div>
  );
}
