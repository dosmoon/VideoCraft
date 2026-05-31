/**
 * ContextTab — the 15-field news context (materials/news_video/schema.SourceContext).
 * Each field commits on blur → material.write_context (whole dict; server
 * normalizes + counts). The completion badge reflects filled/total. AI-fill
 * (slice M5) seeds from the 5 basic_info hints and replaces the whole context.
 *
 * Faithful to the Tk source_context_dialog (entry fields + multiline for the
 * long ones) + news_context_pane (AI fill / manual edit).
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type SourceBasicInfo, type SourceContext } from "../../ipc/client";
import { useJob } from "../../ipc/runJob";
import { Section, TextRow, TextAreaRow } from "../shared/fields";
import type { MaterialTabProps } from "./SourceTab";

// The 5 basic_info hint fields (AI-fill seed). Input-only; AI replaces context.
const SEED_FIELDS: { key: keyof SourceBasicInfo; label: string }[] = [
  { key: "host", label: "主讲人" },
  { key: "host_bio", label: "身份" },
  { key: "event_date", label: "事件日期" },
  { key: "event_location", label: "事件地点" },
  { key: "episode_topic", label: "整集主题" },
];

const EMPTY_SEED: SourceBasicInfo = {
  host: "",
  host_bio: "",
  event_date: "",
  event_location: "",
  episode_topic: "",
};

// Ordered field layout (grouped). `multiline` fields use a textarea.
type FieldKey = keyof SourceContext;
const GROUPS: { title: string; fields: { key: FieldKey; label: string; rows?: number }[] }[] = [
  {
    title: "锚点（AI 校正后的权威写法）",
    fields: [
      { key: "host", label: "主讲人" },
      { key: "host_bio", label: "身份" },
      { key: "event_date", label: "事件日期" },
      { key: "event_location", label: "事件地点" },
      { key: "episode_topic", label: "整集主题" },
    ],
  },
  {
    title: "人物",
    fields: [
      { key: "host_affiliation", label: "所属机构" },
      { key: "guests", label: "嘉宾/在场" },
    ],
  },
  { title: "时间", fields: [{ key: "event_time", label: "事件时间" }] },
  {
    title: "事件",
    fields: [
      { key: "show_type", label: "节目类型" },
      { key: "event_summary", label: "事件概述", rows: 3 },
      { key: "key_points", label: "核心要点", rows: 4 },
    ],
  },
  { title: "背景", fields: [{ key: "background", label: "背景", rows: 5 }] },
  {
    title: "制作",
    fields: [
      { key: "audience", label: "观众" },
      { key: "platform_tone", label: "发布平台" },
      { key: "notes", label: "备注", rows: 3 },
    ],
  },
];

const EMPTY: SourceContext = {
  host: "",
  host_bio: "",
  event_date: "",
  event_location: "",
  episode_topic: "",
  host_affiliation: "",
  guests: "",
  event_time: "",
  show_type: "",
  event_summary: "",
  key_points: "",
  background: "",
  audience: "",
  platform_tone: "",
  notes: "",
};

function fmt(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

const MULTILINE = new Set<FieldKey>(["event_summary", "key_points", "background", "notes"]);

export function ContextTab(props: MaterialTabProps) {
  const { type, instance, refreshKey, onChanged } = props;
  const [ctx, setCtx] = useState<SourceContext | null>(null);
  const [seed, setSeed] = useState<SourceBasicInfo>(EMPTY_SEED);
  const [showSeed, setShowSeed] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const fillJob = useJob();

  const loadContext = useCallback(async () => {
    try {
      const c = await rpc.readContext(type, instance);
      setCtx(c);
    } catch (err) {
      setError(fmt(err));
    }
  }, [type, instance]);

  useEffect(() => {
    void loadContext();
  }, [loadContext, refreshKey]);

  // Load the basic_info seed once (it drives AI fill).
  useEffect(() => {
    let alive = true;
    void rpc
      .readBasicInfo(type, instance)
      .then((b) => alive && setSeed(b))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [type, instance, refreshKey]);

  // Persist a seed field, then run AI fill (replacement semantics).
  const commitSeed = useCallback(
    async (key: keyof SourceBasicInfo, value: string) => {
      if (seed[key] === value) return;
      const next = { ...seed, [key]: value };
      setSeed(next);
      try {
        await rpc.writeBasicInfo(type, instance, next);
      } catch (err) {
        setError(fmt(err));
      }
    },
    [seed, type, instance],
  );

  const runFill = useCallback(async () => {
    const res = await fillJob.run<SourceContext>(() => rpc.startAiFillContext(type, instance));
    if (res !== undefined) {
      await loadContext();
      onChanged();
    }
  }, [fillJob, type, instance, loadContext, onChanged]);

  // Commit one field → write the whole dict (server is the single owner /
  // normalizer) → adopt the stored result. Faithful to write_context semantics.
  const commit = useCallback(
    async (key: FieldKey, value: string) => {
      if (!ctx || ctx[key] === value) return;
      const next = { ...ctx, [key]: value };
      setCtx(next); // optimistic
      setSaving(true);
      setError("");
      try {
        const stored = await rpc.writeContext(type, instance, next);
        setCtx(stored);
        onChanged();
      } catch (err) {
        setError(fmt(err));
      } finally {
        setSaving(false);
      }
    },
    [ctx, type, instance, onChanged],
  );

  if (!ctx) {
    return <div style={{ color: "#666", fontSize: 13 }}>{error ? `✗ ${error}` : "加载中…"}</div>;
  }

  const total = Object.keys(EMPTY).length;
  const filled = (Object.keys(EMPTY) as FieldKey[]).filter((k) => (ctx[k] ?? "").trim()).length;

  return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: "#999" }}>
          新闻背景 · 已填 {filled}/{total} 字段
        </span>
        {saving && <span style={{ fontSize: 11, color: "#4a9eff" }}>保存中…</span>}
        {error && <span style={{ fontSize: 11, color: "#ff6b6b" }}>✗ {error}</span>}
      </div>

      {/* AI fill: 5-field seed → AI web-search → replaces the whole context */}
      <div style={{ padding: "10px 12px", background: "#1c1c20", borderRadius: 6, border: "1px solid #2a2a2e", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button onClick={() => void runFill()} disabled={fillJob.running} style={{ padding: "6px 14px", background: "#7a4fd6", color: "#fff", border: "none", borderRadius: 5, fontSize: 13, cursor: "pointer" }}>
            ✨ AI 填充
          </button>
          <button onClick={() => setShowSeed((s) => !s)} style={{ padding: "5px 10px", background: "transparent", color: "#9aa", border: "none", fontSize: 12, cursor: "pointer" }}>
            {showSeed ? "收起线索" : "编辑线索（5 项）"}
          </button>
          {fillJob.running && (
            <span style={{ fontSize: 12, color: "#4a9eff" }}>
              AI 提取中…
              <button onClick={fillJob.cancel} style={{ marginLeft: 8, padding: "2px 8px", background: "#2a2a2e", color: "#ddd", border: "none", borderRadius: 4, fontSize: 11, cursor: "pointer" }}>
                取消
              </button>
            </span>
          )}
          {fillJob.error && <span style={{ fontSize: 11, color: "#ff6b6b" }}>✗ {fillJob.error}</span>}
        </div>
        <p style={{ color: "#d9a441", fontSize: 11, margin: "6px 0 0" }}>
          ⚠ AI 填充会用联网检索结果整体覆盖现有新闻背景。
        </p>
        {showSeed && (
          <div style={{ marginTop: 8 }}>
            <p style={{ color: "#888", fontSize: 11, margin: "0 0 4px" }}>
              线索只是 AI 的输入提示（可不准），下游不读取。
            </p>
            {SEED_FIELDS.map((f) => (
              <TextRow
                key={f.key}
                label={f.label}
                value={seed[f.key] ?? ""}
                disabled={fillJob.running}
                labelWidth={96}
                inputMaxWidth={360}
                onCommit={(v) => void commitSeed(f.key, v)}
              />
            ))}
          </div>
        )}
      </div>

      {GROUPS.map((g) => (
        <div key={g.title}>
          <Section title={g.title} />
          {g.fields.map((f) =>
            MULTILINE.has(f.key) ? (
              <TextAreaRow
                key={f.key}
                label={f.label}
                value={ctx[f.key] ?? ""}
                disabled={saving}
                rows={f.rows ?? 3}
                labelWidth={96}
                onCommit={(v) => void commit(f.key, v)}
              />
            ) : (
              <TextRow
                key={f.key}
                label={f.label}
                value={ctx[f.key] ?? ""}
                disabled={saving}
                labelWidth={96}
                inputMaxWidth={360}
                onCommit={(v) => void commit(f.key, v)}
              />
            ),
          )}
        </div>
      ))}
    </div>
  );
}
