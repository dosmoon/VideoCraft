/**
 * SubtitleViewer — inspect one subtitle: its SRT text + the quality check
 * (structural / format-residue / language-purity issues) with a one-click
 * auto-fix. Faithful to the Tk srt_preview_pane + subtitles_dialogs check UI.
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type SubtitleCheck } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { color, radius, font, state as st } from "../../ui/tokens";
import { ArrowLeft, Check, Wrench, AlertCircle } from "../../ui/icons";

const ghostBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "5px 12px",
  background: color.bgHover,
  color: color.textPrimary,
  border: "none",
  borderRadius: radius.sm,
  fontSize: font.sm,
  cursor: "pointer",
};

function fmt(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

const SEV_COLOR: Record<string, string> = {
  hard: color.danger,
  fixable: st.partial,
  advisory: color.textMuted,
};

export function SubtitleViewer(props: {
  type: string;
  instance: string;
  lang: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { type, instance, lang, onClose, onChanged } = props;
  const [text, setText] = useState<string | null>(null);
  const [check, setCheck] = useState<SubtitleCheck | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const [t, c] = await Promise.all([
        rpc.readSubtitle(type, instance, lang),
        rpc.checkSubtitle(type, instance, lang),
      ]);
      setText(t.text);
      setCheck(c);
    } catch (err) {
      setError(fmt(err));
    }
  }, [type, instance, lang]);

  useEffect(() => {
    void load();
  }, [load]);

  const quickFix = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const c = await rpc.quickFixSubtitle(type, instance, lang);
      setCheck(c);
      const t = await rpc.readSubtitle(type, instance, lang);
      setText(t.text);
      onChanged();
    } catch (err) {
      setError(fmt(err));
    } finally {
      setBusy(false);
    }
  }, [type, instance, lang, onChanged]);

  return (
    <div style={{ maxWidth: 720 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <button onClick={onClose} style={{ ...ghostBtn, padding: "4px 10px" }}>
          <ArrowLeft size={14} strokeWidth={2} />
          {tr("material.back_btn_text")}
        </button>
        <strong style={{ fontSize: font.md, color: color.textPrimary }}>{lang}.srt</strong>
        {check && (
          <span style={{ fontSize: font.sm, color: color.textSecondary }}>
            {tr("material.subtitles.cue_count", { count: check.cue_count })}
            {check.hard > 0 && <span style={{ color: SEV_COLOR.hard }}> · {tr("material.subtitles.hard_count", { count: check.hard })}</span>}
            {check.fixable > 0 && <span style={{ color: SEV_COLOR.fixable }}> · {tr("material.subtitles.fixable_count", { count: check.fixable })}</span>}
            {check.advisory > 0 && <span style={{ color: SEV_COLOR.advisory }}> · {tr("material.subtitles.advisory_count", { count: check.advisory })}</span>}
            {check.hard === 0 && check.fixable === 0 && (
              <span style={{ color: st.done, display: "inline-flex", alignItems: "center", gap: 3 }}>
                {" "}
                · <Check size={13} strokeWidth={2.5} /> {tr("material.subtitles.no_hard_issues")}
              </span>
            )}
          </span>
        )}
        {check && check.fixable > 0 && (
          <button onClick={() => void quickFix()} disabled={busy} style={{ ...ghostBtn, marginLeft: "auto", color: st.partial }}>
            <Wrench size={13} strokeWidth={2} />
            {tr("material.subtitles.quick_fix_btn")}
          </button>
        )}
      </div>

      {error && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: color.danger, fontSize: font.sm, marginBottom: 8 }}>
          <AlertCircle size={14} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span>{error}</span>
        </div>
      )}

      {check && check.issues.length > 0 && (
        <div style={{ marginBottom: 10, display: "flex", flexDirection: "column", gap: 2 }}>
          {check.issues.slice(0, 30).map((iss, i) => (
            <div key={i} style={{ fontSize: font.xs, color: SEV_COLOR[iss.severity_class] ?? color.textSecondary }}>
              {iss.cue_index > 0 ? `#${iss.cue_index} ` : ""}
              {iss.message}
            </div>
          ))}
          {check.issues.length > 30 && (
            <div style={{ fontSize: font.xs, color: color.textMuted }}>…{tr("material.subtitles.issues_total", { count: check.issues.length })}</div>
          )}
        </div>
      )}

      <pre
        style={{
          margin: 0,
          padding: 10,
          background: color.bgInset,
          border: `1px solid ${color.borderSubtle}`,
          borderRadius: radius.sm,
          maxHeight: 360,
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
