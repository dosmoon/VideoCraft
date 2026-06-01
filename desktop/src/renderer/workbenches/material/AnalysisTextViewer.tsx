/**
 * AnalysisTextViewer — read-only viewer for non-chapter analysis artifacts
 * (transcript.md / chapter_transcript.md / hotclips.json). The chapters
 * (analysis.json) kind is edited via ChapterScheduleEditor instead.
 */

import { useEffect, useState } from "react";
import { rpc, RpcError } from "../../ipc/client";
import { tr } from "../../i18n/tr";

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
          style={{ padding: "3px 10px", background: "#2a2a2e", color: "#ddd", border: "none", borderRadius: 5, fontSize: 12, cursor: "pointer" }}
        >
          {tr("material.back_btn")}
        </button>
        <strong style={{ fontSize: 13 }}>{lang}</strong>
        <span style={{ color: "#777", fontSize: 12 }}>{title}</span>
      </div>
      {error && <div style={{ color: "#ff6b6b", fontSize: 12, marginBottom: 8 }}>✗ {error}</div>}
      <pre
        style={{
          margin: 0,
          padding: 10,
          background: "#161619",
          border: "1px solid #2a2a2e",
          borderRadius: 5,
          maxHeight: 420,
          overflow: "auto",
          fontSize: 12,
          color: "#cdd",
          whiteSpace: "pre-wrap",
          fontFamily: "ui-monospace, monospace",
        }}
      >
        {text ?? tr("common.loading")}
      </pre>
    </div>
  );
}
