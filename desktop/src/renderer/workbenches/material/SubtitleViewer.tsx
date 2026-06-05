/**
 * SubtitleViewer — inspect one subtitle: its SRT text + the quality check
 * (structural / format-residue / language-purity issues) with a one-click
 * auto-fix. Faithful to the Tk srt_preview_pane + subtitles_dialogs check UI.
 * Fills the detail panel (DetailScaffold): the SRT block grows to the panel
 * height instead of a fixed maxHeight.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { rpc, RpcError, type SubtitleCheck } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { color, radius, font, state as st } from "../../ui/tokens";
import { Check, Wrench, AlertCircle } from "../../ui/icons";
import { DetailHeader, DetailScaffold } from "./detailChrome";

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

type Cue = { timing: string; content: string };

// Parse raw SRT into cues, indexed BY POSITION (0-based) to match
// subtitle_check's enumerate(cues, start=1) cue_index — not the SRT sequence
// number, which can drift from position in malformed files.
function parseCues(srt: string): Cue[] {
  const out: Cue[] = [];
  for (const block of srt.replace(/\r\n/g, "\n").trim().split(/\n\n+/)) {
    if (!block.trim()) continue;
    const lines = block.split("\n");
    let i = 0;
    if (/^\d+$/.test((lines[i] ?? "").trim())) i++; // SRT sequence number
    let timing = "";
    const tline = lines[i] ?? "";
    if (tline.includes("-->")) {
      timing = tline.trim();
      i++;
    }
    out.push({ timing, content: lines.slice(i).join("\n") });
  }
  return out;
}

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
  const [highlight, setHighlight] = useState(0); // 1-based cue currently flashed

  const cues = useMemo(() => (text ? parseCues(text) : []), [text]);
  const cueRefs = useRef<(HTMLDivElement | null)[]>([]);

  // Clicking a check issue scrolls its cue into view + flashes it. cue_index is
  // 1-based; file-level issues (cue_index 0) aren't jumpable.
  const jumpTo = useCallback((cueIndex: number) => {
    if (cueIndex <= 0) return;
    cueRefs.current[cueIndex - 1]?.scrollIntoView({ block: "center", behavior: "smooth" });
    setHighlight(cueIndex);
    window.setTimeout(() => setHighlight((h) => (h === cueIndex ? 0 : h)), 1500);
  }, []);

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

  const summary = check && (
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
  );

  const quickFixBtn = check && check.fixable > 0 && (
    <button onClick={() => void quickFix()} disabled={busy} style={{ ...ghostBtn, color: st.partial }}>
      <Wrench size={13} strokeWidth={2} />
      {tr("material.subtitles.quick_fix_btn")}
    </button>
  );

  return (
    <DetailScaffold
      scroll="none"
      header={<DetailHeader onBack={onClose} title={`${lang}.srt`} meta={summary} right={quickFixBtn} />}
    >
      {error && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: color.danger, fontSize: font.sm, marginBottom: 8, flexShrink: 0 }}>
          <AlertCircle size={14} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span>{error}</span>
        </div>
      )}

      {check && check.issues.length > 0 && (
        <div style={{ marginBottom: 10, display: "flex", flexDirection: "column", gap: 2, flexShrink: 0, maxHeight: "30%", overflowY: "auto" }}>
          {check.issues.slice(0, 30).map((iss, i) => {
            const jumpable = iss.cue_index > 0;
            return (
              <div
                key={i}
                onClick={jumpable ? () => jumpTo(iss.cue_index) : undefined}
                title={jumpable ? tr("material.subtitles.jump_to_cue", { n: iss.cue_index }) : undefined}
                style={{
                  fontSize: font.xs,
                  color: SEV_COLOR[iss.severity_class] ?? color.textSecondary,
                  cursor: jumpable ? "pointer" : "default",
                  textDecoration: jumpable ? "underline dotted" : "none",
                  textUnderlineOffset: 2,
                }}
              >
                {jumpable ? `#${iss.cue_index} ` : ""}
                {iss.message}
              </div>
            );
          })}
          {check.issues.length > 30 && (
            <div style={{ fontSize: font.xs, color: color.textMuted }}>…{tr("material.subtitles.issues_total", { count: check.issues.length })}</div>
          )}
        </div>
      )}

      <div
        style={{
          margin: 0,
          padding: 8,
          flex: 1,
          minHeight: 0,
          background: color.bgInset,
          border: `1px solid ${color.borderSubtle}`,
          borderRadius: radius.sm,
          overflow: "auto",
          fontSize: font.md,
          lineHeight: 1.5,
        }}
      >
        {text === null ? (
          <span style={{ color: color.textMuted }}>{tr("common.loading")}</span>
        ) : (
          cues.map((c, i) => (
            <div
              key={i}
              ref={(el) => {
                cueRefs.current[i] = el;
              }}
              style={{
                padding: "4px 6px",
                borderRadius: radius.sm,
                background: highlight === i + 1 ? color.bgHover : "transparent",
                transition: "background 0.3s",
              }}
            >
              <div style={{ fontSize: font.xs, color: color.textMuted, fontFamily: "ui-monospace, monospace" }}>
                #{i + 1}
                {c.timing ? `  ${c.timing}` : ""}
              </div>
              <div style={{ color: color.textSecondary, whiteSpace: "pre-wrap" }}>{c.content}</div>
            </div>
          ))
        )}
      </div>
    </DetailScaffold>
  );
}
