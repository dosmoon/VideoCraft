/**
 * SourceTab — the news_video source-video slot. Acquire a source either by local
 * file import (vc:pickVideo → copy/cut) or yt-dlp download (URL → download), both
 * as sidecar jobs (material.set_source) consumed via runJob. Faithful to the Tk
 * source_add_dialog (origin link|local + optional clip range) + source_prepare_modal
 * (category-keyed recovery hints).
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type AcquireSource, type SourceMeta } from "../../ipc/client";
import { useJob } from "../../ipc/runJob";

export interface MaterialTabProps {
  type: string;
  instance: string;
  refreshKey: number;
  onChanged: () => void;
}

// AcquireError category (prefix of the failed job's message) → recovery hint.
const CATEGORY_HINTS: Record<string, string> = {
  network: "网络问题，请检查连接后重试。",
  url_invalid: "链接无效或不受支持，请检查 URL。",
  js_runtime: "缺少 Node.js JS 运行时（yt-dlp 需要）—— 安装 Node.js 后重试。",
  cookies: "该视频需要登录 / cookies 才能访问。",
  disk: "磁盘问题（空间不足或写入失败）。",
  ffmpeg: "ffmpeg / ffprobe 不可用或处理失败。",
  other: "导入失败。",
};

function hintFor(error: string): string {
  const cat = error.split(":", 1)[0]?.trim();
  return (cat && CATEGORY_HINTS[cat]) || error;
}

function fmtDuration(sec?: number): string {
  if (!sec || sec <= 0) return "";
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}` : `${m}:${String(ss).padStart(2, "0")}`;
}

const INPUT: React.CSSProperties = {
  padding: "4px 8px",
  background: "#1a1a1e",
  color: "#ddd",
  border: "1px solid #333",
  borderRadius: 4,
  fontSize: 13,
};
const BTN: React.CSSProperties = {
  padding: "6px 14px",
  background: "#2d6cdf",
  color: "#fff",
  border: "none",
  borderRadius: 5,
  fontSize: 13,
  cursor: "pointer",
};
const BTN_GHOST: React.CSSProperties = {
  ...BTN,
  background: "#2a2a2e",
  color: "#ddd",
};

export function SourceTab({ type, instance, refreshKey, onChanged }: MaterialTabProps) {
  const [meta, setMeta] = useState<SourceMeta | null>(null);
  const [filled, setFilled] = useState(false);
  const [summary, setSummary] = useState("");
  const [srcUrl, setSrcUrl] = useState("");
  const [mode, setMode] = useState<"local" | "link">("local");
  const [url, setUrl] = useState("");
  const [useRange, setUseRange] = useState(false);
  const [rangeStart, setRangeStart] = useState("");
  const [rangeEnd, setRangeEnd] = useState("");
  const [reimport, setReimport] = useState(false);
  const [loadErr, setLoadErr] = useState("");
  const job = useJob();

  const reload = useCallback(async () => {
    setLoadErr("");
    try {
      const [m, r] = await Promise.all([
        rpc.materialSourceMeta(type, instance),
        rpc.slotReadiness(type, instance),
      ]);
      setMeta(m);
      const isFilled = r.source?.is_filled ?? false;
      setFilled(isFilled);
      setSummary(r.source?.summary ?? "");
      if (isFilled) {
        const path = await rpc.getArtifact(type, instance, "source");
        setSrcUrl(path ? window.vc.mediaUrl(path) : "");
      } else {
        setSrcUrl("");
      }
    } catch (err) {
      setLoadErr(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
    }
  }, [type, instance]);

  useEffect(() => {
    void reload();
  }, [reload, refreshKey]);

  const rangeParams = useCallback((): Pick<AcquireSource, "clip_range"> => {
    if (useRange && rangeStart.trim() && rangeEnd.trim()) {
      return { clip_range: { start: rangeStart.trim(), end: rangeEnd.trim() } };
    }
    return {};
  }, [useRange, rangeStart, rangeEnd]);

  const acquire = useCallback(
    async (source: AcquireSource) => {
      const res = await job.run<{ title?: string }>(() => rpc.startSetSource(type, instance, source));
      if (res !== undefined) {
        setReimport(false);
        onChanged();
        await reload();
      }
    },
    [job, type, instance, onChanged, reload],
  );

  const acquireLocal = useCallback(async () => {
    const path = await window.vc.pickVideo();
    if (!path) return;
    await acquire({ origin: "local", imported_from: path, ...rangeParams() });
  }, [acquire, rangeParams]);

  const acquireLink = useCallback(async () => {
    if (!url.trim()) return;
    await acquire({ origin: "link", url: url.trim(), ...rangeParams() });
  }, [acquire, url, rangeParams]);

  const showPicker = !filled || reimport;

  return (
    <div style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 14 }}>
      {loadErr && <div style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {loadErr}</div>}

      {/* Acquired-source summary card */}
      {filled && (
        <div style={{ padding: "10px 12px", background: "#1c1c20", borderRadius: 6, border: "1px solid #2a2a2e" }}>
          <div style={{ color: "#7fd17f", fontSize: 13, marginBottom: 4 }}>
            ✓ {meta?.title || "video.mp4"}
          </div>
          <div style={{ color: "#999", fontSize: 12 }}>
            {[
              meta?.duration_sec ? fmtDuration(meta.duration_sec) : "",
              meta?.width && meta?.height ? `${meta.width}×${meta.height}` : "",
              meta?.origin === "link" ? meta.url : meta?.imported_from,
            ]
              .filter(Boolean)
              .join("  ·  ") || summary}
          </div>
          {srcUrl && (
            <video
              src={srcUrl}
              controls
              style={{ display: "block", marginTop: 8, maxWidth: "100%", maxHeight: 300, borderRadius: 4, background: "#000" }}
            />
          )}
          {!reimport && (
            <button onClick={() => setReimport(true)} style={{ ...BTN_GHOST, marginTop: 8, padding: "4px 10px", fontSize: 12 }}>
              重新导入…
            </button>
          )}
        </div>
      )}

      {/* Acquisition picker */}
      {showPicker && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filled && reimport && (
            <div style={{ color: "#d9a441", fontSize: 12 }}>⚠ 重新导入会覆盖当前源视频。</div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <ModeBtn label="本地文件" active={mode === "local"} onClick={() => setMode("local")} />
            <ModeBtn label="链接下载 (yt-dlp)" active={mode === "link"} onClick={() => setMode("link")} />
          </div>

          {mode === "link" && (
            <input
              value={url}
              placeholder="粘贴视频链接 (YouTube / Bilibili / …)"
              disabled={job.running}
              onChange={(e) => setUrl(e.target.value)}
              style={{ ...INPUT, width: "100%", boxSizing: "border-box" }}
            />
          )}

          {/* Optional clip range */}
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#bbb" }}>
            <input type="checkbox" checked={useRange} disabled={job.running} onChange={(e) => setUseRange(e.target.checked)} />
            只截取时间段
          </label>
          {useRange && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input value={rangeStart} placeholder="开始 00:00" disabled={job.running} onChange={(e) => setRangeStart(e.target.value)} style={{ ...INPUT, width: 110 }} />
              <span style={{ color: "#666" }}>→</span>
              <input value={rangeEnd} placeholder="结束 10:00" disabled={job.running} onChange={(e) => setRangeEnd(e.target.value)} style={{ ...INPUT, width: 110 }} />
            </div>
          )}

          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {mode === "local" ? (
              <button onClick={() => void acquireLocal()} disabled={job.running} style={BTN}>
                选择本地文件…
              </button>
            ) : (
              <button onClick={() => void acquireLink()} disabled={job.running || !url.trim()} style={BTN}>
                下载
              </button>
            )}
            {filled && reimport && (
              <button onClick={() => setReimport(false)} disabled={job.running} style={BTN_GHOST}>
                取消
              </button>
            )}
          </div>
        </div>
      )}

      {/* Progress + cancel */}
      {job.running && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: "#4a9eff" }}>
            {job.progress?.status_text || job.progress?.phase || "处理中"}
            {job.progress?.pct != null ? ` · ${Math.round(job.progress.pct)}%` : ""}
          </span>
          <button onClick={job.cancel} style={{ ...BTN_GHOST, padding: "3px 10px", fontSize: 12 }}>
            取消
          </button>
        </div>
      )}

      {job.error && <div style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {hintFor(job.error)}</div>}
    </div>
  );
}

function ModeBtn(props: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={props.onClick}
      style={{
        padding: "5px 12px",
        background: props.active ? "#2d6cdf" : "#2a2a2e",
        color: props.active ? "#fff" : "#bbb",
        border: "none",
        borderRadius: 5,
        fontSize: 12,
        cursor: "pointer",
      }}
    >
      {props.label}
    </button>
  );
}
