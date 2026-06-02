/**
 * Hub — the product UI, driven entirely by the read-only sidecar RPC
 * (project.recent_list/open/close/current, project.list_materials/
 * list_creations, material.slot_readiness). It is the renderer's sole surface
 * now that the substrate spike harness has been retired.
 *
 * Scope (migration doc §0.5 — the Electron shell is framework + 素材 + 创作;
 * the legacy Tk menubar tools are cut): a project launcher and a material
 * sidebar tree. Workbenches + the tab-0 preview model land in later slices.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  rpc,
  RpcError,
  type CreationTypeInfo,
  type MaterialTypeInfo,
  type ProjectBrief,
  type SlotState,
} from "../ipc/client";
import { CreationWorkbench } from "../workbenches";
import { MaterialSidebar } from "../workbenches/material/MaterialSidebar";
import { MaterialDetail } from "../workbenches/material/MaterialDetail";
import { tr, getLang } from "../i18n/tr";
import { color, radius, font } from "../ui/tokens";
import { Folder, Diamond, MoreHorizontal } from "../ui/icons";

// Active row: accent-soft fill + a left accent bar (inset shadow, no layout shift).
// Replaces the old solid-blue fill so the instance header and a selected sidebar
// node read as one coherent selection system instead of two clashing blue blocks.
function rowSelectionStyle(active: boolean): React.CSSProperties {
  return {
    background: active ? color.accentSoft : "transparent",
    boxShadow: active ? `inset 2px 0 0 ${color.accent}` : "none",
    color: active ? color.accentText : color.textPrimary,
  };
}

// What the open workbench is — a creation or a material, plus its identity.
type OpenWorkbench = { kind: "creation" | "material"; type: string; instance: string };

// Locale-aware description for a registered type (the sidecar ships both).
function descOf(t: { description_zh: string; description_en: string }): string {
  return getLang() === "zh" ? t.description_zh : t.description_en;
}

// "type/instance" → (slotId → state). Flat key keeps the readiness cache simple.
type Readiness = Record<string, Record<string, SlotState>>;

function fmt(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

export function Hub() {
  const [recents, setRecents] = useState<ProjectBrief[] | null>(null);
  const [current, setCurrent] = useState<ProjectBrief | null>(null);
  const [materials, setMaterials] = useState<Record<string, string[]>>({});
  const [creations, setCreations] = useState<Record<string, string[]>>({});
  const [readiness, setReadiness] = useState<Readiness>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // The open creation workbench (one at a time), or none.
  const [workbench, setWorkbench] = useState<OpenWorkbench | null>(null);
  // The active material instance + selected node in its sidebar tree (B3.2:
  // materials are sidebar-driven; the right panel shows the selected node's
  // detail). Mutually exclusive with `workbench`. matRefresh bumps the sidebar +
  // detail after a job/write so both re-read.
  const [material, setMaterial] = useState<{ type: string; instance: string; nodeId: string | null } | null>(null);
  const [matRefresh, setMatRefresh] = useState(0);

  // Load a project's material/creation tree + per-instance slot readiness.
  const loadTree = useCallback(async (brief: ProjectBrief) => {
    setCurrent(brief);
    const [mats, creas] = await Promise.all([rpc.listMaterials(), rpc.listCreations()]);
    setMaterials(mats);
    setCreations(creas);
    const next: Readiness = {};
    for (const [type, insts] of Object.entries(mats)) {
      for (const inst of insts) {
        try {
          next[`${type}/${inst}`] = await rpc.slotReadiness(type, inst);
        } catch {
          /* a model that can't report readiness just renders without slots */
        }
      }
    }
    setReadiness(next);
  }, []);

  // On mount: recents + whatever project the sidecar already holds open (it
  // persists across renderer reloads — disk is the source of truth).
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const [rec, cur] = await Promise.all([rpc.recentList(), rpc.currentProject()]);
        if (!alive) return;
        setRecents(rec);
        if (cur) await loadTree(cur);
      } catch (err) {
        if (alive) setError(fmt(err));
      }
    })();
    return () => {
      alive = false;
    };
  }, [loadTree]);

  // Live-refresh the tree from sidecar notifications (a workbench job / write in
  // another view, or a material edit, broadcasts these). materials/creations
  // .changed = structural (reload lists + readiness); material.changed = one
  // instance's slots changed (re-read just that one).
  useEffect(() => {
    if (!current) return;
    const unsub = rpc.onNotification((method, params) => {
      if (method === "event.materials.changed" || method === "event.creations.changed") {
        void (async () => {
          const [mats, creas] = await Promise.all([rpc.listMaterials(), rpc.listCreations()]);
          setMaterials(mats);
          setCreations(creas);
          const next: Readiness = {};
          for (const [t, insts] of Object.entries(mats)) {
            for (const i of insts) {
              try {
                next[`${t}/${i}`] = await rpc.slotReadiness(t, i);
              } catch {
                /* best-effort */
              }
            }
          }
          setReadiness(next);
        })();
      } else if (method === "event.material.changed") {
        const p = params as { type?: string; instance?: string } | null;
        if (p?.type && p.instance) {
          const key = `${p.type}/${p.instance}`;
          void rpc
            .slotReadiness(p.type, p.instance)
            .then((r) => setReadiness((prev) => ({ ...prev, [key]: r })))
            .catch(() => {});
        }
      }
    });
    return unsub;
  }, [current]);

  const open = useCallback(
    async (folder: string) => {
      setBusy(true);
      setError("");
      try {
        const brief = await rpc.openProject(folder);
        await loadTree(brief);
        setRecents(await rpc.recentList()); // open bumps the recent list
      } catch (err) {
        setError(fmt(err));
      } finally {
        setBusy(false);
      }
    },
    [loadTree],
  );

  const pickAndOpen = useCallback(async () => {
    const folder = await window.vc.pickFolder();
    if (folder) await open(folder);
  }, [open]);

  const close = useCallback(async () => {
    await rpc.closeProject();
    setCurrent(null);
    setMaterials({});
    setCreations({});
    setReadiness({});
    setWorkbench(null);
  }, []);

  // Create a new creation instance, refresh the tree, and open its workbench.
  const createCreation = useCallback(
    async (type: string) => {
      setError("");
      try {
        const { instance } = await rpc.createCreationInstance(type);
        setCreations(await rpc.listCreations());
        setWorkbench({ kind: "creation", type, instance });
      } catch (err) {
        setError(fmt(err));
      }
    },
    [],
  );

  // Create a new material instance, refresh the tree (+ its slot readiness), and
  // open its workbench. Single-instance types are guarded at the menu, but the
  // RPC also rejects a duplicate name defensively.
  const createMaterial = useCallback(
    async (type: string) => {
      setError("");
      try {
        const { instance } = await rpc.createMaterialInstance(type);
        const mats = await rpc.listMaterials();
        setMaterials(mats);
        try {
          const r = await rpc.slotReadiness(type, instance);
          setReadiness((prev) => ({ ...prev, [`${type}/${instance}`]: r }));
        } catch {
          /* readiness is best-effort */
        }
        setWorkbench({ kind: "material", type, instance });
      } catch (err) {
        setError(fmt(err));
      }
    },
    [],
  );

  // Rename / delete an instance. The sidebar tree refreshes via the changed event
  // the sidecar emits; here we only fix up the open workbench (follow a rename, or
  // close it on delete).
  const renameInst = useCallback(
    async (kind: "material" | "creation", type: string, instance: string) => {
      const next = window.prompt(tr("hub.rename_prompt"), instance);
      if (!next || next.trim() === instance) return;
      setError("");
      try {
        const res = await rpc.renameInstance(kind, type, instance, next.trim());
        setWorkbench((w) =>
          w && w.kind === kind && w.type === type && w.instance === instance
            ? { ...w, instance: res.instance }
            : w,
        );
        if (kind === "material")
          setMaterial((m) =>
            m && m.type === type && m.instance === instance ? { ...m, instance: res.instance } : m,
          );
      } catch (err) {
        setError(fmt(err));
      }
    },
    [],
  );

  const deleteInst = useCallback(
    async (kind: "material" | "creation", type: string, instance: string) => {
      if (!window.confirm(tr("hub.delete_confirm", { name: instance }))) return;
      setError("");
      try {
        await rpc.deleteInstance(kind, type, instance);
        setWorkbench((w) =>
          w && w.kind === kind && w.type === type && w.instance === instance ? null : w,
        );
        if (kind === "material")
          setMaterial((m) => (m && m.type === type && m.instance === instance ? null : m));
      } catch (err) {
        setError(fmt(err));
      }
    },
    [],
  );

  if (!current) {
    return (
      <Launcher recents={recents} busy={busy} error={error} onOpen={open} onPick={pickAndOpen} />
    );
  }
  return (
    <ProjectView
      current={current}
      materials={materials}
      creations={creations}
      readiness={readiness}
      error={error}
      workbench={workbench}
      material={material}
      matRefresh={matRefresh}
      onOpenCreation={(type, instance) => {
        setMaterial(null);
        setWorkbench({ kind: "creation", type, instance });
      }}
      onOpenMaterial={(type, instance) => {
        setWorkbench(null);
        setMaterial({ type, instance, nodeId: "source" });
      }}
      onSelectNode={(nodeId) => setMaterial((m) => (m ? { ...m, nodeId } : m))}
      onMaterialChanged={() => setMatRefresh((k) => k + 1)}
      onCreateCreation={(type) => void createCreation(type)}
      onCreateMaterial={(type) => void createMaterial(type)}
      onRenameInstance={(kind, type, instance) => void renameInst(kind, type, instance)}
      onDeleteInstance={(kind, type, instance) => void deleteInst(kind, type, instance)}
      onCloseWorkbench={() => setWorkbench(null)}
      onClose={close}
    />
  );
}

// Per-instance ⋯ menu (rename / delete) used by both material and creation rows.
function InstanceActions({ onRename, onDelete }: { onRename: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const item: React.CSSProperties = {
    display: "block",
    width: "100%",
    textAlign: "left",
    background: "transparent",
    color: "#ddd",
    border: "none",
    padding: "5px 10px",
    fontSize: 12,
    cursor: "pointer",
  };
  return (
    <div style={{ position: "relative", flexShrink: 0 }}>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        title={tr("hub.instance_actions")}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 22,
          height: 22,
          padding: 0,
          background: "transparent",
          color: color.textMuted,
          border: "none",
          borderRadius: radius.sm,
          cursor: "pointer",
        }}
      >
        <MoreHorizontal size={16} strokeWidth={2} />
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            zIndex: 30,
            background: "#1f1f23",
            border: "1px solid #3a3a40",
            borderRadius: 6,
            padding: 4,
            minWidth: 110,
            boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
          }}
        >
          <button style={item} onClick={() => { setOpen(false); onRename(); }}>
            {tr("hub.rename")}
          </button>
          <button style={{ ...item, color: "#e08a8a" }} onClick={() => { setOpen(false); onDelete(); }}>
            {tr("hub.delete")}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Launcher ──────────────────────────────────────────────────────────────────

function Launcher(props: {
  recents: ProjectBrief[] | null;
  busy: boolean;
  error: string;
  onOpen: (folder: string) => void;
  onPick: () => void;
}) {
  const { recents, busy, error, onOpen, onPick } = props;
  return (
    <div style={{ maxWidth: 560, margin: "0 auto", padding: "40px 24px" }}>
      <h2 style={{ fontWeight: 600, margin: "0 0 4px" }}>VideoCraft</h2>
      <p style={{ color: "#888", margin: "0 0 24px", fontSize: 13 }}>{tr("hub.launcher.subtitle")}</p>

      <button
        onClick={onPick}
        disabled={busy}
        style={{
          padding: "8px 16px",
          background: "#2d6cdf",
          color: "#fff",
          border: "none",
          borderRadius: 5,
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        {tr("hub.launcher.open_folder")}
      </button>

      {error && <p style={{ color: "#ff6b6b", marginTop: 16 }}>✗ {error}</p>}

      <h3 style={{ fontSize: 13, color: "#aaa", margin: "28px 0 8px", fontWeight: 600 }}>
        {tr("hub.launcher.recent")}
      </h3>
      {recents === null ? (
        <p style={{ color: "#888" }}>{tr("common.loading")}</p>
      ) : recents.length === 0 ? (
        <p style={{ color: "#888" }}>{tr("hub.launcher.no_recent")}</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {recents.map((p) => (
            <li key={p.folder}>
              <button
                onClick={() => onOpen(p.folder)}
                disabled={busy}
                title={p.folder}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 10px",
                  background: "transparent",
                  color: "#ddd",
                  border: "1px solid #2a2a2e",
                  borderRadius: 5,
                  marginBottom: 6,
                  cursor: "pointer",
                }}
              >
                <span style={{ fontWeight: 500 }}>{p.name}</span>
                <span
                  style={{
                    display: "block",
                    color: "#777",
                    fontSize: 11,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {p.folder}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Project view (sidebar) ────────────────────────────────────────────────────

function ProjectView(props: {
  current: ProjectBrief;
  materials: Record<string, string[]>;
  creations: Record<string, string[]>;
  readiness: Readiness;
  error: string;
  workbench: OpenWorkbench | null;
  material: { type: string; instance: string; nodeId: string | null } | null;
  matRefresh: number;
  onOpenCreation: (type: string, instance: string) => void;
  onOpenMaterial: (type: string, instance: string) => void;
  onSelectNode: (nodeId: string) => void;
  onMaterialChanged: () => void;
  onCreateCreation: (type: string) => void;
  onCreateMaterial: (type: string) => void;
  onRenameInstance: (kind: "material" | "creation", type: string, instance: string) => void;
  onDeleteInstance: (kind: "material" | "creation", type: string, instance: string) => void;
  onCloseWorkbench: () => void;
  onClose: () => void;
}) {
  const {
    current,
    materials,
    creations,
    error,
    workbench,
    material,
    matRefresh,
    onOpenCreation,
    onOpenMaterial,
    onSelectNode,
    onMaterialChanged,
    onCreateCreation,
    onCreateMaterial,
    onRenameInstance,
    onDeleteInstance,
    onCloseWorkbench,
    onClose,
  } = props;
  const matTypes = Object.entries(materials);
  const creaTypes = Object.entries(creations);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "10px 16px",
          borderBottom: "1px solid #2a2a2e",
        }}
      >
        <strong>{current.name}</strong>
        <span style={{ color: "#777", fontSize: 11 }} title={current.folder}>
          {current.folder}
        </span>
        <button
          onClick={onClose}
          style={{
            marginLeft: "auto",
            padding: "4px 10px",
            background: "#2a2a2e",
            color: "#ddd",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          {tr("hub.close_project")}
        </button>
      </header>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <aside
          style={{
            width: 340,
            flexShrink: 0,
            padding: "12px 14px",
            overflowY: "auto",
            borderRight: "1px solid #2a2a2e",
          }}
        >
          {error && <p style={{ color: "#ff6b6b" }}>✗ {error}</p>}

          <SectionTitleRow title={tr("hub.section.materials")}>
            <CreateMaterialMenu materials={materials} onCreate={onCreateMaterial} onOpen={onOpenMaterial} />
          </SectionTitleRow>
          {matTypes.length === 0 && <Empty>{tr("hub.no_materials")}</Empty>}
          {matTypes.map(([type, insts]) => (
            <div key={type} style={{ marginBottom: 10 }}>
              <TypeLabel>{type}</TypeLabel>
              {insts.length === 0 && <Empty>{tr("hub.empty_parens")}</Empty>}
              {insts.map((inst) => {
                const active = material?.type === type && material.instance === inst;
                return (
                  <MaterialInstance
                    key={inst}
                    type={type}
                    name={inst}
                    active={active}
                    selectedNodeId={active ? material!.nodeId : null}
                    matRefresh={matRefresh}
                    onOpen={() => onOpenMaterial(type, inst)}
                    onSelectNode={onSelectNode}
                    onMaterialChanged={onMaterialChanged}
                    onRename={() => onRenameInstance("material", type, inst)}
                    onDelete={() => onDeleteInstance("material", type, inst)}
                  />
                );
              })}
            </div>
          ))}

          <SectionTitleRow title={tr("hub.section.creations")}>
            <CreateCreationMenu onCreate={onCreateCreation} />
          </SectionTitleRow>
          {creaTypes.length === 0 && <Empty>{tr("hub.no_creations")}</Empty>}
          {creaTypes.map(([type, insts]) => (
            <div key={type} style={{ marginBottom: 10 }}>
              <TypeLabel>{type}</TypeLabel>
              {insts.length === 0 && <Empty>{tr("hub.empty_parens")}</Empty>}
              {insts.map((inst) => {
                const active =
                  workbench?.kind === "creation" &&
                  workbench.type === type &&
                  workbench.instance === inst;
                return (
                  <div key={inst} style={{ display: "flex", alignItems: "center", gap: 2 }}>
                    <button
                      onClick={() => onOpenCreation(type, inst)}
                      style={{
                        flex: 1,
                        minWidth: 0,
                        display: "flex",
                        alignItems: "center",
                        gap: 7,
                        textAlign: "left",
                        padding: "5px 8px",
                        border: "none",
                        borderRadius: radius.sm,
                        fontSize: font.md,
                        cursor: "pointer",
                        ...rowSelectionStyle(active),
                      }}
                    >
                      <Diamond size={14} strokeWidth={2} color={active ? color.accentText : color.textSecondary} style={{ flexShrink: 0 }} />
                      <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{inst}</span>
                    </button>
                    <InstanceActions
                      onRename={() => onRenameInstance("creation", type, inst)}
                      onDelete={() => onDeleteInstance("creation", type, inst)}
                    />
                  </div>
                );
              })}
            </div>
          ))}
        </aside>

        <main style={{ flex: 1, overflow: "auto" }}>
          {material ? (
            <MaterialDetail
              key={`m:${material.type}/${material.instance}/${material.nodeId ?? ""}`}
              type={material.type}
              instance={material.instance}
              nodeId={material.nodeId}
              refreshKey={matRefresh}
              onChanged={onMaterialChanged}
              onDeselect={() => onSelectNode("")}
            />
          ) : workbench ? (
            <CreationWorkbench
              key={`c:${workbench.type}/${workbench.instance}`}
              type={workbench.type}
              instance={workbench.instance}
              onClose={onCloseWorkbench}
            />
          ) : (
            <div style={{ padding: 24, color: "#666" }}>{tr("hub.pick_to_open")}</div>
          )}
        </main>
      </div>
    </div>
  );
}

// ── Material sidebar rows ─────────────────────────────────────────────────────

function MaterialInstance(props: {
  type: string;
  name: string;
  active: boolean;
  selectedNodeId: string | null;
  matRefresh: number;
  onOpen: () => void;
  onSelectNode: (nodeId: string) => void;
  onMaterialChanged: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const { type, name, active, selectedNodeId, matRefresh, onOpen, onSelectNode, onMaterialChanged, onRename, onDelete } = props;
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
        <button
          onClick={onOpen}
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            alignItems: "center",
            gap: 7,
            textAlign: "left",
            padding: "5px 8px",
            border: "none",
            borderRadius: radius.sm,
            fontSize: font.md,
            fontWeight: 600,
            cursor: "pointer",
            ...rowSelectionStyle(active),
          }}
        >
          <Folder size={15} strokeWidth={2} color={active ? color.accentText : color.textSecondary} style={{ flexShrink: 0 }} />
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
        </button>
        <InstanceActions onRename={onRename} onDelete={onDelete} />
      </div>
      {active && (
        <MaterialSidebar
          type={type}
          instance={name}
          selectedNodeId={selectedNodeId}
          onSelect={onSelectNode}
          refreshKey={matRefresh}
          onChanged={onMaterialChanged}
        />
      )}
    </div>
  );
}

// A section title with trailing controls on the same row (e.g. the 创作 [+]).
function SectionTitleRow({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", margin: "14px 0 6px" }}>
      <h3
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: 0.5,
          color: "#888",
          margin: 0,
          fontWeight: 700,
        }}
      >
        {title}
      </h3>
      <div style={{ marginLeft: "auto" }}>{children}</div>
    </div>
  );
}

// [+] menu listing registered creation types (descriptions, never type_name).
function CreateCreationMenu({ onCreate }: { onCreate: (type: string) => void }) {
  const [open, setOpen] = useState(false);
  const [types, setTypes] = useState<CreationTypeInfo[] | null>(null);

  const toggle = useCallback(() => {
    setOpen((o) => !o);
    if (types === null) {
      void rpc
        .listCreationTypes()
        .then(setTypes)
        .catch(() => setTypes([]));
    }
  }, [types]);

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={toggle}
        title={tr("hub.new_creation")}
        style={{
          width: 22,
          height: 20,
          lineHeight: "18px",
          padding: 0,
          background: "#2a2a2e",
          color: "#ccc",
          border: "1px solid #3a3a40",
          borderRadius: 4,
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        +
      </button>
      {open && (
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
            minWidth: 200,
            boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
          }}
        >
          {types === null ? (
            <div style={{ padding: "5px 8px", color: "#888", fontSize: 12 }}>{tr("common.loading")}</div>
          ) : types.length === 0 ? (
            <div style={{ padding: "5px 8px", color: "#888", fontSize: 12 }}>{tr("hub.no_types")}</div>
          ) : (
            types.map((t) => (
              <button
                key={t.type_name}
                onClick={() => {
                  setOpen(false);
                  onCreate(t.type_name);
                }}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  background: "transparent",
                  color: "#ddd",
                  border: "none",
                  borderRadius: 4,
                  padding: "5px 8px",
                  fontSize: 13,
                  cursor: "pointer",
                }}
                title={descOf(t)}
              >
                {descOf(t) || t.type_name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// [+] menu listing registered material types. For a single-instance type that
// already has an instance, the item opens it instead of creating a broken 2nd
// (source/ASR are still project-level — see the news_video single_instance note).
function CreateMaterialMenu(props: {
  materials: Record<string, string[]>;
  onCreate: (type: string) => void;
  onOpen: (type: string, instance: string) => void;
}) {
  const { materials, onCreate, onOpen } = props;
  const [open, setOpen] = useState(false);
  const [types, setTypes] = useState<MaterialTypeInfo[] | null>(null);

  const toggle = useCallback(() => {
    setOpen((o) => !o);
    if (types === null) {
      void rpc
        .listMaterialTypes()
        .then(setTypes)
        .catch(() => setTypes([]));
    }
  }, [types]);

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={toggle}
        title={tr("hub.new_material")}
        style={{
          width: 22,
          height: 20,
          lineHeight: "18px",
          padding: 0,
          background: "#2a2a2e",
          color: "#ccc",
          border: "1px solid #3a3a40",
          borderRadius: 4,
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        +
      </button>
      {open && (
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
            minWidth: 220,
            boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
          }}
        >
          {types === null ? (
            <div style={{ padding: "5px 8px", color: "#888", fontSize: 12 }}>{tr("common.loading")}</div>
          ) : types.length === 0 ? (
            <div style={{ padding: "5px 8px", color: "#888", fontSize: 12 }}>{tr("hub.no_types")}</div>
          ) : (
            types.map((t) => {
              const existing = materials[t.type_name] ?? [];
              // Single-instance + already created → offer to open it, not re-create.
              const openExisting = t.single_instance && existing.length > 0;
              const label = openExisting
                ? tr("hub.open_existing", { name: existing[0]! })
                : descOf(t) || t.type_name;
              return (
                <button
                  key={t.type_name}
                  onClick={() => {
                    setOpen(false);
                    if (openExisting) onOpen(t.type_name, existing[0]!);
                    else onCreate(t.type_name);
                  }}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    background: "transparent",
                    color: "#ddd",
                    border: "none",
                    borderRadius: 4,
                    padding: "5px 8px",
                    fontSize: 13,
                    cursor: "pointer",
                  }}
                  title={descOf(t)}
                >
                  {label}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

function TypeLabel({ children }: { children: ReactNode }) {
  return <div style={{ fontSize: 11, color: "#6a9", marginBottom: 2 }}>{children}</div>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div style={{ fontSize: 12, color: "#666", padding: "2px 8px" }}>{children}</div>;
}
