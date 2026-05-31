/**
 * SubtitleViewer — inspect one subtitle: its SRT text + the quality check
 * (structural / format-residue / language-purity issues) with a one-click
 * auto-fix. Faithful to the Tk srt_preview_pane + subtitles_dialogs check UI.
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type SubtitleCheck } from "../../ipc/client";

const BTN_GHOST: React.CSSProperties = {
  padding: "5px 12px",
  background: "#2a2a2e",
  color: "#ddd",
  border: "none",
  borderRadius: 5,
  fontSize: 12,
  cursor: "pointer",
};

function fmt(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

const SEV_COLOR: Record<string, string> = {
  hard: "#ff6b6b",
  fixable: "#d9a441",
  advisory: "#888",
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
        <button onClick={onClose} style={{ ...BTN_GHOST, padding: "3px 10px" }}>
          ← 返回
        </button>
        <strong style={{ fontSize: 13 }}>{lang}.srt</strong>
        {check && (
          <span style={{ fontSize: 12, color: "#999" }}>
            {check.cue_count} 条
            {check.hard > 0 && <span style={{ color: SEV_COLOR.hard }}> · {check.hard} 严重</span>}
            {check.fixable > 0 && <span style={{ color: SEV_COLOR.fixable }}> · {check.fixable} 可修复</span>}
            {check.advisory > 0 && <span style={{ color: SEV_COLOR.advisory }}> · {check.advisory} 提示</span>}
            {check.hard === 0 && check.fixable === 0 && (
              <span style={{ color: "#3ecf8e" }}> · ✓ 无硬伤</span>
            )}
          </span>
        )}
        {check && check.fixable > 0 && (
          <button onClick={() => void quickFix()} disabled={busy} style={{ ...BTN_GHOST, marginLeft: "auto", color: "#d9a441" }}>
            一键修复可修复项
          </button>
        )}
      </div>

      {error && <div style={{ color: "#ff6b6b", fontSize: 12, marginBottom: 8 }}>✗ {error}</div>}

      {check && check.issues.length > 0 && (
        <div style={{ marginBottom: 10, display: "flex", flexDirection: "column", gap: 2 }}>
          {check.issues.slice(0, 30).map((iss, i) => (
            <div key={i} style={{ fontSize: 11, color: SEV_COLOR[iss.severity_class] ?? "#999" }}>
              {iss.cue_index > 0 ? `#${iss.cue_index} ` : ""}
              {iss.message}
            </div>
          ))}
          {check.issues.length > 30 && (
            <div style={{ fontSize: 11, color: "#666" }}>…共 {check.issues.length} 条</div>
          )}
        </div>
      )}

      <pre
        style={{
          margin: 0,
          padding: 10,
          background: "#161619",
          border: "1px solid #2a2a2e",
          borderRadius: 5,
          maxHeight: 360,
          overflow: "auto",
          fontSize: 12,
          color: "#cdd",
          whiteSpace: "pre-wrap",
          fontFamily: "ui-monospace, monospace",
        }}
      >
        {text ?? "加载中…"}
      </pre>
    </div>
  );
}
