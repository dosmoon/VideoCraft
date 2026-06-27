/**
 * Style tab (样式) — faithful structural port of the Tk clip Style tab
 * (style_panel.py): left column = source preview (whole source) + a draggable
 * staging crop box with "apply crop to all" + the component checkbox list;
 * right column = the selected component's property panel.
 *
 * The preview shows the WHOLE source with sample hook/outro text from the first
 * candidate (mirrors StylePanel._push_preview). The crop here is a pure staging
 * rect (style_panel.py never stored a global crop) — "apply crop to all" bakes
 * it into every candidate's override. Per-candidate crop editing is the Clips
 * tab's job.
 *
 * Still-pending pieces of the original Style tab, deferred to their own
 * increments (NOT dropped):
 *   - toolbar (language / aspect / encode / preset combo + apply/save-as/
 *     override/delete) and the output settings block → later increment
 */

import { useCallback, useEffect, useState } from "react";
import { tr } from "../../i18n/tr";
import { confirmDialog } from "../../ui/confirm";
import type { Component, PresetList } from "../../ipc/client";
import { rpc, RpcError } from "../../ipc/client";
import { MaterialBindingBar } from "../shared/MaterialBindingBar";
import { HotclipsSourceBar } from "./HotclipsSourceBar";
import { ComponentEditor } from "../shared/ComponentEditor";
import { CropPreview } from "./CropPreview";
import { useClipPreview } from "./useClipPreview";
import { centerCropRect, type CropRect } from "@composition/crop.js";
import type { HotclipCandidate } from "@creations/clip/types.js";
import type { DubVersionImport } from "@creations/clip/preview";

// Friendly component labels — mirrors style_panel.py::_KIND_LABELS. The UI must
// never show the internal kind name ([[feedback_user_facing_naming]]).
const KIND_LABEL_KEYS: Record<string, string> = {
  clip_subtitle: "clip.kind.subtitle",
  clip_text_watermark: "clip.kind.text_watermark",
  clip_image_watermark: "clip.kind.image_watermark",
  clip_hook_card: "clip.kind.hook_card",
  clip_outro_card: "clip.kind.outro_card",
  clip_dubbing: "clip.kind.dubbing",
};
function kindLabel(kind: string): string {
  const key = KIND_LABEL_KEYS[kind];
  return key ? tr(key) : kind;
}

const EMPTY_CANDIDATE: HotclipCandidate = { start: "00:00:00.000", end: "00:00:00.000" };

// Mirrors style_panel.py::_ASPECTS / _ENCODE_PRESETS.
const ASPECTS = ["9:16", "1:1", "16:9", "4:5"];
const ENCODE_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"];
const SHORT_EDGES = [720, 1080, 1440, 2160];

const selStyle: React.CSSProperties = {
  background: "#1a1a1e",
  color: "#ddd",
  border: "1px solid #333",
  borderRadius: 4,
  padding: "2px 4px",
  fontSize: 12,
};
const tbBtn: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ccc",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "2px 8px",
  fontSize: 12,
  cursor: "pointer",
};

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
  /** Shared binding refresh key (owned by ClipWorkbench, shared across tabs). */
  refreshKey: number;
  /** Bump the shared key after (re-)binding so every tab's preview reloads. */
  onMaterialBound: () => void;
  onSelect: (id: string | null) => void;
  onPatch: (comp: Component, fields: Record<string, unknown>) => void;
  /** Replace the whole component list (add / remove / reorder returns a new list). */
  onComponentsReplaced: (list: Component[]) => void;
}) {
  const { type, instance, components, selectedId, refreshKey, onMaterialBound, onSelect, onPatch, onComponentsReplaced } =
    props;
  const selected = components?.find((c) => c.id === selectedId) ?? null;

  // Addable component kinds for the [+ Add] menu (registration order + gating).
  const [addable, setAddable] = useState<{ kind: string; multi_instance: boolean }[]>([]);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [compErr, setCompErr] = useState("");
  const [dubBusy, setDubBusy] = useState(false);
  const [dubErr, setDubErr] = useState("");

  // Snapshot a material dubbing track into the selected clip_dubbing component,
  // then force a full preview reload so dubbingAudioPath (preview_data) refreshes.
  const importDub = useCallback(
    async (componentId: string, lang: string, versionId: number) => {
      setDubBusy(true);
      setDubErr("");
      try {
        await rpc.importResource(type, instance, componentId, { kind: "dubbing", lang, version_id: versionId });
        onMaterialBound();
      } catch (e) {
        setDubErr(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
      } finally {
        setDubBusy(false);
      }
    },
    [type, instance, onMaterialBound],
  );

  useEffect(() => {
    let alive = true;
    void rpc
      .listAddableComponents(type, instance)
      .then((a) => alive && setAddable(a))
      .catch(() => alive && setAddable([]));
    return () => {
      alive = false;
    };
  }, [type, instance]);

  const presentKinds = new Set((components ?? []).map((c) => c.kind));

  const fmtErr = (err: unknown) =>
    err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err);

  const onAdd = useCallback(
    async (kind: string) => {
      setAddMenuOpen(false);
      setCompErr("");
      try {
        const list = await rpc.addComponent(type, instance, kind);
        onComponentsReplaced(list);
        // Select the newly added component (appended at the end).
        if (list.length) onSelect(list[list.length - 1]!.id);
      } catch (err) {
        setCompErr(fmtErr(err));
      }
    },
    [type, instance, onComponentsReplaced, onSelect],
  );

  const onRemove = useCallback(async () => {
    if (!selectedId) return;
    if (!(await confirmDialog(tr("clip.style.remove_component_confirm")))) return;
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

  // Material binding (ADR-0005). The shared refreshKey (from ClipWorkbench) forces
  // a full preview reload (nobind → ready) across ALL tabs when a material is
  // (re-)bound — binding changes the source + candidates, which the lightweight
  // reload() doesn't re-fetch.
  const { status, message, data, reload } = useClipPreview(type, instance, refreshKey);

  // ── toolbar (aspect / short-edge / mode / encode / presets) ─────────────────
  const [presets, setPresets] = useState<PresetList | null>(null);
  const [selectedPreset, setSelectedPreset] = useState("");
  const [toolbarErr, setToolbarErr] = useState("");
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

  const tErr = (err: unknown) =>
    setToolbarErr(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));

  // Patch a top-level output field → lightweight reload (no engine reopen).
  const patchOutput = useCallback(
    async (patch: Record<string, unknown>) => {
      setToolbarErr("");
      try {
        await rpc.updateConfig(type, instance, patch);
        reload();
      } catch (err) {
        tErr(err);
      }
    },
    [type, instance, reload],
  );

  const onApplyPreset = useCallback(async () => {
    if (!selectedPreset) return;
    setToolbarErr("");
    try {
      const cfg = await rpc.applyPreset(type, instance, selectedPreset);
      if (Array.isArray(cfg["components"])) onComponentsReplaced(cfg["components"] as Component[]);
      onSelect(null);
      reload();
    } catch (err) {
      tErr(err);
    }
  }, [type, instance, selectedPreset, onComponentsReplaced, onSelect, reload]);

  const onSavePresetAs = useCallback(async () => {
    const name = newPresetName.trim();
    if (!name) return;
    setToolbarErr("");
    try {
      const list = await rpc.savePreset(type, instance, name);
      setPresets(list);
      setSelectedPreset(name);
      setSavingAs(false);
      setNewPresetName("");
      reload();
    } catch (err) {
      tErr(err);
    }
  }, [type, instance, newPresetName, reload]);

  const cancelSaveAs = useCallback(() => {
    setSavingAs(false);
    setNewPresetName("");
    setToolbarErr("");
  }, []);

  const onOverwritePreset = useCallback(async () => {
    if (!selectedPreset) return;
    if (!(await confirmDialog(tr("clip.style.overwrite_preset_confirm", { name: selectedPreset })))) return;
    setToolbarErr("");
    try {
      const list = await rpc.savePreset(type, instance, selectedPreset);
      setPresets(list);
      reload();
    } catch (err) {
      tErr(err);
    }
  }, [type, instance, selectedPreset, reload]);

  const onDeletePreset = useCallback(async () => {
    if (!selectedPreset) return;
    if (!(await confirmDialog(tr("clip.style.delete_preset_confirm", { name: selectedPreset })))) return;
    setToolbarErr("");
    try {
      const list = await rpc.deletePreset(type, instance, selectedPreset);
      setPresets(list);
      setSelectedPreset(list.lastUsed || list.names[0] || "");
    } catch (err) {
      tErr(err);
    }
  }, [type, instance, selectedPreset]);
  // In-memory staging crop (style_panel.py never persisted a global crop).
  const [stagedCrop, setStagedCrop] = useState<CropRect | null>(null);
  const [note, setNote] = useState("");

  const onReady = useCallback(
    (info: { srcW: number; srcH: number }) => {
      if (!data || data.mode !== "reframe") return;
      setStagedCrop(centerCropRect(info.srcW, info.srcH, data.aspect.aw, data.aspect.ah));
    },
    [data],
  );

  // "apply crop to all": bake the staged box into EVERY candidate's override
  // (clips_overrides_merge). Mirrors style_panel.py::_on_apply_crop_to_all.
  const onApplyCropToAll = useCallback(async () => {
    const n = data?.candidates.length ?? 0;
    const rect = stagedCrop;
    if (n <= 0 || !rect) {
      setNote(tr("clip.style.no_candidates_for_crop"));
      return;
    }
    if (!(await confirmDialog(tr("clip.style.apply_crop_confirm", { n })))) return;
    const merge: Record<string, { crop_rect: CropRect }> = {};
    for (let i = 0; i < n; i++) merge[String(i)] = { crop_rect: rect };
    try {
      await rpc.updateConfig(type, instance, { clips_overrides_merge: merge });
      setNote(tr("clip.style.crop_applied", { n }));
    } catch (err) {
      setNote(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
    }
  }, [type, instance, data, stagedCrop]);

  const sample = data?.candidates[0];
  const isReframe = data?.mode === "reframe";

  const aspectStr = data ? `${data.aspect.aw}:${data.aspect.ah}` : "9:16";
  // 原样(passthrough) keeps the source frame verbatim, so the aspect + short-edge
  // settings have no effect there — gray them out to kill the "原样 + 9:16 does
  // nothing" confusion. reframe and letterbox both honour them.
  const aspectInert = data?.mode === "passthrough";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Toolbar (style_panel.py::_build_toolbar): language / aspect / encode /
          mode / short-edge + preset combo with apply / save-as / overwrite / delete. */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 10,
          padding: "8px 16px",
          borderBottom: "1px solid #2a2a2e",
          fontSize: 12,
          color: "#999",
        }}
      >
        <label title={aspectInert ? tr("clip.style.aspect_inert_hint") : undefined}>
          {tr("clip.style.tb_aspect")}{" "}
          <select
            value={aspectStr}
            disabled={!data || aspectInert}
            onChange={(e) => void patchOutput({ output_aspect: e.target.value })}
            style={selStyle}
          >
            {ASPECTS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label title={aspectInert ? tr("clip.style.aspect_inert_hint") : undefined}>
          {tr("clip.style.tb_short_edge")}{" "}
          <select
            value={String(data?.shortEdge ?? 1080)}
            disabled={!data || aspectInert}
            onChange={(e) => void patchOutput({ output_short_edge: Number(e.target.value) })}
            style={selStyle}
          >
            {SHORT_EDGES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          {tr("clip.style.tb_mode")}{" "}
          <select
            value={data?.mode ?? "reframe"}
            disabled={!data}
            onChange={(e) => void patchOutput({ output_mode: e.target.value })}
            style={selStyle}
          >
            <option value="reframe">{tr("clip.style.mode_reframe")}</option>
            <option value="letterbox">{tr("clip.style.mode_letterbox")}</option>
            <option value="passthrough">{tr("clip.style.mode_passthrough")}</option>
          </select>
        </label>
        <label>
          {tr("clip.style.tb_encode")}{" "}
          <select
            value={data?.encodePreset ?? "medium"}
            disabled={!data}
            onChange={(e) => void patchOutput({ encode_preset: e.target.value })}
            style={selStyle}
          >
            {ENCODE_PRESETS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <span style={{ width: 1, height: 18, background: "#3a3a40", margin: "0 2px" }} />

        <label>
          {tr("clip.style.tb_preset")}{" "}
          <select
            value={selectedPreset}
            onChange={(e) => setSelectedPreset(e.target.value)}
            style={{ ...selStyle, maxWidth: 200 }}
          >
            {(presets?.names ?? []).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        {savingAs ? (
          <>
            <input
              autoFocus
              value={newPresetName}
              placeholder={tr("clip.style.preset_name_placeholder")}
              onChange={(e) => setNewPresetName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void onSavePresetAs();
                else if (e.key === "Escape") cancelSaveAs();
              }}
              style={{ ...selStyle, maxWidth: 200 }}
            />
            <button onClick={() => void onSavePresetAs()} disabled={!newPresetName.trim()} style={tbBtn}>
              {tr("common.ok")}
            </button>
            <button onClick={cancelSaveAs} style={tbBtn}>
              {tr("common.cancel")}
            </button>
          </>
        ) : (
          <>
            <button onClick={() => void onApplyPreset()} disabled={!selectedPreset} style={tbBtn}>
              {tr("clip.style.preset_apply")}
            </button>
            <button onClick={() => setSavingAs(true)} style={tbBtn}>
              {tr("clip.style.preset_save_as")}
            </button>
            <button
              onClick={() => void onOverwritePreset()}
              disabled={!selectedPreset || (presets?.builtins.includes(selectedPreset) ?? false)}
              style={tbBtn}
            >
              {tr("clip.style.preset_overwrite")}
            </button>
            <button
              onClick={() => void onDeletePreset()}
              disabled={!selectedPreset || (presets?.builtins.includes(selectedPreset) ?? false)}
              style={tbBtn}
            >
              {tr("common.delete")}
            </button>
          </>
        )}
        {toolbarErr && <span style={{ color: "#ff6b6b" }}>✗ {toolbarErr}</span>}
      </div>

      {/* Material binding — persistent setting; bind here to enable the preview,
          candidates and export (a new-arch clip is created unbound). */}
      <MaterialBindingBar
        type={type}
        instance={instance}
        refreshKey={refreshKey}
        onBound={onMaterialBound}
      />

      {/* Hotclips source — which language's candidates this instance cuts from
          (mirrors the news_desk chapter-source row). Reuses the binding refresh
          callback: a switch changes the candidate set, so every tab reloads. */}
      {status === "ready" && data && (
        <HotclipsSourceBar
          type={type}
          instance={instance}
          lang={data.needsLangChoice ? "" : data.lang}
          availableLangs={data.availableLangs}
          hasCandidateState={data.selectedIndices.length > 0 || Object.keys(data.overrides).length > 0}
          onChanged={onMaterialBound}
        />
      )}

      <div style={{ display: "flex", gap: 16, padding: 16, alignItems: "flex-start", flex: 1, overflow: "auto" }}>
        {/* Left: source preview + staging crop + component checkbox list */}
      <div style={{ flex: "0 0 auto", minWidth: 360 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase" }}>
            {tr("clip.style.preview_label")}
          </span>
          {note && <span style={{ fontSize: 11, color: "#666" }}>{note}</span>}
        </div>

        {status === "loading" && <p style={{ color: "#888", fontSize: 12 }}>{tr("clip.preview.loading_source")}</p>}
        {status === "nobind" && <p style={{ color: "#888", fontSize: 12 }}>{tr("clip.style.no_material_preview")}</p>}
        {status === "nosrc" && <p style={{ color: "#888", fontSize: 12 }}>{tr("clip.no_source_video")}</p>}
        {status === "error" && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {message}</p>}

        {status === "ready" && data && (
          <>
            {/* Crop bar (style_panel.py::_build_preview): staging hint + apply-to-all. */}
            {isReframe && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: "#888" }}>{tr("clip.style.global_crop_hint")}</span>
                <button
                  onClick={() => void onApplyCropToAll()}
                  style={{
                    marginLeft: "auto",
                    padding: "3px 10px",
                    background: "#2a2a2e",
                    color: "#ddd",
                    border: "1px solid #3a3a40",
                    borderRadius: 4,
                    fontSize: 12,
                    cursor: "pointer",
                  }}
                >
                  {tr("clip.style.apply_crop_to_all")}
                </button>
              </div>
            )}
            <CropPreview
              srcPath={data.srcPath}
              candidate={sample ?? EMPTY_CANDIDATE}
              components={components ?? []}
              srtByLang={data.srtByLang}
              mode={data.mode}
              aspect={data.aspect}
              fullSource
              showCards={data.candidates.length > 0}
              cropRect={stagedCrop}
              onCropChange={setStagedCrop}
              dubbingAudioPath={data.dubbingAudioPath}
              onReady={onReady}
            />
          </>
        )}

        {/* Component manager header — [+ 添加] menu / 删除 / ↑ / ↓ (faithful to
            style_panel.py::_build_component_list). */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, margin: "12px 0 6px", position: "relative" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#ccc" }}>{tr("clip.style.components_label")}</span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <button onClick={() => setAddMenuOpen((o) => !o)} style={mgrBtn}>
              + {tr("clip.style.add_component")}
            </button>
            <button onClick={() => void onMove(-1)} disabled={!selectedId} style={mgrBtn} title={tr("clip.style.move_up")}>
              ↑
            </button>
            <button onClick={() => void onMove(1)} disabled={!selectedId} style={mgrBtn} title={tr("clip.style.move_down")}>
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
                // Single-instance kinds are disabled once one exists (faithful
                // to _rebuild_add_menu's gating).
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
          <p style={{ color: "#888" }}>{tr("clip.style.no_components")}</p>
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

      {/* Right: selected component's property panel */}
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
          {tr("clip.style.properties_label")}
        </div>
        {selected ? (
          <>
            {selected.kind === "clip_dubbing" && (
              <DubImportRow
                key={selected.id}
                versions={data?.dubVersions ?? []}
                imported={typeof selected["audio_path"] === "string" && !!selected["audio_path"]}
                busy={dubBusy}
                onPick={(lang, id) => void importDub(selected.id, lang, id)}
              />
            )}
            {dubErr && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {dubErr}</p>}
            <ComponentEditor
              component={selected}
              disabled={false}
              onPatch={(fields) => onPatch(selected, fields)}
              enums={{ language: data?.subtitleLangs ?? [] }}
            />
          </>
        ) : (
          <p style={{ color: "#666", fontSize: 12 }}>{tr("clip.style.no_component_selected")}</p>
        )}
      </div>
      </div>
    </div>
  );
}

/** Pick a material dubbing version (a voice) and snapshot it into the component. */
function DubImportRow(props: {
  versions: DubVersionImport[];
  imported: boolean;
  busy: boolean;
  onPick: (lang: string, id: number) => void;
}) {
  const { versions, imported, busy, onPick } = props;
  const [choice, setChoice] = useState("");
  const keyOf = (v: DubVersionImport) => `${v.lang}#${v.id}`;
  const sel = choice || (versions[0] ? keyOf(versions[0]) : "");
  const picked = versions.find((v) => keyOf(v) === sel);
  return (
    <div style={{ marginBottom: 12, padding: "8px 10px", background: "#1a1a1e", border: "1px solid #2a2a2e", borderRadius: 6 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#ccc" }}>{tr("clip.style.dub_source")}</span>
        <span style={{ fontSize: 11, color: "#777" }}>
          {imported ? tr("clip.style.dub_imported") : tr("clip.style.dub_not_imported")}
        </span>
      </div>
      {versions.length === 0 ? (
        <p style={{ color: "#888", fontSize: 11, margin: 0 }}>{tr("clip.style.dub_empty_hint")}</p>
      ) : (
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <select
            value={sel}
            onChange={(e) => setChoice(e.target.value)}
            disabled={busy}
            style={{ flex: 1, background: "#0e0e10", color: "#ddd", border: "1px solid #333", borderRadius: 4, padding: "4px 6px", fontSize: 12 }}
          >
            {versions.map((v) => (
              <option key={keyOf(v)} value={keyOf(v)}>
                {v.lang.toUpperCase()} · {v.name}
              </option>
            ))}
          </select>
          <button
            onClick={() => picked && onPick(picked.lang, picked.id)}
            disabled={busy || !picked}
            style={{ background: "#2a2a2e", color: "#ccc", border: "1px solid #3a3a40", borderRadius: 4, padding: "4px 12px", fontSize: 12, cursor: busy ? "default" : "pointer" }}
          >
            {tr("clip.style.dub_import_btn")}
          </button>
        </div>
      )}
    </div>
  );
}
