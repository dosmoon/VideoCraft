/**
 * DubViewer — manager for a language's dubbing versions. The <lang>.dub.json
 * manifest holds one version per voice (synthesized from the subtitle "+" →
 * 合成音频 action, which appends/updates a version). This panel lists them, plays
 * each, and deletes them. Deleting the last version clears the sidebar node.
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type DubVersion } from "../../ipc/client";
import { confirmDialog } from "../../ui/confirm";
import { tr } from "../../i18n/tr";
import { color, radius, font } from "../../ui/tokens";
import { DetailHeader, DetailScaffold } from "./detailChrome";

function fmtDuration(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function DubViewer(props: {
  type: string;
  instance: string;
  lang: string;
  title: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { type, instance, lang, title, onClose, onChanged } = props;
  const [versions, setVersions] = useState<DubVersion[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      setVersions(await rpc.listDubVersions(type, instance, lang));
    } catch (e) {
      setError(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
    }
  }, [type, instance, lang]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (v: DubVersion) => {
    if (!(await confirmDialog(tr("material.dub.delete_confirm", { name: v.name })))) return;
    setBusy(v.id);
    try {
      await rpc.removeDubVersion(type, instance, lang, v.id);
      await load();
      onChanged(); // the sidebar node clears when the last version is gone
    } catch (e) {
      setError(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <DetailScaffold header={<DetailHeader title={title} subtitle={lang.toUpperCase()} onBack={onClose} />}>
      {error && <div style={{ color: color.danger, fontSize: font.sm, marginBottom: 8 }}>{error}</div>}
      {versions === null ? (
        <div style={{ color: color.textMuted, fontSize: font.sm }}>{tr("material.dub.loading")}</div>
      ) : versions.length === 0 ? (
        <div style={{ color: color.textMuted, fontSize: font.sm }}>{tr("material.dub.versions_empty")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {versions.map((v) => (
            <div
              key={v.id}
              style={{
                background: color.bgInset,
                border: `1px solid ${color.border}`,
                borderRadius: radius.sm,
                padding: 12,
              }}
            >
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
                <span style={{ color: color.textPrimary, fontSize: font.md, fontWeight: 600 }}>{v.name}</span>
                <span style={{ color: color.textMuted, fontSize: font.xs }}>
                  {v.provider} · {fmtDuration(v.total_sec)}
                  {v.overflow_count > 0 ? ` · ${tr("material.dub.stat_overflow")} ${v.overflow_count}` : ""}
                </span>
                <button
                  onClick={() => void remove(v)}
                  disabled={busy === v.id}
                  style={{
                    marginLeft: "auto",
                    background: "transparent",
                    color: color.danger,
                    border: `1px solid ${color.border}`,
                    borderRadius: radius.sm,
                    padding: "3px 10px",
                    fontSize: font.xs,
                    cursor: busy === v.id ? "default" : "pointer",
                  }}
                >
                  {tr("material.dub.delete")}
                </button>
              </div>
              <audio src={window.vc.mediaUrl(v.audio_path)} controls style={{ display: "block", width: "100%" }} />
            </div>
          ))}
        </div>
      )}
    </DetailScaffold>
  );
}
