/**
 * AnalysisTextViewer — read-only viewer for non-chapter analysis artifacts
 * (transcript.md / chapter_transcript.md / hotclips.json). The chapters
 * (analysis.json) kind is edited via ChapterScheduleEditor instead.
 */

import { useEffect, useState } from "react";
import { rpc, RpcError } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { color, radius, font } from "../../ui/tokens";
import { ArrowLeft, AlertCircle } from "../../ui/icons";

export function AnalysisTextViewer(props: {
  type: string;
  instance: string;
  lang: string;
  kind: string;
  title: string;
  onClose: () => void;
}) {
  const { type, instance, lang, kind, title, onClose } = props;
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void rpc
      .readAnalysisText(type, instance, lang, kind)
      .then((r) => alive && setText(r.text))
      .catch((err) =>
        alive && setError(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err)),
      );
    return () => {
      alive = false;
    };
  }, [type, instance, lang, kind]);

  return (
    <div style={{ maxWidth: 720 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <button
          onClick={onClose}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 10px",
            background: color.bgHover,
            color: color.textPrimary,
            border: "none",
            borderRadius: radius.sm,
            fontSize: font.sm,
            cursor: "pointer",
          }}
        >
          <ArrowLeft size={14} strokeWidth={2} />
          {tr("material.back_btn_text")}
        </button>
        <strong style={{ fontSize: font.md, color: color.textPrimary }}>{lang}</strong>
        <span style={{ color: color.textMuted, fontSize: font.sm }}>{title}</span>
      </div>
      {error && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: color.danger, fontSize: font.sm, marginBottom: 8 }}>
          <AlertCircle size={14} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span>{error}</span>
        </div>
      )}
      <pre
        style={{
          margin: 0,
          padding: 10,
          background: color.bgInset,
          border: `1px solid ${color.borderSubtle}`,
          borderRadius: radius.sm,
          maxHeight: 420,
          overflow: "auto",
          fontSize: font.sm,
          color: color.textSecondary,
          whiteSpace: "pre-wrap",
          fontFamily: "ui-monospace, monospace",
        }}
      >
        {text ?? tr("common.loading")}
      </pre>
    </div>
  );
}
