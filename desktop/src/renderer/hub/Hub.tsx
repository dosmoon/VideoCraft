/**
 * Hub — the first real product-UI slice, driven entirely by the read-only
 * sidecar RPC (project.recent_list/open/close/current, project.list_materials/
 * list_creations, material.slot_readiness). It replaces nothing yet: the spike
 * harness stays reachable via the Shell toggle (additive, per the "new UI must
 * not swallow existing tools" rule).
 *
 * Scope (migration doc §0.5 — the Electron shell is framework + 素材 + 创作;
 * the legacy Tk menubar tools are cut): a project launcher and a material
 * sidebar tree. Workbenches + the tab-0 preview model land in later slices.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { rpc, RpcError, type Component, type ProjectBrief, type SlotState } from "../ipc/client";

// Friendly labels for the news_video slots (placeholder — real i18n later).
const SLOT_LABELS: Record<string, string> = {
  source: "源视频",
  news_context: "新闻背景",
  subtitles: "字幕",
};

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
  // The open creation workbench (one at a time for this slice), or none.
  const [workbench, setWorkbench] = useState<{ type: string; instance: string } | null>(null);

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
      onOpenCreation={(type, instance) => setWorkbench({ type, instance })}
      onCloseWorkbench={() => setWorkbench(null)}
      onClose={close}
    />
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
      <p style={{ color: "#888", margin: "0 0 24px", fontSize: 13 }}>选择一个项目打开</p>

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
        打开文件夹…
      </button>

      {error && <p style={{ color: "#ff6b6b", marginTop: 16 }}>✗ {error}</p>}

      <h3 style={{ fontSize: 13, color: "#aaa", margin: "28px 0 8px", fontWeight: 600 }}>
        最近项目
      </h3>
      {recents === null ? (
        <p style={{ color: "#888" }}>加载中…</p>
      ) : recents.length === 0 ? (
        <p style={{ color: "#888" }}>暂无最近项目</p>
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
  workbench: { type: string; instance: string } | null;
  onOpenCreation: (type: string, instance: string) => void;
  onCloseWorkbench: () => void;
  onClose: () => void;
}) {
  const {
    current,
    materials,
    creations,
    readiness,
    error,
    workbench,
    onOpenCreation,
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
          关闭项目
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

          <SectionTitle>素材</SectionTitle>
          {matTypes.length === 0 && <Empty>无素材</Empty>}
          {matTypes.map(([type, insts]) => (
            <div key={type} style={{ marginBottom: 10 }}>
              <TypeLabel>{type}</TypeLabel>
              {insts.length === 0 && <Empty>（空）</Empty>}
              {insts.map((inst) => (
                <MaterialInstance key={inst} name={inst} slots={readiness[`${type}/${inst}`]} />
              ))}
            </div>
          ))}

          <SectionTitle>创作</SectionTitle>
          {creaTypes.length === 0 && <Empty>无创作</Empty>}
          {creaTypes.map(([type, insts]) => (
            <div key={type} style={{ marginBottom: 10 }}>
              <TypeLabel>{type}</TypeLabel>
              {insts.length === 0 && <Empty>（空）</Empty>}
              {insts.map((inst) => {
                const active = workbench?.type === type && workbench?.instance === inst;
                return (
                  <button
                    key={inst}
                    onClick={() => onOpenCreation(type, inst)}
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      padding: "4px 8px",
                      color: active ? "#fff" : "#ccc",
                      background: active ? "#2d6cdf" : "transparent",
                      border: "none",
                      borderRadius: 4,
                      fontSize: 13,
                      cursor: "pointer",
                    }}
                  >
                    ◆ {inst}
                  </button>
                );
              })}
            </div>
          ))}
        </aside>

        <main style={{ flex: 1, overflow: "auto" }}>
          {workbench ? (
            <Workbench
              key={`${workbench.type}/${workbench.instance}`}
              type={workbench.type}
              instance={workbench.instance}
              onClose={onCloseWorkbench}
            />
          ) : (
            <div style={{ padding: 24, color: "#666" }}>选择一个创作以打开工作台</div>
          )}
        </main>
      </div>
    </div>
  );
}

// ── Creation workbench (component list + enabled toggle) ──────────────────────

function Workbench(props: { type: string; instance: string; onClose: () => void }) {
  const { type, instance, onClose } = props;
  const [components, setComponents] = useState<Component[] | null>(null);
  const [error, setError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setComponents(await rpc.listComponents(type, instance));
    } catch (err) {
      setError(fmt(err));
    }
  }, [type, instance]);

  useEffect(() => {
    setComponents(null);
    setError("");
    void reload();
  }, [reload]);

  const toggle = useCallback(
    async (comp: Component) => {
      setSavingId(comp.id);
      setError("");
      try {
        await rpc.updateComponent(type, instance, comp.id, { enabled: !(comp.enabled ?? true) });
        await reload(); // re-read so the UI reflects the persisted state
      } catch (err) {
        setError(fmt(err));
      } finally {
        setSavingId(null);
      }
    },
    [type, instance, reload],
  );

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <strong>{instance}</strong>
        <span style={{ color: "#777", fontSize: 12 }}>{type} · 组件</span>
        <button
          onClick={onClose}
          style={{
            marginLeft: "auto",
            padding: "2px 9px",
            background: "#2a2a2e",
            color: "#ddd",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          ✕
        </button>
      </div>

      {error && <p style={{ color: "#ff6b6b" }}>✗ {error}</p>}

      {components === null ? (
        <p style={{ color: "#888" }}>加载中…</p>
      ) : components.length === 0 ? (
        <p style={{ color: "#888" }}>无组件</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {components.map((c) => (
            <li
              key={c.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "6px 8px",
                borderBottom: "1px solid #222",
              }}
            >
              <input
                type="checkbox"
                checked={c.enabled ?? true}
                disabled={savingId === c.id}
                onChange={() => void toggle(c)}
              />
              <span style={{ fontWeight: 500, color: "#ddd", fontSize: 13 }}>{c.kind}</span>
              <span style={{ color: "#777", fontSize: 11 }}>{c.id}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MaterialInstance(props: { name: string; slots: Record<string, SlotState> | undefined }) {
  const { name, slots } = props;
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ padding: "4px 8px", color: "#ddd", fontSize: 13, fontWeight: 500 }}>
        📁 {name}
      </div>
      {slots &&
        Object.values(slots).map((s) => <SlotRow key={s.slot_id} slot={s} />)}
    </div>
  );
}

function SlotRow({ slot }: { slot: SlotState }) {
  const icon = slot.is_locked ? "🔒" : slot.is_filled ? "✓" : "✗";
  const color = slot.is_locked ? "#777" : slot.is_filled ? "#7fd17f" : "#d98b8b";
  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        padding: "2px 8px 2px 22px",
        fontSize: 12,
        color: "#bbb",
      }}
    >
      <span style={{ color, width: 14, flexShrink: 0 }}>{icon}</span>
      <span style={{ width: 56, flexShrink: 0, color: "#999" }}>
        {SLOT_LABELS[slot.slot_id] ?? slot.slot_id}
      </span>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {slot.summary}
      </span>
    </div>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h3
      style={{
        fontSize: 11,
        textTransform: "uppercase",
        letterSpacing: 0.5,
        color: "#888",
        margin: "14px 0 6px",
        fontWeight: 700,
      }}
    >
      {children}
    </h3>
  );
}

function TypeLabel({ children }: { children: ReactNode }) {
  return <div style={{ fontSize: 11, color: "#6a9", marginBottom: 2 }}>{children}</div>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div style={{ fontSize: 12, color: "#666", padding: "2px 8px" }}>{children}</div>;
}
