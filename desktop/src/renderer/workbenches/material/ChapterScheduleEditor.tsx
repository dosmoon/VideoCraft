/**
 * ChapterScheduleEditor — edit a material's analysis.json chapter schedule. Loads
 * the raw envelope (material.read_analysis), lets the user edit each chapter's
 * start time + title, and saves through material.save_chapters (the server
 * normalizes: sort / end=next.start / drop degenerate / synth 00:00 + preserves
 * titles[] and per-chapter refined/key_points).
 *
 * refined / key_points are shown read-only and carried through on save. The source
 * video is PINNED at the top (DetailScaffold) so it stays on screen while the
 * chapter list scrolls below; seek / take-current act on that pinned video.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { rpc, RpcError } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { color, radius, font, state as st } from "../../ui/tokens";
import { DetailHeader, DetailScaffold } from "./detailChrome";

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
  padding: "4px 8px",
  background: color.bgInset,
  color: color.textPrimary,
  border: `1px solid ${color.border}`,
  borderRadius: radius.sm,
  fontSize: font.md,
};
const BTN: React.CSSProperties = {
  padding: "5px 14px",
  background: color.accent,
  color: "#fff",
  border: "none",
  borderRadius: radius.sm,
  fontSize: font.sm,
  cursor: "pointer",
};
const BTN_GHOST: React.CSSProperties = { ...BTN, background: color.bgHover, color: color.textPrimary };

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

  const seekTo = useCallback((c: Chapter) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = typeof c.start_sec === "number" ? c.start_sec : parseHMS(c.start);
  }, []);

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

  const header = (
    <DetailHeader
      onBack={onClose}
      title={filename}
      subtitle={tr("material.chapters.schedule_label")}
      right={
        <>
          {saving && <span style={{ fontSize: font.sm, color: color.accentText }}>{tr("material.chapters.saving")}</span>}
          {dirty && !saving && <span style={{ fontSize: font.sm, color: st.partial }}>{tr("material.chapters.unsaved")}</span>}
          <button onClick={() => void save()} disabled={saving || !dirty} style={{ ...BTN, opacity: saving || !dirty ? 0.5 : 1 }}>
            {tr("common.save")}
          </button>
        </>
      }
    />
  );

  const pinned = srcUrl ? (
    <video ref={videoRef} src={srcUrl} controls style={{ display: "block", width: "100%", maxHeight: "44vh", borderRadius: radius.sm, background: "#000" }} />
  ) : undefined;

  return (
    <DetailScaffold header={header} pinned={pinned}>
      {error && <div style={{ color: color.danger, fontSize: font.sm, marginBottom: 8 }}>✗ {error}</div>}
      {chapters === null ? (
        <div style={{ color: color.textMuted, fontSize: font.md }}>{tr("common.loading")}</div>
      ) : chapters.length === 0 ? (
        <div style={{ color: color.textMuted, fontSize: font.md }}>{tr("material.chapters.none")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {chapters.map((c, i) => (
            <div key={i} style={{ padding: "10px 12px", background: color.bgInset, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.sm }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input
                  value={c.start ?? ""}
                  disabled={saving}
                  onChange={(e) => edit(i, "start", e.target.value)}
                  style={{ ...INPUT, width: 96 }}
                  title={tr("material.chapters.start_time_title")}
                />
                {srcUrl && (
                  <>
                    <button onClick={() => seekTo(c)} disabled={saving} style={{ ...BTN_GHOST, padding: "4px 10px", fontSize: font.xs }} title={tr("material.chapters.seek_title")}>
                      {tr("material.chapters.seek_btn")}
                    </button>
                    <button onClick={() => takeCurrent(i)} disabled={saving} style={{ ...BTN_GHOST, padding: "4px 10px", fontSize: font.xs }} title={tr("material.chapters.take_current_title")}>
                      {tr("material.chapters.take_current_btn")}
                    </button>
                  </>
                )}
                <input
                  value={c.title ?? ""}
                  disabled={saving}
                  onChange={(e) => edit(i, "title", e.target.value)}
                  style={{ ...INPUT, flex: 1, minWidth: 0 }}
                  title={tr("material.chapters.title_field_title")}
                />
              </div>
              {(c.refined || (c.key_points && c.key_points.length > 0)) && (
                <div style={{ marginTop: 6, paddingLeft: 2, color: color.textMuted, fontSize: font.sm, lineHeight: 1.5 }}>
                  {c.refined}
                  {c.key_points && c.key_points.length > 0 && (
                    <ul style={{ margin: "3px 0 0", paddingLeft: 18 }}>
                      {c.key_points.map((kp, k) => (
                        <li key={k}>{kp}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          ))}
          <p style={{ color: color.textMuted, fontSize: font.xs, marginTop: 4 }}>{tr("material.chapters.save_hint")}</p>
        </div>
      )}
    </DetailScaffold>
  );
}
