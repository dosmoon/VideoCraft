/**
 * SubtitlesTab — the news_video subtitles slot: ASR, translate, external SRT
 * import, the four analysis kinds (titles+chapters / transcript / chapter
 * transcript / hotclips), subtitle viewing + quality check, and the chapter
 * schedule editor. Faithful to the Tk subtitles_progress_modal / srt_preview_pane
 * / subtitle_analysis_preview / chapter_editor.
 *
 * NB: ASR / translate are project-level (one source per project) — see the
 * news_video single_instance note.
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type AnalysisArtifact, type KnownLanguage } from "../../ipc/client";
import { useJob } from "../../ipc/runJob";
import { tr } from "../../i18n/tr";
import type { MaterialTabProps } from "./SourceTab";
import { ChapterScheduleEditor } from "./ChapterScheduleEditor";
import { SubtitleViewer } from "./SubtitleViewer";
import { AnalysisTextViewer } from "./AnalysisTextViewer";
import { LanguagePicker } from "./LanguagePicker";

// The user-facing generate kinds. The engine registry (ANALYSIS_TYPES / RUNNERS)
// also defines transcript + chapter_transcript, but the material UI never offered
// generating them — the Tk menu hides them (node_panes._show_analysis_menu:
// hidden={transcript, chapter_transcript}); they exist only for internal use
// (news_desk export/publish). We mirror that curated menu, not the engine catalog.
function getAnalysisKinds(): { kind: string; label: string }[] {
  return [
    { kind: "analysis", label: tr("material.analysis.kind.analysis") },
    { kind: "hotclips", label: tr("material.analysis.kind.hotclips") },
  ];
}

type Inspect =
  | { mode: "subtitle"; lang: string }
  | { mode: "chapters"; filename: string; lang: string }
  | { mode: "text"; lang: string; kind: string; title: string };

const BTN: React.CSSProperties = {
  padding: "5px 12px",
  background: "#2d6cdf",
  color: "#fff",
  border: "none",
  borderRadius: 5,
  fontSize: 12,
  cursor: "pointer",
};
const BTN_GHOST: React.CSSProperties = { ...BTN, background: "#2a2a2e", color: "#ddd" };

export function SubtitlesTab({ type, instance, refreshKey, onChanged }: MaterialTabProps) {
  const [langs, setLangs] = useState<string[]>([]);
  const [knownLangs, setKnownLangs] = useState<KnownLanguage[]>([]);
  const [artifacts, setArtifacts] = useState<Record<string, AnalysisArtifact[]>>({});
  const [asrLang, setAsrLang] = useState("");
  const [transLang, setTransLang] = useState("");
  const [importLang, setImportLang] = useState("");
  const [inspect, setInspect] = useState<Inspect | null>(null);
  const [loadErr, setLoadErr] = useState("");
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

  const reload = useCallback(async () => {
    setLoadErr("");
    try {
      const ls = await rpc.listSubtitleLanguages(type, instance);
      setLangs(ls);
      const byLang: Record<string, AnalysisArtifact[]> = {};
      for (const l of ls) {
        byLang[l] = await rpc.listAnalysisArtifacts(type, instance, l);
      }
      setArtifacts(byLang);
    } catch (err) {
      setLoadErr(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
    }
  }, [type, instance]);

  useEffect(() => {
    void reload();
  }, [reload, refreshKey]);

  const afterJob = useCallback(
    async (ok: unknown) => {
      if (ok !== undefined) {
        onChanged();
        await reload();
      }
    },
    [onChanged, reload],
  );

  const runAsr = useCallback(async () => {
    const res = await job.run<{ lang_iso?: string }>(() => rpc.startRunAsr(type, instance, asrLang.trim() || undefined));
    // capability.asr stamps no project meta; persist the detected source language
    // (ADR-0008 B3.2b). Other material types still go through the Python job.
    if (res?.lang_iso && type === "news_video") await rpc.setSourceLanguage(res.lang_iso);
    await afterJob(res);
  }, [afterJob, job, type, instance, asrLang]);

  const runTranslate = useCallback(async () => {
    const target = transLang.trim();
    if (!target) return;
    const res = await job.run(() => rpc.startRunTranslate(type, instance, target));
    if (res !== undefined && type === "news_video") await rpc.addTranslatedLanguage(target);
    await afterJob(res);
  }, [afterJob, job, type, instance, transLang]);

  const runAnalysis = useCallback(
    async (lang: string, kind: string) => {
      await afterJob(await job.run(() => rpc.startRunAnalysis(type, instance, lang, kind)));
    },
    [afterJob, job, type, instance],
  );

  const importExternal = useCallback(async () => {
    const lang = importLang.trim();
    if (!lang) return;
    const path = await window.vc.pickSubtitle();
    if (!path) return;
    setLoadErr("");
    try {
      await rpc.importSubtitle(type, instance, path, lang);
      setImportLang("");
      onChanged();
      await reload();
    } catch (err) {
      setLoadErr(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
    }
  }, [importLang, type, instance, onChanged, reload]);

  // Full-panel inspectors (return to the list on close).
  if (inspect?.mode === "subtitle") {
    return (
      <SubtitleViewer
        type={type}
        instance={instance}
        lang={inspect.lang}
        onClose={() => setInspect(null)}
        onChanged={() => {
          onChanged();
          void reload();
        }}
      />
    );
  }
  if (inspect?.mode === "chapters") {
    return (
      <ChapterScheduleEditor
        type={type}
        instance={instance}
        filename={inspect.filename}
        lang={inspect.lang}
        onClose={() => setInspect(null)}
        onSaved={() => void reload()}
      />
    );
  }
  if (inspect?.mode === "text") {
    return (
      <AnalysisTextViewer
        type={type}
        instance={instance}
        lang={inspect.lang}
        kind={inspect.kind}
        title={inspect.title}
        onClose={() => setInspect(null)}
      />
    );
  }

  const busy = job.running;
  const analysisKinds = getAnalysisKinds();

  return (
    <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 18 }}>
      {loadErr && <div style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {loadErr}</div>}

      {/* ASR + import */}
      <Section title={tr("material.subtitles_tab.section_asr")}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
          <LanguagePicker
            value={asrLang}
            onChange={setAsrLang}
            languages={knownLangs}
            allowAuto
            placeholder={tr("material.subtitles_tab.asr_lang_placeholder")}
            disabled={busy}
            width={200}
          />
          <button onClick={() => void runAsr()} disabled={busy} style={BTN}>
            {tr("material.subtitles_tab.run_asr_btn")}
          </button>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <LanguagePicker
            value={importLang}
            onChange={setImportLang}
            languages={knownLangs}
            placeholder={tr("material.subtitles_tab.import_lang_placeholder")}
            disabled={busy}
            width={200}
          />
          <button onClick={() => void importExternal()} disabled={busy || !importLang.trim()} style={BTN_GHOST}>
            {tr("material.subtitles_tab.import_srt_btn")}
          </button>
        </div>
      </Section>

      {/* Languages: view / check + translate */}
      <Section title={tr("material.subtitles_tab.section_languages")}>
        {langs.length === 0 ? (
          <div style={{ color: "#666", fontSize: 12 }}>{tr("material.subtitles_tab.no_subtitles")}</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 8 }}>
            {langs.map((l) => (
              <div key={l} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ width: 48, color: "#cdd", fontSize: 13 }}>{l}</span>
                <button onClick={() => setInspect({ mode: "subtitle", lang: l })} style={{ ...BTN_GHOST, padding: "3px 10px", fontSize: 11 }}>
                  {tr("material.subtitles_tab.view_check_btn")}
                </button>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <LanguagePicker
            value={transLang}
            onChange={setTransLang}
            languages={knownLangs}
            placeholder={tr("material.subtitles_tab.translate_lang_placeholder")}
            disabled={busy}
            width={200}
          />
          <button onClick={() => void runTranslate()} disabled={busy || !transLang.trim()} style={BTN_GHOST}>
            {tr("material.subtitles_tab.translate_btn")}
          </button>
        </div>
      </Section>

      {/* Analysis: per language, run the 4 kinds + open existing artifacts */}
      <Section title={tr("material.subtitles_tab.section_analysis")}>
        {langs.length === 0 ? (
          <div style={{ color: "#666", fontSize: 12 }}>{tr("material.subtitles_tab.analysis_needs_subtitles")}</div>
        ) : (
          langs.map((l) => (
            <div key={l} style={{ marginBottom: 12 }}>
              <div style={{ color: "#6a9", fontSize: 12, marginBottom: 4 }}>{l}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
                {analysisKinds.map((k) => (
                  <button key={k.kind} onClick={() => void runAnalysis(l, k.kind)} disabled={busy} style={{ ...BTN_GHOST, padding: "3px 10px", fontSize: 11 }}>
                    {tr("material.subtitles_tab.generate_kind_btn", { kind: k.label })}
                  </button>
                ))}
              </div>
              {(artifacts[l] ?? []).length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  {(artifacts[l] ?? []).map((a) => (
                    <button
                      key={a.kind}
                      onClick={() =>
                        a.kind === "analysis"
                          ? setInspect({ mode: "chapters", filename: `${l}.analysis.json`, lang: l })
                          : setInspect({ mode: "text", lang: l, kind: a.kind, title: a.display_zh })
                      }
                      style={{
                        display: "flex",
                        gap: 8,
                        alignItems: "center",
                        textAlign: "left",
                        padding: "5px 10px",
                        background: "#1c1c20",
                        color: "#ddd",
                        border: "1px solid #2a2a2e",
                        borderRadius: 5,
                        fontSize: 12,
                        cursor: "pointer",
                      }}
                    >
                      <span>{a.icon}</span>
                      <span>{a.display_zh}</span>
                      <span style={{ color: "#666", marginLeft: "auto" }}>
                        {a.kind === "analysis" ? tr("material.subtitles_tab.edit_chapters_link") : tr("material.subtitles_tab.view_link")}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </Section>

      {/* Job progress + cancel */}
      {busy && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: "#4a9eff" }}>
            {job.progress?.status_text || job.progress?.phase || tr("material.subtitles_tab.processing")}
            {job.progress?.pct != null ? ` · ${Math.round(job.progress.pct)}%` : ""}
          </span>
          <button onClick={job.cancel} style={{ ...BTN_GHOST, padding: "3px 10px" }}>
            {tr("common.cancel")}
          </button>
        </div>
      )}
      {job.error && <div style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {job.error}</div>}
    </div>
  );
}

function Section(props: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>
        {props.title}
      </div>
      {props.children}
    </div>
  );
}
