/**
 * Export tab (导出) — news_desk composes the FULL source into ONE output
 * (news_desk_tool.py::_do_export), unlike clip's per-candidate batch. This tab
 * shows the render plan (single output.mp4 path + media + duration) and the
 * persisted rendered state, read-only.
 *
 * Deferred to a live-verify increment (NOT dropped): the actual render trigger
 * (buildNewsDeskTimeline → GPU engine → encode → vc:writeFile → commit_render),
 * which mirrors clip's ExportTab render loop but for one full-source output.
 * That path can only be confirmed in a live Electron run, so it lands with its
 * verification rather than as an untested button here.
 */

import { useCallback, useEffect, useState } from "react";
import { rpcCall, RpcError } from "../../ipc/client";

/** news_desk render plan (creation.plan_render — single full-source output). */
interface NewsDeskRenderPlan {
  instanceDir: string;
  mediaRef: string | null;
  durationSec: number;
  outIdx: number;
  outputPath: string;
}

interface RenderedEntry {
  file: string;
  output_index: number;
  duration_sec: number;
  rendered_at: string;
}

function fmtErr(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

function fmtDuration(sec: number): string {
  if (!sec || sec <= 0) return "—";
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

export function ExportTab(props: { type: string; instance: string; active: boolean }) {
  const { type, instance, active } = props;
  const [plan, setPlan] = useState<NewsDeskRenderPlan | null>(null);
  const [rendered, setRendered] = useState<RenderedEntry[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [p, cfg] = await Promise.all([
        rpcCall<NewsDeskRenderPlan>("creation.plan_render", { type, instance }),
        rpcCall<Record<string, unknown>>("creation.load_config", { type, instance }),
      ]);
      setPlan(p);
      const r = cfg["rendered"];
      setRendered(Array.isArray(r) ? (r as RenderedEntry[]) : []);
    } catch (err) {
      setError(fmtErr(err));
    } finally {
      setLoading(false);
    }
  }, [type, instance]);

  // Refresh when this tab becomes active (config may have changed in Style).
  useEffect(() => {
    if (active) void load();
  }, [active, load]);

  const row: React.CSSProperties = { display: "flex", gap: 10, padding: "4px 0", fontSize: 13 };
  const key: React.CSSProperties = { color: "#888", minWidth: 90 };
  const val: React.CSSProperties = { color: "#ddd", wordBreak: "break-all" };

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#ccc" }}>导出</span>
        <button
          onClick={() => void load()}
          disabled={loading}
          style={{
            marginLeft: "auto",
            background: "#2a2a2e",
            color: "#ccc",
            border: "1px solid #3a3a40",
            borderRadius: 4,
            padding: "2px 10px",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          刷新
        </button>
      </div>

      {error && <p style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {error}</p>}
      {loading && <p style={{ color: "#888", fontSize: 12 }}>加载中…</p>}

      {plan && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>
            渲染计划(整源单输出)
          </div>
          {plan.mediaRef ? (
            <>
              <div style={row}>
                <span style={key}>时长</span>
                <span style={val}>{fmtDuration(plan.durationSec)}</span>
              </div>
              <div style={row}>
                <span style={key}>输出文件</span>
                <span style={val}>{plan.outputPath}</span>
              </div>
            </>
          ) : (
            <p style={{ color: "#888", fontSize: 12 }}>未绑定素材 — 无法导出</p>
          )}
        </div>
      )}

      <div style={{ fontSize: 11, color: "#888", fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>
        已渲染
      </div>
      {rendered.length === 0 ? (
        <p style={{ color: "#888", fontSize: 12 }}>尚未渲染</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {rendered.map((r) => (
            <li key={r.output_index} style={{ ...row, borderBottom: "1px solid #222" }}>
              <span style={val}>{r.file}</span>
              <span style={{ color: "#777", marginLeft: "auto" }}>{fmtDuration(r.duration_sec)}</span>
              <span style={{ color: "#666" }}>{r.rendered_at}</span>
            </li>
          ))}
        </ul>
      )}

      <p style={{ color: "#666", fontSize: 11, marginTop: 16 }}>
        渲染管线(整源合成 → 编码 → 写盘)待后续迭代,需真机验证。
      </p>
    </div>
  );
}
