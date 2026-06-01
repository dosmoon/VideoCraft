/**
 * ModelManager — the 📦 panel: download / install / remove the embedded-AI models
 * (faster-whisper, Qwen3 GGUF) via the models.* RPC. Installed state is a cheap
 * disk check from models.catalog; live download progress streams in over the
 * `event.models` notification (one DownloadManager → one bridge → all rows).
 *
 * Deferred (still Tk-only): CUDA-wheel GPU setup, change-models-dir, tier-batch.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { rpc, RpcError, type ModelCatalogEntry, type ModelJob } from "../ipc/client";
import { tr } from "../i18n/tr";

function fmtBytes(n: number): string {
  if (n <= 0) return "0";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
}

function fmtErr(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

const CARD: React.CSSProperties = {
  border: "1px solid #2a2a2e",
  borderRadius: 6,
  padding: "10px 12px",
  marginBottom: 8,
};
const BTN: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ddd",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  fontSize: 12,
  padding: "3px 10px",
  cursor: "pointer",
};

export function ModelManager() {
  const [catalog, setCatalog] = useState<ModelCatalogEntry[] | null>(null);
  const [jobs, setJobs] = useState<ModelJob[]>([]);
  const [error, setError] = useState("");
  const doneSeen = useRef<Set<string>>(new Set());

  const loadCatalog = useCallback(() => {
    rpc
      .modelsCatalog()
      .then(setCatalog)
      .catch((e) => setError(fmtErr(e)));
  }, []);

  useEffect(() => {
    loadCatalog();
    rpc.modelsJobs().then(setJobs).catch(() => {});
    const unsub = rpc.onNotification((method, params) => {
      if (method !== "event.models") return;
      const next = (params as { jobs?: ModelJob[] } | null)?.jobs ?? [];
      setJobs(next);
      // When a job finishes, the installed state changed — re-scan the catalog.
      for (const j of next) {
        if (j.state === "done" && !doneSeen.current.has(j.job_id)) {
          doneSeen.current.add(j.job_id);
          loadCatalog();
        }
      }
    });
    return unsub;
  }, [loadCatalog]);

  // Latest job per model_id (so a row knows if it's downloading).
  const jobByModel = new Map<string, ModelJob>();
  for (const j of jobs) jobByModel.set(j.model_id, j);

  const download = (id: string) =>
    rpc.modelsDownload(id).catch((e) => setError(fmtErr(e)));
  const cancel = (jobId: string) => rpc.modelsCancel(jobId).catch((e) => setError(fmtErr(e)));
  const remove = (m: ModelCatalogEntry) => {
    if (!window.confirm(tr("models.remove_confirm", { name: m.name }))) return;
    rpc
      .modelsRemove(m.id)
      .then(loadCatalog)
      .catch((e) => setError(fmtErr(e)));
  };

  // Group by capability for section headers.
  const groups = new Map<string, ModelCatalogEntry[]>();
  for (const m of catalog ?? []) {
    const g = groups.get(m.capability) ?? [];
    g.push(m);
    groups.set(m.capability, g);
  }

  return (
    <div style={{ padding: "16px 20px", maxWidth: 760, margin: "0 auto" }}>
      <h2 style={{ fontWeight: 600, margin: "0 0 4px" }}>{tr("models.title")}</h2>
      <p style={{ color: "#888", fontSize: 12, margin: "0 0 14px" }}>{tr("models.gpu_note")}</p>
      {error && <p style={{ color: "#ff6b6b" }}>✗ {error}</p>}
      {catalog === null ? (
        <p style={{ color: "#888" }}>{tr("common.loading")}</p>
      ) : catalog.length === 0 ? (
        <p style={{ color: "#888" }}>{tr("models.empty")}</p>
      ) : (
        [...groups.entries()].map(([cap, rows]) => (
          <div key={cap} style={{ marginBottom: 14 }}>
            <h3 style={{ fontSize: 12, color: "#6a9", margin: "0 0 6px", fontWeight: 700 }}>
              {tr(`models.cap.${cap}`)}
            </h3>
            {rows.map((m) => (
              <ModelRow
                key={m.id}
                model={m}
                job={jobByModel.get(m.id)}
                onDownload={() => download(m.id)}
                onCancel={cancel}
                onRemove={() => remove(m)}
              />
            ))}
          </div>
        ))
      )}
    </div>
  );
}

function ModelRow({
  model: m,
  job,
  onDownload,
  onCancel,
  onRemove,
}: {
  model: ModelCatalogEntry;
  job: ModelJob | undefined;
  onDownload: () => void;
  onCancel: (jobId: string) => void;
  onRemove: () => void;
}) {
  const active = job && (job.state === "running" || job.state === "queued");
  return (
    <div style={CARD}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{m.name}</span>
        <span style={{ fontSize: 11, color: "#888" }}>{tr(`models.tier.${m.tier}`)}</span>
        <span style={{ fontSize: 11, color: "#777" }}>{tr(`models.for.${m.recommended_for}`)}</span>
        <span style={{ marginLeft: "auto", fontSize: 12, color: m.installed ? "#7fd17f" : "#888" }}>
          {m.installed
            ? tr("models.installed")
            : m.present > 0
              ? tr("models.partial", { present: m.present, total: m.total })
              : ""}
        </span>
        {active ? (
          <button onClick={() => onCancel(job!.job_id)} style={BTN}>
            {tr("common.cancel")}
          </button>
        ) : m.installed ? (
          <button onClick={onRemove} style={BTN}>
            {tr("models.remove")}
          </button>
        ) : (
          <button onClick={onDownload} style={{ ...BTN, background: "#2d6cdf", color: "#fff", border: "none" }}>
            {tr("models.download")}
          </button>
        )}
      </div>
      {m.description && <div style={{ fontSize: 11, color: "#888", marginTop: 4 }}>{m.description}</div>}
      {active && job && (
        <div style={{ marginTop: 8 }}>
          <div style={{ height: 5, background: "#222", borderRadius: 3, overflow: "hidden" }}>
            <div
              style={{
                width: `${Math.round(job.fraction * 100)}%`,
                height: "100%",
                background: "#2d6cdf",
                transition: "width 0.2s",
              }}
            />
          </div>
          <div style={{ fontSize: 11, color: "#888", marginTop: 3 }}>
            {job.state === "queued"
              ? tr("models.queued")
              : tr("models.downloading", {
                  pct: Math.round(job.fraction * 100),
                  done: fmtBytes(job.bytes_done),
                  total: fmtBytes(job.bytes_total),
                  speed: fmtBytes(job.bytes_per_sec),
                })}
          </div>
        </div>
      )}
      {job && job.state === "failed" && (
        <div style={{ fontSize: 11, color: "#d98b8b", marginTop: 4 }}>
          ✗ {job.error || tr("models.failed")}
        </div>
      )}
    </div>
  );
}
