/**
 * AiConsole — the framework AI settings surface, ported from the Tk AI Console
 * (tools/router/ai_console.py) onto the ai.* RPC domain. Six tabs:
 *   Routing · Embedded · Cloud · aistack · TTS · Stats
 * (the Tk console's Prompts/Playground are deliberately NOT here — the prompt hub
 * was retired.) All state comes from ai.snapshot; every edit calls a write RPC
 * that returns a fresh snapshot, so the whole console re-syncs from one source.
 *
 * Deferred (P1-b2, needs jobs — network I/O must not block the dispatch thread):
 * per-provider "Test connection" and the aistack "Test & Refresh models" action
 * (so the aistack routing model lists stay empty until that lands).
 */

import { useCallback, useEffect, useState } from "react";
import {
  rpc,
  RpcError,
  type AiSnapshot,
  type AiProvider,
  type AiCategory,
  type AiKeyStatus,
  type AiStatsEntry,
} from "../ipc/client";
import { tr } from "../i18n/tr";

type TabId = "routing" | "embedded" | "cloud" | "aistack" | "tts" | "stats";
const TABS: { id: TabId; key: string }[] = [
  { id: "routing", key: "ai.tab.routing" },
  { id: "embedded", key: "ai.tab.embedded" },
  { id: "cloud", key: "ai.tab.cloud" },
  { id: "aistack", key: "ai.tab.aistack" },
  { id: "tts", key: "ai.tab.tts" },
  { id: "stats", key: "ai.tab.stats" },
];

// ── shared styles ─────────────────────────────────────────────────────────────
const INPUT: React.CSSProperties = {
  background: "#1a1a1e",
  color: "#ddd",
  border: "1px solid #333",
  borderRadius: 3,
  fontSize: 12,
  padding: "3px 6px",
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
const CARD: React.CSSProperties = {
  border: "1px solid #2a2a2e",
  borderRadius: 6,
  padding: "10px 12px",
  marginBottom: 10,
};

function fmtErr(err: unknown): string {
  if (err instanceof RpcError) return `[${err.code}] ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

function keyStatusText(ks: AiKeyStatus): string {
  switch (ks.state) {
    case "ok":
      return ks.masked ?? "✓";
    case "cli":
      return tr("ai.key.cli");
    case "no_key_needed":
      return tr("ai.key.no_key_needed");
    case "empty":
      return tr("ai.key.empty");
    default:
      return tr("ai.key.not_configured");
  }
}
function keyStatusColor(state: AiKeyStatus["state"]): string {
  if (state === "ok" || state === "cli") return "#7fd17f";
  if (state === "no_key_needed") return "#888";
  return "#d98b8b";
}

// ── routing helpers (mirror the Tk tier model) ────────────────────────────────
function deployTierMap(snap: AiSnapshot): Record<string, string> {
  const m: Record<string, string> = {};
  (["llm", "asr", "tts"] as const).forEach((cat) =>
    snap.providers[cat].forEach((p) => (m[p.name] = p.deploy_tier)),
  );
  return m;
}
// Which routing tier (embedded/cloud/aistack/auto) an active cell belongs to.
function routingTierOf(provider: string, dtMap: Record<string, string>): string {
  if (!provider) return "auto";
  const dt = dtMap[provider];
  if (dt === "cloud") return "cloud";
  if (dt === "aistack") return "aistack";
  return "embedded"; // local | free_online
}
function providersForTier(snap: AiSnapshot, tier: string, category: AiCategory): string[] {
  if (tier === "aistack") return ["aistack"];
  const list = snap.providers[category];
  if (tier === "embedded")
    return list.filter((p) => p.deploy_tier === "local" || p.deploy_tier === "free_online").map((p) => p.name);
  if (tier === "cloud") return list.filter((p) => p.deploy_tier === "cloud").map((p) => p.name);
  return [];
}
function modelsForTier(snap: AiSnapshot, tier: string, category: AiCategory, provider: string): string[] {
  if (tier === "aistack") return snap.aistack.models_cache[category] ?? [];
  return snap.providers[category].find((p) => p.name === provider)?.models ?? [];
}

// ── component ─────────────────────────────────────────────────────────────────
export function AiConsole() {
  const [snap, setSnap] = useState<AiSnapshot | null>(null);
  const [tab, setTab] = useState<TabId>("routing");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    rpc
      .aiSnapshot()
      .then(setSnap)
      .catch((e) => setError(fmtErr(e)));
  }, []);
  useEffect(load, [load]);

  // Wrap a write so failures surface and the returned snapshot re-syncs.
  const apply = useCallback(async (p: Promise<AiSnapshot>) => {
    try {
      setSnap(await p);
    } catch (e) {
      setError(fmtErr(e));
    }
  }, []);

  return (
    <div style={{ padding: "16px 20px", maxWidth: 900 }}>
      <h2 style={{ fontWeight: 600, margin: "0 0 12px" }}>{tr("ai.title")}</h2>
      {error && <p style={{ color: "#ff6b6b" }}>✗ {error}</p>}

      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #2a2a2e", marginBottom: 14 }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: "6px 12px",
              border: "none",
              borderBottom: tab === t.id ? "2px solid #2d6cdf" : "2px solid transparent",
              background: "transparent",
              color: tab === t.id ? "#fff" : "#999",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            {tr(t.key)}
          </button>
        ))}
      </div>

      {!snap ? (
        <p style={{ color: "#888" }}>{tr("common.loading")}</p>
      ) : tab === "routing" ? (
        <RoutingTab snap={snap} apply={apply} />
      ) : tab === "embedded" ? (
        <ProvidersTab snap={snap} tiers={["local", "free_online"]} apply={apply} />
      ) : tab === "cloud" ? (
        <ProvidersTab snap={snap} tiers={["cloud"]} apply={apply} />
      ) : tab === "aistack" ? (
        <AistackTab snap={snap} apply={apply} />
      ) : tab === "tts" ? (
        <TtsTab snap={snap} apply={apply} />
      ) : (
        <StatsTab />
      )}
    </div>
  );
}

type ApplyFn = (p: Promise<AiSnapshot>) => void;

// ── Routing tab ───────────────────────────────────────────────────────────────
function RoutingTab({ snap, apply }: { snap: AiSnapshot; apply: ApplyFn }) {
  const dtMap = deployTierMap(snap);
  return (
    <div>
      <p style={{ color: "#888", fontSize: 12, margin: "0 0 10px" }}>{tr("ai.routing.hint")}</p>
      {snap.tasks.map((task) => {
        const active = snap.task_routing[task.id] ?? { provider: "", model: "" };
        const activeTier = routingTierOf(active.provider, dtMap);
        const tiers = task.category === "llm" ? snap.routing_tiers.llm : snap.routing_tiers.non_llm;
        return (
          <div key={task.id} style={CARD}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
              <span style={{ color: "#6a9", fontSize: 11, marginRight: 6 }}>
                {tr(`ai.category.${task.category}`)}
              </span>
              {task.label}
            </div>
            {tiers.map((tier) => (
              <TierRow
                key={tier}
                snap={snap}
                task={task.id}
                category={task.category}
                tier={tier}
                isActive={activeTier === tier}
                apply={apply}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

function TierRow(props: {
  snap: AiSnapshot;
  task: string;
  category: AiCategory;
  tier: string;
  isActive: boolean;
  apply: ApplyFn;
}) {
  const { snap, task, category, tier, isActive, apply } = props;
  const provOptions = providersForTier(snap, tier, category);
  // The cell's current pick: stored per-tier pref, else a sensible default.
  const pref = snap.task_tier_prefs[task]?.[tier];
  const provider = pref?.provider ?? provOptions[0] ?? "";
  const modelOptions = modelsForTier(snap, tier, category, provider);
  const model = pref?.model ?? modelOptions[0] ?? "";

  const pickTier = () => apply(rpc.aiSetRouting(task, provider, model));
  const changeProvider = (prov: string) => {
    const m = modelsForTier(snap, tier, category, prov)[0] ?? "";
    apply(rpc.aiSetTierPref(task, tier, prov, m));
    if (isActive) apply(rpc.aiSetRouting(task, prov, m));
  };
  const changeModel = (m: string) => {
    apply(rpc.aiSetTierPref(task, tier, provider, m));
    if (isActive) apply(rpc.aiSetRouting(task, provider, m));
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 0" }}>
      <input type="radio" checked={isActive} onChange={pickTier} />
      <span style={{ width: 80, fontSize: 12, color: "#bbb" }}>{tr(`ai.tier.${tier}`)}</span>
      {tier === "auto" ? (
        <span style={{ color: "#777", fontSize: 12, fontStyle: "italic" }}>{tr("ai.tier.auto_hint")}</span>
      ) : (
        <>
          {provOptions.length > 1 ? (
            <select value={provider} onChange={(e) => changeProvider(e.target.value)} style={INPUT}>
              {provOptions.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          ) : (
            <span style={{ fontSize: 12, color: "#ccc", width: 110 }}>{provider || "—"}</span>
          )}
          {modelOptions.length > 0 ? (
            <select value={model} onChange={(e) => changeModel(e.target.value)} style={INPUT}>
              {modelOptions.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          ) : (
            <span style={{ fontSize: 11, color: "#777" }}>
              {tier === "aistack" ? tr("ai.aistack.no_models") : model || "—"}
            </span>
          )}
        </>
      )}
    </div>
  );
}

// ── Embedded / Cloud tabs (provider rows filtered by deploy tier) ─────────────
function ProvidersTab({
  snap,
  tiers,
  apply,
}: {
  snap: AiSnapshot;
  tiers: string[];
  apply: ApplyFn;
}) {
  // TTS lives in its own tab; here we show only llm + asr rows for these tiers.
  const rows = (["llm", "asr"] as const).flatMap((cat) =>
    snap.providers[cat].filter((p) => tiers.includes(p.deploy_tier)),
  );
  if (rows.length === 0) return <p style={{ color: "#888", fontSize: 12 }}>{tr("ai.providers.empty")}</p>;
  return (
    <div>
      {rows.map((p) => (
        <ProviderRow key={`${p.category}:${p.name}`} provider={p} apply={apply} />
      ))}
    </div>
  );
}

function ProviderRow({ provider: p, apply }: { provider: AiProvider; apply: ApplyFn }) {
  const [keyVal, setKeyVal] = useState("");
  const [editing, setEditing] = useState(false);
  const saveKey = () => {
    apply(rpc.aiSetKey(p.name, p.category, keyVal));
    setKeyVal("");
    setEditing(false);
  };
  return (
    <div style={CARD}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{p.name}</span>
        <span style={{ fontSize: 11, color: "#6a9" }}>{tr(`ai.category.${p.category}`)}</span>
        {p.models.length > 0 && (
          <span style={{ fontSize: 11, color: "#777" }}>
            {tr("ai.providers.model_count", { n: p.models.length })}
          </span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 12, color: keyStatusColor(p.key_status.state) }}>
          {keyStatusText(p.key_status)}
        </span>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#ccc" }}>
          <input
            type="checkbox"
            checked={p.enabled}
            onChange={(e) => apply(rpc.aiSetProviderEnabled(p.name, p.category, e.target.checked))}
          />
          {tr("ai.providers.enabled")}
        </label>
      </div>
      {p.needs_key && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8 }}>
          {editing ? (
            <>
              <input
                type="password"
                value={keyVal}
                onChange={(e) => setKeyVal(e.target.value)}
                placeholder={tr("ai.providers.key_placeholder")}
                style={{ ...INPUT, flex: 1 }}
                autoFocus
              />
              <button onClick={saveKey} disabled={!keyVal} style={BTN}>
                {tr("common.save")}
              </button>
              <button onClick={() => setEditing(false)} style={BTN}>
                {tr("common.cancel")}
              </button>
            </>
          ) : (
            <button onClick={() => setEditing(true)} style={BTN}>
              {p.key_status.state === "ok" ? tr("ai.providers.change_key") : tr("ai.providers.set_key")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── aistack tab ───────────────────────────────────────────────────────────────
function AistackTab({ snap, apply }: { snap: AiSnapshot; apply: ApplyFn }) {
  const [url, setUrl] = useState(snap.aistack.base_url);
  useEffect(() => setUrl(snap.aistack.base_url), [snap.aistack.base_url]);
  return (
    <div style={CARD}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>{tr("ai.aistack.title")}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: "#bbb", width: 40 }}>{tr("ai.aistack.url")}</span>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onBlur={() => url !== snap.aistack.base_url && apply(rpc.aiSetAistackGateway(url, snap.aistack.enabled))}
          style={{ ...INPUT, flex: 1 }}
        />
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#ccc" }}>
        <input
          type="checkbox"
          checked={snap.aistack.enabled}
          onChange={(e) => apply(rpc.aiSetAistackGateway(snap.aistack.base_url, e.target.checked))}
        />
        {tr("ai.aistack.enable")}
      </label>
      <p style={{ fontSize: 11, color: "#777", marginTop: 8 }}>{tr("ai.aistack.test_deferred")}</p>
    </div>
  );
}

// ── TTS tab ───────────────────────────────────────────────────────────────────
function TtsTab({ snap, apply }: { snap: AiSnapshot; apply: ApplyFn }) {
  if (snap.providers.tts.length === 0)
    return <p style={{ color: "#888", fontSize: 12 }}>{tr("ai.providers.empty")}</p>;
  return (
    <div>
      {snap.providers.tts.map((p) => (
        <ProviderRow key={p.name} provider={p} apply={apply} />
      ))}
      <p style={{ fontSize: 11, color: "#777" }}>{tr("ai.tts.picker_note")}</p>
    </div>
  );
}

// ── Stats tab ─────────────────────────────────────────────────────────────────
function StatsTab() {
  const [stats, setStats] = useState<Record<string, AiStatsEntry> | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    rpc
      .aiStats()
      .then(setStats)
      .catch((e) => setError(fmtErr(e)));
  }, []);
  useEffect(load, [load]);

  const rows = Object.entries(stats ?? {});
  return (
    <div>
      <button onClick={load} style={{ ...BTN, marginBottom: 10 }}>
        {tr("ai.stats.refresh")}
      </button>
      {error && <p style={{ color: "#ff6b6b" }}>✗ {error}</p>}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ color: "#888", textAlign: "left" }}>
            <th style={{ padding: "4px 8px" }}>{tr("ai.stats.col_provider")}</th>
            <th style={{ padding: "4px 8px" }}>{tr("ai.stats.col_calls")}</th>
            <th style={{ padding: "4px 8px" }}>{tr("ai.stats.col_errors")}</th>
            <th style={{ padding: "4px 8px" }}>{tr("ai.stats.col_error_rate")}</th>
            <th style={{ padding: "4px 8px" }}>{tr("ai.stats.col_last_used")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, s]) => {
            const rate = s.calls > 0 ? `${Math.round((s.errors / s.calls) * 100)}%` : "—";
            return (
              <tr key={name} style={{ borderTop: "1px solid #2a2a2e", color: "#ccc" }}>
                <td style={{ padding: "4px 8px" }}>{name}</td>
                <td style={{ padding: "4px 8px" }}>{s.calls}</td>
                <td style={{ padding: "4px 8px" }}>{s.errors}</td>
                <td style={{ padding: "4px 8px" }}>{rate}</td>
                <td style={{ padding: "4px 8px" }}>{s.last_used ?? tr("ai.stats.never")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
