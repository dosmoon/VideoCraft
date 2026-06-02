/**
 * AnalysisTextViewer — read-only viewer for text analysis artifacts
 * (transcript.md / chapter_transcript.md). The chapters (analysis.json) kind is
 * edited via ChapterScheduleEditor; hotclips.json is rendered structured via
 * HotclipsViewer. Fills the detail panel (DetailScaffold).
 */

import { useEffect, useState } from "react";
import { rpc, RpcError } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { color, radius, font } from "../../ui/tokens";
import { AlertCircle } from "../../ui/icons";
import { DetailHeader, DetailScaffold } from "./detailChrome";

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
    <DetailScaffold scroll="none" header={<DetailHeader onBack={onClose} title={lang.toUpperCase()} subtitle={title} />}>
      {error && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: color.danger, fontSize: font.sm, marginBottom: 8, flexShrink: 0 }}>
          <AlertCircle size={14} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span>{error}</span>
        </div>
      )}
      <pre
        style={{
          margin: 0,
          padding: 12,
          flex: 1,
          minHeight: 0,
          background: color.bgInset,
          border: `1px solid ${color.borderSubtle}`,
          borderRadius: radius.sm,
          overflow: "auto",
          fontSize: font.md,
          color: color.textSecondary,
          whiteSpace: "pre-wrap",
          fontFamily: "ui-monospace, monospace",
          lineHeight: 1.6,
        }}
      >
        {text ?? tr("common.loading")}
      </pre>
    </DetailScaffold>
  );
}
