/**
 * MaterialBindingBar — the shared material-binding control for creation
 * workbenches (ADR-0005). A new-arch creation is created unbound; this is the
 * headless replacement for the Tk material picker. Always visible (binding is a
 * persistent setting, not a one-time gate): shows the bound material and lets the
 * user (re-)bind at any time. Lists every material instance in the project (no
 * type filter, faithful to material_binding.show_material_picker).
 *
 * Extracted from the news_desk Style tab so clip (and future creations) reuse the
 * same control — binding is a framework concern, not per-plugin.
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError } from "../../ipc/client";
import { tr } from "../../i18n/tr";

const SEL: React.CSSProperties = {
  background: "#222",
  color: "#ddd",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "3px 6px",
  fontSize: 12,
  minWidth: 160,
};
const BIND_BTN: React.CSSProperties = {
  background: "#2d6cdf",
  color: "#fff",
  border: "none",
  borderRadius: 4,
  padding: "3px 12px",
  fontSize: 12,
  cursor: "pointer",
};
const PLAIN_BTN: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ccc",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "3px 9px",
  fontSize: 12,
  cursor: "pointer",
};

export function MaterialBindingBar(props: {
  type: string;
  instance: string;
  refreshKey: number;
  onBound: () => void;
}) {
  const { type, instance, refreshKey, onBound } = props;
  const [bound, setBound] = useState<{ matType: string; matInstance: string } | null>(null);
  const [entries, setEntries] = useState<{ matType: string; matInstance: string }[]>([]);
  const [editing, setEditing] = useState(false);
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // Read the current binding + the project's material instances. Re-runs on
  // refreshKey so an external change (or our own bind) is reflected.
  useEffect(() => {
    let alive = true;
    void rpc
      .loadConfig(type, instance)
      .then((cfg) => {
        if (!alive) return;
        const bm = cfg["bound_material"] as
          | { type_name?: string; instance_name?: string }
          | null;
        setBound(
          bm?.type_name && bm.instance_name
            ? { matType: bm.type_name, matInstance: bm.instance_name }
            : null,
        );
      })
      .catch(() => {});
    void rpc
      .listMaterials()
      .then((m) => {
        if (!alive) return;
        const flat: { matType: string; matInstance: string }[] = [];
        for (const [t, insts] of Object.entries(m)) {
          for (const i of insts) flat.push({ matType: t, matInstance: i });
        }
        setEntries(flat);
        setChoice((cur) => cur || (flat.length ? `${flat[0]!.matType}/${flat[0]!.matInstance}` : ""));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [type, instance, refreshKey]);

  const doBind = useCallback(async () => {
    const e = entries.find((x) => `${x.matType}/${x.matInstance}` === choice);
    if (!e) return;
    setBusy(true);
    setErr("");
    try {
      await rpc.bindMaterial(type, instance, e.matType, e.matInstance);
      setBound(e);
      setEditing(false);
      onBound();
    } catch (er) {
      setErr(er instanceof RpcError ? `[${er.code}] ${er.message}` : String(er));
    } finally {
      setBusy(false);
    }
  }, [type, instance, choice, entries, onBound]);

  const picking = editing || !bound;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 16px 0", flexWrap: "wrap" }}>
      <span style={{ fontSize: 12, color: "#888" }}>{tr("bind.label")}</span>
      {picking ? (
        entries.length === 0 ? (
          <span style={{ fontSize: 12, color: "#c87" }}>{tr("bind.none")}</span>
        ) : (
          <>
            <select value={choice} onChange={(e) => setChoice(e.target.value)} style={SEL}>
              {entries.map((e) => (
                <option key={`${e.matType}/${e.matInstance}`} value={`${e.matType}/${e.matInstance}`}>
                  {e.matInstance} · {e.matType}
                </option>
              ))}
            </select>
            <button onClick={() => void doBind()} disabled={busy || !choice} style={{ ...BIND_BTN, opacity: busy ? 0.6 : 1 }}>
              {tr("bind.bind")}
            </button>
            {bound && (
              <button onClick={() => setEditing(false)} style={PLAIN_BTN}>
                {tr("common.cancel")}
              </button>
            )}
          </>
        )
      ) : (
        <>
          <span style={{ fontSize: 12, color: "#ddd" }}>
            {bound!.matInstance} <span style={{ color: "#777" }}>· {bound!.matType}</span>
          </span>
          <button onClick={() => setEditing(true)} style={PLAIN_BTN}>
            {tr("bind.rebind")}
          </button>
        </>
      )}
      {err && <span style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {err}</span>}
    </div>
  );
}
