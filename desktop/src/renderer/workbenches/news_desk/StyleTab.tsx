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

import { useCallback, useEffect, useState } from "react";
import type { Component } from "../../ipc/client";
import { rpc, RpcError } from "../../ipc/client";
import { PropertyPanel } from "../clip/propertyEditor";
import { NewsDeskPreview } from "./NewsDeskPreview";
import { useNewsDeskPreview } from "./useNewsDeskPreview";

// Friendly component labels — the UI must never show the internal kind name
// ([[feedback_user_facing_naming]]). Matches the default_instance names in
// creations/news_desk/component_defs.py.
const KIND_LABELS: Record<string, string> = {
  subtitle: "字幕",
  text_watermark: "文字水印",
  image_watermark: "图片水印",
  chapter: "章节",
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
  }, [type, instance]);

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
      } catch (err) {
        setImportErr(fmtErr(err));
      } finally {
        setImportBusy(false);
      }
    },
    [type, instance, components, onComponentsReplaced],
  );

  const presentKinds = new Set((components ?? []).map((c) => c.kind));
  const fmtErr = (err: unknown) =>
    err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err);

  // Full-source composition preview (whole source + overlays; no crop box).
  const preview = useNewsDeskPreview(type, instance);

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

  return (
    <div style={{ display: "flex", gap: 16, padding: 16, alignItems: "flex-start", height: "100%" }}>
      {/* Left: full-source preview + component manager (list order = z-order). */}
      <div style={{ flex: "0 0 auto", minWidth: 360 }}>
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>
            预览
          </div>
          {preview.status === "loading" && <p style={{ color: "#888", fontSize: 12 }}>加载源…</p>}
          {preview.status === "nobind" && <p style={{ color: "#888", fontSize: 12 }}>未绑定素材 — 无法预览</p>}
          {preview.status === "nosrc" && <p style={{ color: "#888", fontSize: 12 }}>绑定素材尚无源视频</p>}
          {preview.status === "error" && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {preview.message}</p>}
          {preview.status === "ready" && preview.data && (
            <NewsDeskPreview
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
          属性
        </div>
        {selected ? (
          <>
            {selected.kind === "subtitle" && (
              <ImportRow
                label="字幕来源"
                options={imports.subtitleLangs}
                emptyHint="素材无可用字幕(先在素材里跑字幕生成)"
                current={
                  typeof selected["srt_path"] === "string" && selected["srt_path"]
                    ? "已导入"
                    : "未导入"
                }
                busy={importBusy}
                onPick={(lang) => void onImport(selected.id, { kind: "subtitle", lang })}
              />
            )}
            {selected.kind === "chapter" && (
              <ImportRow
                label="章节来源"
                options={imports.analyses}
                emptyHint="素材无章节分析(先在素材里跑章节分析)"
                current={
                  Array.isArray(selected["schedule"]) && (selected["schedule"] as unknown[]).length
                    ? `已导入 ${(selected["schedule"] as unknown[]).length} 章`
                    : "未导入"
                }
                busy={importBusy}
                onPick={(filename) => void onImport(selected.id, { kind: "chapters", filename })}
              />
            )}
            {importErr && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {importErr}</p>}
            <PropertyPanel
              component={selected}
              disabled={savingId === selected.id}
              onCommit={(k, v) => onPatch(selected, { [k]: v })}
            />
            {selected.kind === "chapter" && (
              <p style={{ color: "#666", fontSize: 11, marginTop: 10 }}>
                章节排期 + 卡片样式编辑待后续迭代
              </p>
            )}
          </>
        ) : (
          <p style={{ color: "#666", fontSize: 12 }}>选择一个组件以编辑其属性</p>
        )}
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
            导入
          </button>
        </div>
      )}
    </div>
  );
}
