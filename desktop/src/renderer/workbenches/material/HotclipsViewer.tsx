/**
 * HotclipsViewer — read-only structured view of a hotclips.json analysis
 * artifact (the AI-proposed short-clip candidates). Mirrors the chapter editor's
 * shape — source video pinned at top, cards scrolling below, per-card seek — but
 * is read-only (hotclips has no save semantics). Replaces the old raw-JSON dump.
 *
 * Reads the same envelope RPC as ChapterScheduleEditor (material.read_analysis →
 * env.clips[]); each clip = start/end/duration_sec/hook/outro/why_viral/score/
 * suggested_title/suggested_hashtags[]/transcript.
 */

import { useEffect, useRef, useState } from "react";
import { rpc, RpcError } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { color, radius, font, state as st } from "../../ui/tokens";
import { DetailHeader, DetailScaffold } from "./detailChrome";

interface Clip {
  start?: string;
  end?: string;
  duration_sec?: number;
  hook?: string;
  outro?: string;
  why_viral?: string;
  score?: number;
  suggested_title?: string;
  suggested_hashtags?: string[];
  transcript?: string;
}

function parseHMS(s: string): number {
  const parts = (s || "").trim().split(":").map(Number);
  if (parts.some((n) => Number.isNaN(n))) return 0;
  if (parts.length === 3) return parts[0]! * 3600 + parts[1]! * 60 + parts[2]!;
  if (parts.length === 2) return parts[0]! * 60 + parts[1]!;
  return parts[0] ?? 0;
}

const ghostBtn: React.CSSProperties = {
  padding: "4px 10px",
  background: color.bgHover,
  color: color.textPrimary,
  border: "none",
  borderRadius: radius.sm,
  fontSize: font.xs,
  cursor: "pointer",
  flexShrink: 0,
};

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 6, fontSize: font.sm, lineHeight: 1.5 }}>
      <span style={{ color: color.textMuted }}>{label} </span>
      <span style={{ color: color.textSecondary }}>{children}</span>
    </div>
  );
}

export function HotclipsViewer(props: {
  type: string;
  instance: string;
  lang: string;
  title: string;
  onClose: () => void;
}) {
  const { type, instance, lang, title, onClose } = props;
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [srcUrl, setSrcUrl] = useState("");
  const [error, setError] = useState("");
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const env = await rpc.readAnalysis(type, instance, `${lang}.hotclips.json`);
        if (alive) setClips((env["clips"] as Clip[]) ?? []);
        const path = await rpc.getArtifact(type, instance, "source");
        if (alive) setSrcUrl(path ? window.vc.mediaUrl(path) : "");
      } catch (err) {
        if (alive) setError(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
      }
    })();
    return () => {
      alive = false;
    };
  }, [type, instance, lang]);

  const seekTo = (c: Clip) => {
    const v = videoRef.current;
    if (v && c.start) v.currentTime = parseHMS(c.start);
  };

  const pinned = srcUrl ? (
    <video ref={videoRef} src={srcUrl} controls style={{ display: "block", width: "100%", maxHeight: "44vh", borderRadius: radius.sm, background: "#000" }} />
  ) : undefined;

  return (
    <DetailScaffold header={<DetailHeader onBack={onClose} title={lang.toUpperCase()} subtitle={title} />} pinned={pinned}>
      {error && <div style={{ color: color.danger, fontSize: font.sm, marginBottom: 8 }}>✗ {error}</div>}
      {clips === null ? (
        <div style={{ color: color.textMuted, fontSize: font.md }}>{tr("common.loading")}</div>
      ) : clips.length === 0 ? (
        <div style={{ color: color.textMuted, fontSize: font.md }}>{tr("material.hotclips.none")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {clips.map((c, i) => (
            <div key={i} style={{ padding: "12px 14px", background: color.bgInset, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.md }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: color.textMuted, fontSize: font.sm, flexShrink: 0 }}>#{i + 1}</span>
                <strong style={{ flex: 1, minWidth: 0, fontSize: font.md, color: color.textPrimary }}>
                  {c.suggested_title || tr("material.hotclips.untitled")}
                </strong>
                {typeof c.score === "number" && (
                  <span style={{ flexShrink: 0, fontSize: font.xs, color: st.partial, border: `1px solid rgba(217,162,58,0.5)`, borderRadius: radius.pill, padding: "0 8px", lineHeight: "16px" }}>
                    {tr("material.hotclips.score", { score: String(c.score) })}
                  </span>
                )}
                {srcUrl && c.start && (
                  <button onClick={() => seekTo(c)} style={ghostBtn} title={tr("material.chapters.seek_title")}>
                    {tr("material.chapters.seek_btn")}
                  </button>
                )}
              </div>
              <div style={{ marginTop: 4, fontSize: font.xs, color: color.textMuted }}>
                {c.start}–{c.end}
                {typeof c.duration_sec === "number" ? ` · ${c.duration_sec}s` : ""}
              </div>

              {c.hook && <Labeled label={tr("material.hotclips.hook")}>{c.hook}</Labeled>}
              {c.outro && <Labeled label={tr("material.hotclips.outro")}>{c.outro}</Labeled>}
              {c.why_viral && <Labeled label={tr("material.hotclips.why_viral")}>{c.why_viral}</Labeled>}

              {c.suggested_hashtags && c.suggested_hashtags.length > 0 && (
                <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {c.suggested_hashtags.map((h, k) => (
                    <span key={k} style={{ fontSize: font.xs, color: color.accentText, background: color.accentSoft, borderRadius: radius.pill, padding: "2px 8px" }}>
                      {h.startsWith("#") ? h : `#${h}`}
                    </span>
                  ))}
                </div>
              )}

              {c.transcript && (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ fontSize: font.sm, color: color.textMuted, cursor: "pointer" }}>{tr("material.hotclips.transcript")}</summary>
                  <div style={{ marginTop: 4, fontSize: font.sm, color: color.textSecondary, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{c.transcript}</div>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
    </DetailScaffold>
  );
}
