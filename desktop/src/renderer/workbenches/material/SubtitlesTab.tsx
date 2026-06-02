/**
 * SubtitlesTab — the subtitle OPERATIONS panel for the news_video subtitles node.
 *
 * Pared down (ADR-0008 B3.2 sidebar redesign): the sidebar now owns subtitle
 * navigation and per-language actions — language nodes open the viewer, the
 * language "+" generates analysis, analysis child nodes open their artifact. So
 * this panel keeps ONLY the data-producing actions that don't fit a one-click
 * sidebar affordance:
 *   - Transcribe (ASR) with an optional source-language override (the sidebar's
 *     inline ASR is auto-detect only)
 *   - Translate an existing subtitle into a target language (no sidebar home)
 *   - Import an external .srt from disk (no sidebar home)
 *
 * The old language list + analysis sections were removed as redundant with the
 * sidebar. ASR / translate are project-level (one source per project) — see the
 * news_video single_instance note. Detected/target language is persisted to
 * project meta after the job (capability.* stamps none).
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type KnownLanguage } from "../../ipc/client";
import { useJob } from "../../ipc/runJob";
import { tr } from "../../i18n/tr";
import type { MaterialTabProps } from "./SourceTab";
import { LanguagePicker } from "./LanguagePicker";
import { color, radius, font } from "../../ui/tokens";
import { AudioLines, Languages, FileUp, Loader2, AlertCircle, type LucideIcon } from "../../ui/icons";

const PICKER_W = 220;

const primaryBtn: React.CSSProperties = {
  padding: "6px 14px",
  background: color.accent,
  color: "#fff",
  border: "none",
  borderRadius: radius.sm,
  fontSize: font.sm,
  cursor: "pointer",
};
const ghostBtn: React.CSSProperties = {
  ...primaryBtn,
  background: color.bgHover,
  color: color.textPrimary,
};
function disabledStyle(base: React.CSSProperties, disabled: boolean): React.CSSProperties {
  return disabled ? { ...base, opacity: 0.5, cursor: "default" } : base;
}

function OperationCard(props: { icon: LucideIcon; title: string; hint: string; children: React.ReactNode }) {
  const { icon: Icon, title, hint, children } = props;
  return (
    <div
      style={{
        border: `1px solid ${color.borderSubtle}`,
        background: color.bgInset,
        borderRadius: radius.md,
        padding: 14,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
        <Icon size={16} strokeWidth={2} color={color.textSecondary} style={{ flexShrink: 0 }} />
        <span style={{ fontSize: font.md, fontWeight: 600, color: color.textPrimary }}>{title}</span>
      </div>
      <div style={{ fontSize: font.xs, color: color.textMuted, marginBottom: 10, paddingLeft: 24 }}>{hint}</div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", paddingLeft: 24 }}>{children}</div>
    </div>
  );
}

export function SubtitlesTab({ type, instance, refreshKey, onChanged }: MaterialTabProps) {
  const [knownLangs, setKnownLangs] = useState<KnownLanguage[]>([]);
  const [sourceLang, setSourceLang] = useState("");
  const [asrLang, setAsrLang] = useState("");
  const [transLang, setTransLang] = useState("");
  const [importLang, setImportLang] = useState("");
  const [err, setErr] = useState("");
  const job = useJob();

  // Preset language catalog for the pickers (loaded once).
  useEffect(() => {
    let alive = true;
    void rpc
      .listLanguages()
      .then((ls) => alive && setKnownLangs(ls))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // The project's source language (ASR / first import stamps project meta). Translate
  // is FROM this source SRT; reload after a job so a fresh ASR surfaces it here.
  useEffect(() => {
    let alive = true;
    void rpc
      .currentProject()
      .then((cur) => {
        if (!alive) return;
        const meta = (cur?.meta ?? {}) as { language?: { source?: string } };
        setSourceLang(meta.language?.source ?? "");
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [refreshKey]);

  // Persist the detected/target language to project meta after the job. Non-fatal:
  // the SRT is already on disk, so a meta-write failure must surface, not hide it.
  const persistMeta = useCallback(async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
    }
  }, []);

  const runAsr = useCallback(async () => {
    setErr("");
    const res = await job.run<{ lang_iso?: string }>(() => rpc.startRunAsr(type, instance, asrLang.trim() || undefined));
    if (res?.lang_iso && type === "news_video") await persistMeta(() => rpc.setSourceLanguage(res.lang_iso!));
    if (res !== undefined) onChanged();
  }, [job, type, instance, asrLang, persistMeta, onChanged]);

  const runTranslate = useCallback(async () => {
    const target = transLang.trim();
    if (!target) return;
    setErr("");
    const res = await job.run(() => rpc.startRunTranslate(type, instance, target));
    if (res !== undefined && type === "news_video") await persistMeta(() => rpc.addTranslatedLanguage(target));
    if (res !== undefined) onChanged();
  }, [job, type, instance, transLang, persistMeta, onChanged]);

  const importExternal = useCallback(async () => {
    const lang = importLang.trim();
    if (!lang) return;
    const path = await window.vc.pickSubtitle();
    if (!path) return;
    setErr("");
    try {
      await rpc.importSubtitle(type, instance, path, lang);
      setImportLang("");
      onChanged();
    } catch (e) {
      setErr(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
    }
  }, [importLang, type, instance, onChanged]);

  const busy = job.running;

  return (
    <div style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <h2 style={{ fontSize: font.lg, fontWeight: 600, margin: "0 0 4px", color: color.textPrimary }}>
          {tr("material.subtitles_tab.op_heading")}
        </h2>
        <p style={{ fontSize: font.sm, color: color.textSecondary, margin: 0, lineHeight: 1.5 }}>
          {tr("material.subtitles_tab.op_hint")}
        </p>
      </div>

      {err && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: color.danger, fontSize: font.sm }}>
          <AlertCircle size={14} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span>{err}</span>
        </div>
      )}

      <OperationCard icon={AudioLines} title={tr("material.subtitles_tab.asr_title")} hint={tr("material.subtitles_tab.asr_hint")}>
        <LanguagePicker
          value={asrLang}
          onChange={setAsrLang}
          languages={knownLangs}
          allowAuto
          placeholder={tr("material.subtitles_tab.asr_lang_placeholder")}
          disabled={busy}
          width={PICKER_W}
        />
        <button onClick={() => void runAsr()} disabled={busy} style={disabledStyle(primaryBtn, busy)}>
          {tr("material.subtitles_tab.run_asr_btn")}
        </button>
      </OperationCard>

      <OperationCard icon={Languages} title={tr("material.subtitles_tab.translate_title")} hint={tr("material.subtitles_tab.translate_hint")}>
        {sourceLang ? (
          <>
            <span
              style={{
                fontSize: font.sm,
                color: color.textSecondary,
                background: color.bgHover,
                borderRadius: radius.sm,
                padding: "4px 8px",
                whiteSpace: "nowrap",
              }}
            >
              {tr("material.subtitles_tab.translate_from", { lang: sourceLang.toUpperCase() })}
            </span>
            <LanguagePicker
              value={transLang}
              onChange={setTransLang}
              languages={knownLangs}
              placeholder={tr("material.subtitles_tab.translate_target_placeholder")}
              disabled={busy}
              width={PICKER_W}
            />
            <button
              onClick={() => void runTranslate()}
              disabled={busy || !transLang.trim()}
              style={disabledStyle(primaryBtn, busy || !transLang.trim())}
            >
              {tr("material.subtitles_tab.translate_btn")}
            </button>
          </>
        ) : (
          <span style={{ fontSize: font.sm, color: color.textMuted }}>{tr("material.subtitles_tab.translate_needs_source")}</span>
        )}
      </OperationCard>

      <OperationCard icon={FileUp} title={tr("material.subtitles_tab.import_title")} hint={tr("material.subtitles_tab.import_hint")}>
        <LanguagePicker
          value={importLang}
          onChange={setImportLang}
          languages={knownLangs}
          placeholder={tr("material.subtitles_tab.import_lang_placeholder")}
          disabled={busy}
          width={PICKER_W}
        />
        <button
          onClick={() => void importExternal()}
          disabled={busy || !importLang.trim()}
          style={disabledStyle(ghostBtn, busy || !importLang.trim())}
        >
          {tr("material.subtitles_tab.import_srt_btn")}
        </button>
      </OperationCard>

      {busy && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: color.accentText, fontSize: font.sm }}>
          <Loader2 size={14} strokeWidth={2} className="vc-spin" style={{ flexShrink: 0 }} />
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {job.progress?.status_text || job.progress?.phase || tr("material.subtitles_tab.processing")}
            {job.progress?.pct != null ? ` · ${Math.round(job.progress.pct)}%` : ""}
          </span>
          <button onClick={job.cancel} style={ghostBtn}>
            {tr("common.cancel")}
          </button>
        </div>
      )}
      {job.error && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: color.danger, fontSize: font.sm }}>
          <AlertCircle size={14} strokeWidth={2} style={{ flexShrink: 0 }} />
          <span>{job.error}</span>
        </div>
      )}
    </div>
  );
}
