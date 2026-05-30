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
import type { Component } from "../../ipc/client";
import { rpc, RpcError } from "../../ipc/client";
import { PropertyPanel } from "./propertyEditor";
import { CropPreview } from "./CropPreview";
import { useClipPreview } from "./useClipPreview";
import { centerCropRect, type CropRect } from "./cropEditor";
import type { HotclipCandidate } from "@creations/clip/types.js";

// Friendly component labels — mirrors style_panel.py::_KIND_LABELS. The UI must
// never show the internal kind name ([[feedback_user_facing_naming]]).
const KIND_LABELS: Record<string, string> = {
  clip_subtitle: "字幕",
  clip_text_watermark: "文字水印",
  clip_image_watermark: "图片水印",
  clip_hook_card: "Hook 卡片",
  clip_outro_card: "Outro 卡片",
};

const EMPTY_CANDIDATE: HotclipCandidate = { start: "00:00:00.000", end: "00:00:00.000" };

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
  /** Replace the whole component list (add / remove / reorder returns a new list). */
  onComponentsReplaced: (list: Component[]) => void;
}) {
  const { type, instance, components, selectedId, savingId, onSelect, onPatch, onComponentsReplaced } =
    props;
  const selected = components?.find((c) => c.id === selectedId) ?? null;

  // Addable component kinds for the [+ Add] menu (registration order + gating).
  const [addable, setAddable] = useState<{ kind: string; multi_instance: boolean }[]>([]);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [compErr, setCompErr] = useState("");

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
    if (!window.confirm("删除选中的组件？")) return;
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

  const { status, message, data } = useClipPreview(type, instance);
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
      setNote("素材无候选 — 无法应用裁剪");
      return;
    }
    if (!window.confirm(`把当前裁剪框应用到全部 ${n} 个候选？`)) return;
    const merge: Record<string, { crop_rect: CropRect }> = {};
    for (let i = 0; i < n; i++) merge[String(i)] = { crop_rect: rect };
    try {
      await rpc.updateConfig(type, instance, { clips_overrides_merge: merge });
      setNote(`已应用裁剪到全部 ${n} 个候选`);
    } catch (err) {
      setNote(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
    }
  }, [type, instance, data, stagedCrop]);

  const sample = data?.candidates[0];
  const isReframe = data?.mode === "reframe";

  return (
    <div style={{ display: "flex", gap: 16, padding: 16, alignItems: "flex-start" }}>
      {/* Left: source preview + staging crop + component checkbox list */}
      <div style={{ flex: "0 0 auto", minWidth: 360 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase" }}>
            预览
          </span>
          {note && <span style={{ fontSize: 11, color: "#666" }}>{note}</span>}
        </div>

        {status === "loading" && <p style={{ color: "#888", fontSize: 12 }}>加载源…</p>}
        {status === "nobind" && <p style={{ color: "#888", fontSize: 12 }}>未绑定素材 — 无法预览</p>}
        {status === "nosrc" && <p style={{ color: "#888", fontSize: 12 }}>绑定素材尚无源视频</p>}
        {status === "error" && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {message}</p>}

        {status === "ready" && data && (
          <>
            {/* Crop bar (style_panel.py::_build_preview): staging hint + apply-to-all. */}
            {isReframe && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: "#888" }}>全局裁剪 · 拖动预览中的框取景</span>
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
                  应用裁剪到全部
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
              onReady={onReady}
            />
          </>
        )}

        {/* Component manager header — [+ 添加] menu / 删除 / ↑ / ↓ (faithful to
            style_panel.py::_build_component_list). */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, margin: "12px 0 6px", position: "relative" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#ccc" }}>组件</span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <button onClick={() => setAddMenuOpen((o) => !o)} style={mgrBtn}>
              + 添加
            </button>
            <button onClick={() => void onMove(-1)} disabled={!selectedId} style={mgrBtn} title="上移">
              ↑
            </button>
            <button onClick={() => void onMove(1)} disabled={!selectedId} style={mgrBtn} title="下移">
              ↓
            </button>
            <button onClick={() => void onRemove()} disabled={!selectedId} style={mgrBtn}>
              删除
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
                    {KIND_LABELS[a.kind] ?? a.kind}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        {compErr && <p style={{ color: "#ff6b6b", fontSize: 12, margin: "0 0 6px" }}>✗ {compErr}</p>}

        {components === null ? (
          <p style={{ color: "#888" }}>加载中…</p>
        ) : components.length === 0 ? (
          <p style={{ color: "#888" }}>无组件 — 用「+ 添加」新建</p>
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
                        {KIND_LABELS[c.kind] ?? c.kind}
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
          属性
        </div>
        {selected ? (
          <PropertyPanel
            component={selected}
            disabled={savingId === selected.id}
            onCommit={(k, v) => onPatch(selected, { [k]: v })}
          />
        ) : (
          <p style={{ color: "#666", fontSize: 12 }}>选择一个组件以编辑其属性</p>
        )}
      </div>
    </div>
  );
}
