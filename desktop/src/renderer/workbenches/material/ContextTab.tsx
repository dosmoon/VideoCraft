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
import { tr } from "../../i18n/tr";
import { Section, TextRow, TextAreaRow } from "../shared/fields";
import type { MaterialTabProps } from "./SourceTab";

// The 5 basic_info hint fields (AI-fill seed). Input-only; AI replaces context.
function getSeedFields(): { key: keyof SourceBasicInfo; label: string }[] {
  return [
    { key: "host", label: tr("material.context.field.host") },
    { key: "host_bio", label: tr("material.context.field.host_bio") },
    { key: "event_date", label: tr("material.context.field.event_date") },
    { key: "event_location", label: tr("material.context.field.event_location") },
    { key: "episode_topic", label: tr("material.context.field.episode_topic") },
  ];
}

const EMPTY_SEED: SourceBasicInfo = {
  host: "",
  host_bio: "",
  event_date: "",
  event_location: "",
  episode_topic: "",
};

// Ordered field layout (grouped). `multiline` fields use a textarea.
type FieldKey = keyof SourceContext;
function getGroups(): { title: string; fields: { key: FieldKey; label: string; rows?: number }[] }[] {
  return [
    {
      title: tr("material.context.group.anchors"),
      fields: [
        { key: "host", label: tr("material.context.field.host") },
        { key: "host_bio", label: tr("material.context.field.host_bio") },
        { key: "event_date", label: tr("material.context.field.event_date") },
        { key: "event_location", label: tr("material.context.field.event_location") },
        { key: "episode_topic", label: tr("material.context.field.episode_topic") },
      ],
    },
    {
      title: tr("material.context.group.people"),
      fields: [
        { key: "host_affiliation", label: tr("material.context.field.host_affiliation") },
        { key: "guests", label: tr("material.context.field.guests") },
      ],
    },
    { title: tr("material.context.group.time"), fields: [{ key: "event_time", label: tr("material.context.field.event_time") }] },
    {
      title: tr("material.context.group.event"),
      fields: [
        { key: "show_type", label: tr("material.context.field.show_type") },
        { key: "event_summary", label: tr("material.context.field.event_summary"), rows: 3 },
        { key: "key_points", label: tr("material.context.field.key_points"), rows: 4 },
      ],
    },
    { title: tr("material.context.group.background"), fields: [{ key: "background", label: tr("material.context.field.background"), rows: 5 }] },
    {
      title: tr("material.context.group.production"),
      fields: [
        { key: "audience", label: tr("material.context.field.audience") },
        { key: "platform_tone", label: tr("material.context.field.platform_tone") },
        { key: "notes", label: tr("material.context.field.notes"), rows: 3 },
      ],
    },
  ];
}

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
      // news_video runs the generic capability.llm_extract, which returns the raw
      // 15-field dict but does NOT write context.json (the plugin owns that), so
      // persist it here (replacement semantics). The Python path already wrote it.
      if (type === "news_video") {
        try {
          await rpc.writeContext(type, instance, res);
        } catch (err) {
          setError(fmt(err));
        }
      }
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

  const seedFields = getSeedFields();
  const groups = getGroups();

  if (!ctx) {
    return <div style={{ color: "#666", fontSize: 13 }}>{error ? `✗ ${error}` : tr("common.loading")}</div>;
  }

  const total = Object.keys(EMPTY).length;
  const filled = (Object.keys(EMPTY) as FieldKey[]).filter((k) => (ctx[k] ?? "").trim()).length;

  return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: "#999" }}>
          {tr("material.context.filled_count", { filled, total })}
        </span>
        {saving && <span style={{ fontSize: 11, color: "#4a9eff" }}>{tr("material.context.saving")}</span>}
        {error && <span style={{ fontSize: 11, color: "#ff6b6b" }}>✗ {error}</span>}
      </div>

      {/* How this page works */}
      <p style={{ color: "#9aa", fontSize: 12, margin: "0 0 12px", lineHeight: 1.6 }}>
        {tr("material.context.usage_hint")}
      </p>

      {/* Step ① — user hints (input to AI; never read downstream) */}
      <StepCard step={tr("material.context.step1_label")} subtitle={tr("material.context.step1_subtitle")}>
        <p style={{ color: "#888", fontSize: 11, margin: "0 0 6px" }}>
          {tr("material.context.step1_desc")}
        </p>
        {seedFields.map((f) => (
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
      </StepCard>

      {/* Step ② — AI fill (replacement) */}
      <StepCard step={tr("material.context.step2_label")} subtitle={tr("material.context.step2_subtitle")}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            onClick={() => void runFill()}
            disabled={fillJob.running}
            style={{ padding: "6px 14px", background: "#7a4fd6", color: "#fff", border: "none", borderRadius: 5, fontSize: 13, cursor: "pointer" }}
          >
            ✨ {tr("material.context.ai_fill_btn")}
          </button>
          {fillJob.running && (
            <span style={{ fontSize: 12, color: "#4a9eff" }}>
              {tr("material.context.ai_running")}
              <button onClick={fillJob.cancel} style={{ marginLeft: 8, padding: "2px 8px", background: "#2a2a2e", color: "#ddd", border: "none", borderRadius: 4, fontSize: 11, cursor: "pointer" }}>
                {tr("common.cancel")}
              </button>
            </span>
          )}
          {fillJob.error && <span style={{ fontSize: 11, color: "#ff6b6b" }}>✗ {fillJob.error}</span>}
        </div>
        <p style={{ color: "#d9a441", fontSize: 11, margin: "6px 0 0" }}>
          ⚠ {tr("material.context.step2_warn")}
        </p>
      </StepCard>

      {/* Step ③ — AI-generated background (the downstream source of truth; editable) */}
      <div style={{ fontSize: 12, color: "#cdd", fontWeight: 700, margin: "16px 0 2px" }}>
        {tr("material.context.step3_heading")}
      </div>
      {filled === 0 && (
        <p style={{ color: "#888", fontSize: 11, margin: "0 0 6px" }}>
          {tr("material.context.step3_empty_hint")}
        </p>
      )}

      {groups.map((g) => (
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

// A bordered "step" card with a numbered heading + subtitle.
function StepCard(props: { step: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: "10px 12px", background: "#1c1c20", borderRadius: 6, border: "1px solid #2a2a2e", marginBottom: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#cdd" }}>{props.step}</span>
        <span style={{ fontSize: 11, color: "#888" }}>{props.subtitle}</span>
      </div>
      {props.children}
    </div>
  );
}
