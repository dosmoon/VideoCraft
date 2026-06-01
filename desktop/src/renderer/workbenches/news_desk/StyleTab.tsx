/**
 * Style tab (样式) — structural port of the Tk news_desk workbench's left list
 * pane + right property pane (news_desk_tool.py::_build_list_pane /
 * _build_property_pane): a component list with [+ 添加] / 删除 / ↑ / ↓ and a
 * type-driven property panel for the selected component.
 *
 * Reuses clip's generic PropertyPanel (it's component-agnostic — primitive
 * fields only). news_desk's chapter component carries nested modes/style/
 * schedule that the primitive panel skips; nested chapter-style editing + the
 * live source preview are deferred to a follow-on increment (the preview needs
 * the GPU engine wired to buildNewsDeskTimeline). Component add/remove/reorder
 * + flat-field editing are fully live here through the same creation.* RPCs clip
 * uses — the base layer is creation-agnostic (ADR-0004).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Component, PresetList } from "../../ipc/client";
import { rpc, RpcError } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import type { NewsDeskChapterRow } from "@creations/news_desk/types.js";
import { PropertyPanel } from "../clip/propertyEditor";
import { MaterialBindingBar } from "../shared/MaterialBindingBar";
import { NewsDeskPreview, type NewsDeskPreviewHandle } from "./NewsDeskPreview";
import { useNewsDeskPreview } from "./useNewsDeskPreview";
import { ComponentEditor } from "../shared/ComponentEditor";
import { fieldsForKind } from "@composition/components/fieldSpec.js";
import { SubtitleCueList, ChapterScheduleList } from "./ComponentDetail";

// Friendly component labels — the UI must never show the internal kind name
// ([[feedback_user_facing_naming]]). Matches the default_instance names in
// creations/news_desk/component_defs.py.
function kindLabel(kind: string): string {
  const map: Record<string, string> = {
    subtitle: tr("news_desk.kind.subtitle"),
    text_watermark: tr("news_desk.kind.text_watermark"),
    image_watermark: tr("news_desk.kind.image_watermark"),
    chapter: tr("news_desk.kind.chapter"),
  };
  return map[kind] ?? kind;
}

const mgrBtn: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ccc",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "2px 9px",
  fontSize: 12,
  cursor: "pointer",
};

export function StyleTab(props: {
  type: string;
  instance: string;
  components: Component[] | null;
  selectedId: string | null;
  savingId: string | null;
  onSelect: (id: string | null) => void;
  onPatch: (comp: Component, fields: Record<string, unknown>) => void;
  onComponentsReplaced: (list: Component[]) => void;
}) {
  const { type, instance, components, selectedId, savingId, onSelect, onPatch, onComponentsReplaced } =
    props;
  const selected = components?.find((c) => c.id === selectedId) ?? null;

  const [addable, setAddable] = useState<{ kind: string; multi_instance: boolean }[]>([]);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [compErr, setCompErr] = useState("");
  // Importable material artifacts (subtitle languages + analysis files).
  const [imports, setImports] = useState<{ subtitleLangs: string[]; analyses: string[] }>({
    subtitleLangs: [],
    analyses: [],
  });
  const [importBusy, setImportBusy] = useState(false);
  const [importErr, setImportErr] = useState("");
  // Bumped after a material bind so the import options (which come from the now-
  // bound material) re-fetch.
  const [refreshKey, setRefreshKey] = useState(0);

  // Full-source composition preview (whole source + overlays; no crop box).
  const preview = useNewsDeskPreview(type, instance);
  // Drives the preview playhead from the subtitle/chapter detail lists.
  const previewRef = useRef<NewsDeskPreviewHandle>(null);

  useEffect(() => {
    let alive = true;
    void rpc
      .listAddableComponents(type, instance)
      .then((a) => alive && setAddable(a))
      .catch(() => alive && setAddable([]));
    void rpc
      .listImports(type, instance)
      .then((i) => alive && setImports(i))
      .catch(() => alive && setImports({ subtitleLangs: [], analyses: [] }));
    return () => {
      alive = false;
    };
  }, [type, instance, refreshKey]);

  // Import a material artifact into the selected component → splice the returned
  // (updated) component back into the list. The owner persisted it server-side.
  const onImport = useCallback(
    async (componentId: string, params: Record<string, unknown>) => {
      setImportBusy(true);
      setImportErr("");
      try {
        const updated = await rpc.importResource(type, instance, componentId, params);
        onComponentsReplaced(
          (components ?? []).map((c) => (c.id === componentId ? updated : c)),
        );
        // A subtitle import snapshots a new SRT into the instance; the preview's
        // cuesBySrtPath comes from preview_data, so it must re-fetch or the
        // subtitle has an srt_path but no cues and renders nothing. (Chapter
        // schedule rides in the component config, so it renders without this —
        // but reloading is cheap/in-place and covers both.)
        preview.reload();
      } catch (err) {
        setImportErr(fmtErr(err));
      } finally {
        setImportBusy(false);
      }
    },
    [type, instance, components, onComponentsReplaced, preview],
  );

  const presentKinds = new Set((components ?? []).map((c) => c.kind));
  const fmtErr = (err: unknown) =>
    err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err);

  // After binding a material, refresh the preview (nobind → ready) and the
  // import options (which read the now-bound material).
  const onMaterialBound = useCallback(() => {
    setRefreshKey((k) => k + 1);
    preview.reload();
  }, [preview]);

  // ── presets (component-list templates; news_desk has no output geometry) ────
  const [presets, setPresets] = useState<PresetList | null>(null);
  const [selectedPreset, setSelectedPreset] = useState("");
  const [presetErr, setPresetErr] = useState("");
  // Inline save-as input (window.prompt is not supported in the Electron renderer).
  const [savingAs, setSavingAs] = useState(false);
  const [newPresetName, setNewPresetName] = useState("");

  useEffect(() => {
    let alive = true;
    void rpc
      .listPresets(type, instance)
      .then((p) => {
        if (!alive) return;
        setPresets(p);
        setSelectedPreset((cur) => cur || p.lastUsed || p.names[0] || "");
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [type, instance]);

  const pErr = (err: unknown) =>
    setPresetErr(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));

  const onApplyPreset = useCallback(async () => {
    if (!selectedPreset) return;
    if (!window.confirm(tr("news_desk.style.preset_apply_confirm", { name: selectedPreset }))) return;
    setPresetErr("");
    try {
      const cfg = await rpc.applyPreset(type, instance, selectedPreset);
      if (Array.isArray(cfg["components"])) onComponentsReplaced(cfg["components"] as Component[]);
      onSelect(null);
      preview.reload();
    } catch (err) {
      pErr(err);
    }
  }, [type, instance, selectedPreset, onComponentsReplaced, onSelect, preview]);

  const onSavePresetAs = useCallback(async () => {
    const name = newPresetName.trim();
    if (!name) return;
    setPresetErr("");
    try {
      const list = await rpc.savePreset(type, instance, name);
      setPresets(list);
      setSelectedPreset(name);
      setSavingAs(false);
      setNewPresetName("");
    } catch (err) {
      pErr(err);
    }
  }, [type, instance, newPresetName]);

  const cancelSaveAs = useCallback(() => {
    setSavingAs(false);
    setNewPresetName("");
    setPresetErr("");
  }, []);

  const onOverwritePreset = useCallback(async () => {
    if (!selectedPreset) return;
    if (!window.confirm(tr("news_desk.style.preset_overwrite_confirm", { name: selectedPreset }))) return;
    setPresetErr("");
    try {
      const list = await rpc.savePreset(type, instance, selectedPreset);
      setPresets(list);
    } catch (err) {
      pErr(err);
    }
  }, [type, instance, selectedPreset]);

  const onDeletePreset = useCallback(async () => {
    if (!selectedPreset) return;
    if (!window.confirm(tr("news_desk.style.preset_delete_confirm", { name: selectedPreset }))) return;
    setPresetErr("");
    try {
      const list = await rpc.deletePreset(type, instance, selectedPreset);
      setPresets(list);
      setSelectedPreset(list.lastUsed || list.names[0] || "");
    } catch (err) {
      pErr(err);
    }
  }, [type, instance, selectedPreset]);

  const onAdd = useCallback(
    async (kind: string) => {
      setAddMenuOpen(false);
      setCompErr("");
      try {
        const list = await rpc.addComponent(type, instance, kind);
        onComponentsReplaced(list);
        if (list.length) onSelect(list[list.length - 1]!.id);
      } catch (err) {
        setCompErr(fmtErr(err));
      }
    },
    [type, instance, onComponentsReplaced, onSelect],
  );

  const onRemove = useCallback(async () => {
    if (!selectedId) return;
    if (!window.confirm(tr("news_desk.style.component_delete_confirm"))) return;
    setCompErr("");
    try {
      const list = await rpc.removeComponent(type, instance, selectedId);
      onComponentsReplaced(list);
      onSelect(null);
    } catch (err) {
      setCompErr(fmtErr(err));
    }
  }, [type, instance, selectedId, onComponentsReplaced, onSelect]);

  const onMove = useCallback(
    async (delta: number) => {
      if (!selectedId) return;
      setCompErr("");
      try {
        const list = await rpc.moveComponent(type, instance, selectedId, delta);
        onComponentsReplaced(list);
      } catch (err) {
        setCompErr(fmtErr(err));
      }
    },
    [type, instance, selectedId, onComponentsReplaced],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Preset toolbar — component-list templates (news_desk has no output
          geometry, so this is just the preset combo + apply/save/delete). */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "10px 16px 0",
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontSize: 12, color: "#888" }}>{tr("news_desk.style.preset_label")}</span>
        <select
          value={selectedPreset}
          onChange={(e) => setSelectedPreset(e.target.value)}
          style={{
            background: "#222",
            color: "#ddd",
            border: "1px solid #3a3a40",
            borderRadius: 4,
            padding: "3px 6px",
            fontSize: 12,
            minWidth: 140,
          }}
        >
          {(presets?.names ?? []).map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        {savingAs ? (
          <>
            <input
              autoFocus
              value={newPresetName}
              placeholder={tr("news_desk.style.preset_name_placeholder")}
              onChange={(e) => setNewPresetName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void onSavePresetAs();
                else if (e.key === "Escape") cancelSaveAs();
              }}
              style={{
                background: "#222",
                color: "#ddd",
                border: "1px solid #3a3a40",
                borderRadius: 4,
                padding: "3px 6px",
                fontSize: 12,
                minWidth: 140,
              }}
            />
            <button onClick={() => void onSavePresetAs()} disabled={!newPresetName.trim()} style={mgrBtn}>
              {tr("common.ok")}
            </button>
            <button onClick={cancelSaveAs} style={mgrBtn}>
              {tr("common.cancel")}
            </button>
          </>
        ) : (
          <>
            <button onClick={() => void onApplyPreset()} disabled={!selectedPreset} style={mgrBtn}>
              {tr("news_desk.style.preset_apply")}
            </button>
            <button onClick={() => setSavingAs(true)} style={mgrBtn}>
              {tr("news_desk.style.preset_save_as")}
            </button>
            <button
              onClick={() => void onOverwritePreset()}
              disabled={!selectedPreset || (presets?.builtins.includes(selectedPreset) ?? false)}
              style={mgrBtn}
            >
              {tr("news_desk.style.preset_overwrite")}
            </button>
            <button
              onClick={() => void onDeletePreset()}
              disabled={!selectedPreset || (presets?.builtins.includes(selectedPreset) ?? false)}
              style={mgrBtn}
            >
              {tr("common.delete")}
            </button>
          </>
        )}
        {presetErr && <span style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {presetErr}</span>}
      </div>

      {/* Material binding — a persistent setting (not a one-time gate): shows the
          bound material and lets the user re-bind at any time. */}
      <MaterialBindingBar
        type={type}
        instance={instance}
        refreshKey={refreshKey}
        onBound={onMaterialBound}
      />

      <div style={{ display: "flex", gap: 16, padding: 16, alignItems: "flex-start", flex: 1, overflow: "auto" }}>
      {/* Left: full-source preview + component manager (list order = z-order). */}
      <div style={{ flex: "0 0 auto", minWidth: 360 }}>
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>
            {tr("news_desk.style.preview_heading")}
          </div>
          {preview.status === "loading" && <p style={{ color: "#888", fontSize: 12 }}>{tr("news_desk.preview.loading_source")}</p>}
          {preview.status === "nobind" && (
            <p style={{ color: "#888", fontSize: 12 }}>{tr("news_desk.style.preview_nobind")}</p>
          )}
          {preview.status === "nosrc" && <p style={{ color: "#888", fontSize: 12 }}>{tr("news_desk.style.preview_nosrc")}</p>}
          {preview.status === "error" && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {preview.message}</p>}
          {preview.status === "ready" && preview.data && (
            <NewsDeskPreview
              controlRef={previewRef}
              srcPath={preview.data.srcPath}
              durationSec={preview.data.durationSec}
              components={components ?? []}
              cuesBySrtPath={preview.data.cuesBySrtPath}
            />
          )}
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginBottom: 6,
            position: "relative",
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600, color: "#ccc" }}>{tr("news_desk.style.components_heading")}</span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <button onClick={() => setAddMenuOpen((o) => !o)} style={mgrBtn}>
              {tr("news_desk.style.add_component")}
            </button>
            <button onClick={() => void onMove(-1)} disabled={!selectedId} style={mgrBtn} title={tr("news_desk.style.move_up")}>
              ↑
            </button>
            <button onClick={() => void onMove(1)} disabled={!selectedId} style={mgrBtn} title={tr("news_desk.style.move_down")}>
              ↓
            </button>
            <button onClick={() => void onRemove()} disabled={!selectedId} style={mgrBtn}>
              {tr("common.delete")}
            </button>
          </div>
          {addMenuOpen && (
            <div
              style={{
                position: "absolute",
                top: "100%",
                right: 0,
                zIndex: 20,
                background: "#1f1f23",
                border: "1px solid #3a3a40",
                borderRadius: 6,
                padding: 4,
                minWidth: 140,
                boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
              }}
            >
              {addable.map((a) => {
                // Single-instance kinds (chapter) disable once present.
                const disabled = !a.multi_instance && presentKinds.has(a.kind);
                return (
                  <button
                    key={a.kind}
                    disabled={disabled}
                    onClick={() => void onAdd(a.kind)}
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      background: "transparent",
                      color: disabled ? "#555" : "#ddd",
                      border: "none",
                      borderRadius: 4,
                      padding: "5px 8px",
                      fontSize: 13,
                      cursor: disabled ? "not-allowed" : "pointer",
                    }}
                  >
                    {kindLabel(a.kind)}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        {compErr && <p style={{ color: "#ff6b6b", fontSize: 12, margin: "0 0 6px" }}>✗ {compErr}</p>}

        {components === null ? (
          <p style={{ color: "#888" }}>{tr("common.loading")}</p>
        ) : components.length === 0 ? (
          <p style={{ color: "#888" }}>{tr("news_desk.style.no_components")}</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {components.map((c) => {
              const sel = selectedId === c.id;
              return (
                <li key={c.id} style={{ borderBottom: "1px solid #222" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 8px" }}>
                    <input
                      type="checkbox"
                      checked={c.enabled ?? true}
                      disabled={savingId === c.id}
                      onChange={() => onPatch(c, { enabled: !(c.enabled ?? true) })}
                    />
                    <button
                      onClick={() => onSelect(sel ? null : c.id)}
                      style={{
                        flex: 1,
                        display: "flex",
                        gap: 8,
                        alignItems: "baseline",
                        textAlign: "left",
                        background: sel ? "#1d2740" : "transparent",
                        border: "none",
                        borderRadius: 4,
                        padding: "2px 6px",
                        cursor: "pointer",
                        color: sel ? "#fff" : "#ddd",
                      }}
                    >
                      <span style={{ fontWeight: 500, fontSize: 13 }}>
                        {kindLabel(c.kind)}
                      </span>
                      {typeof c["name"] === "string" && c["name"] && (
                        <span style={{ color: "#777", fontSize: 11 }}>{c["name"] as string}</span>
                      )}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Right: selected component's property panel. */}
      <div style={{ flex: 1, minWidth: 220, borderLeft: "1px solid #222", paddingLeft: 16 }}>
        <div
          style={{
            fontSize: 11,
            color: "#888",
            fontWeight: 700,
            textTransform: "uppercase",
            marginBottom: 8,
          }}
        >
          {tr("news_desk.style.properties_heading")}
        </div>
        {selected ? (
          <>
            {selected.kind === "subtitle" && (
              <ImportRow
                key={selected.id}
                label={tr("news_desk.style.subtitle_source")}
                options={imports.subtitleLangs}
                emptyHint={tr("news_desk.style.subtitle_empty_hint")}
                current={
                  typeof selected["srt_path"] === "string" && selected["srt_path"]
                    ? tr("news_desk.style.imported")
                    : tr("news_desk.style.not_imported")
                }
                busy={importBusy}
                onPick={(lang) => void onImport(selected.id, { kind: "subtitle", lang })}
              />
            )}
            {selected.kind === "chapter" && (
              <ImportRow
                key={selected.id}
                label={tr("news_desk.style.chapter_source")}
                options={imports.analyses}
                emptyHint={tr("news_desk.style.chapter_empty_hint")}
                current={
                  Array.isArray(selected["schedule"]) && (selected["schedule"] as unknown[]).length
                    ? tr("news_desk.style.chapter_imported_count", { count: (selected["schedule"] as unknown[]).length })
                    : tr("news_desk.style.not_imported")
                }
                busy={importBusy}
                onPick={(filename) => void onImport(selected.id, { kind: "chapters", filename })}
              />
            )}
            {importErr && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {importErr}</p>}
            {fieldsForKind(selected.kind) ? (
              <ComponentEditor
                component={selected}
                disabled={savingId === selected.id}
                onPatch={(fields) => onPatch(selected, fields)}
              />
            ) : (
              <PropertyPanel
                component={selected}
                disabled={savingId === selected.id}
                onCommit={(k, v) => onPatch(selected, { [k]: v })}
              />
            )}

            {/* Read-only detail list for the selected component, click to seek. */}
            {selected.kind === "subtitle" && (
              <SubtitleCueList
                cues={
                  typeof selected["srt_path"] === "string"
                    ? preview.data?.cuesBySrtPath[selected["srt_path"] as string]
                    : undefined
                }
                onSeek={(sec) => previewRef.current?.seek(sec)}
              />
            )}
            {selected.kind === "chapter" && (
              <ChapterScheduleList
                schedule={selected["schedule"] as NewsDeskChapterRow[] | undefined}
                onSeek={(sec) => previewRef.current?.seek(sec)}
              />
            )}
          </>
        ) : (
          <p style={{ color: "#666", fontSize: 12 }}>{tr("news_desk.style.select_component_hint")}</p>
        )}
      </div>
      </div>
    </div>
  );
}

// Import-from-material row: a dropdown of options (subtitle langs / analysis
// files) + an import button. Picking one snapshots it into the component.
function ImportRow(props: {
  label: string;
  options: string[];
  emptyHint: string;
  current: string;
  busy: boolean;
  onPick: (option: string) => void;
}) {
  const { label, options, emptyHint, current, busy, onPick } = props;
  const [choice, setChoice] = useState("");
  const sel = choice || options[0] || "";
  return (
    <div
      style={{
        marginBottom: 12,
        padding: "8px 10px",
        background: "#1a1a1e",
        border: "1px solid #2a2a2e",
        borderRadius: 6,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#ccc" }}>{label}</span>
        <span style={{ fontSize: 11, color: "#777" }}>{current}</span>
      </div>
      {options.length === 0 ? (
        <p style={{ color: "#888", fontSize: 11, margin: 0 }}>{emptyHint}</p>
      ) : (
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <select
            value={sel}
            onChange={(e) => setChoice(e.target.value)}
            style={{
              flex: 1,
              background: "#222",
              color: "#ddd",
              border: "1px solid #3a3a40",
              borderRadius: 4,
              padding: "3px 6px",
              fontSize: 12,
            }}
          >
            {options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
          <button
            onClick={() => sel && onPick(sel)}
            disabled={busy || !sel}
            style={{
              background: "#2d6cdf",
              color: "#fff",
              border: "none",
              borderRadius: 4,
              padding: "3px 12px",
              fontSize: 12,
              cursor: busy ? "default" : "pointer",
              opacity: busy ? 0.6 : 1,
            }}
          >
            {tr("news_desk.style.import_btn")}
          </button>
        </div>
      )}
    </div>
  );
}
