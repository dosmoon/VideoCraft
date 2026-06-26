/**
 * voicePicker.tsx — imperative TTS voice picker for the dubbing flow.
 *
 * Same host/promise shape as confirm.tsx: a single <VoicePickerHost /> mounted
 * at the shell root renders the modal whenever pickVoice() is awaiting. The
 * caller (the subtitle "+" → 合成音频 action) does:
 *
 *     const pick = await pickVoice({ langHint: "zh" });
 *     if (!pick) return;                       // cancelled
 *     job.run(() => rpc.startTtsDub(..., pick.provider, pick.voiceId, pick.options));
 *
 * Voice selection lives here (renderer), not in the AI Console — engine + voice
 * are chosen per use, not routed (see the TTS abstraction layer). Providers come
 * from the AI snapshot; the catalog from ai.tts_voices.
 */

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { rpc, type TtsVoice } from "../ipc/client";
import { tr } from "../i18n/tr";
import { color, radius, font, space } from "./tokens";

export interface VoicePick {
  provider: string;
  voiceId: string;
  options: { max_speed: number };
}

type VoiceRequest = {
  langHint: string;
  resolve: (pick: VoicePick | null) => void;
};

// Readable provider labels (proper nouns — not localized; fall back to the id).
const PROVIDER_LABELS: Record<string, string> = {
  edge_tts: "Edge TTS",
  aistack: "aistack",
  fish_audio: "Fish Audio",
};

let current: VoiceRequest | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const cb of listeners) cb();
}

/**
 * Open the voice picker and resolve the chosen {provider, voiceId, options}, or
 * null when cancelled. `langHint` (the subtitle ISO, e.g. "zh") pre-filters the
 * list to matching voices. Requires <VoicePickerHost /> mounted near the root.
 */
export function pickVoice(opts?: { langHint?: string }): Promise<VoicePick | null> {
  return new Promise<VoicePick | null>((resolve) => {
    if (current) current.resolve(null);
    current = { langHint: opts?.langHint ?? "", resolve };
    emit();
  });
}

function settle(pick: VoicePick | null): void {
  const req = current;
  current = null;
  emit();
  req?.resolve(pick);
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function VoicePickerHost(): React.ReactElement | null {
  const req = useSyncExternalStore(subscribe, () => current);
  if (!req) return null;
  // Re-mount the modal per request so its internal form state resets cleanly.
  return <VoicePickerModal req={req} />;
}

function VoicePickerModal({ req }: { req: VoiceRequest }): React.ReactElement {
  const [providers, setProviders] = useState<string[]>([]);
  const [provider, setProvider] = useState("");
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasCache, setHasCache] = useState(true);
  const [query, setQuery] = useState(req.langHint);
  const [voiceId, setVoiceId] = useState("");
  const [maxSpeed, setMaxSpeed] = useState(1.5);
  const [err, setErr] = useState("");

  // Load the enabled TTS providers once; default to edge_tts when present.
  useEffect(() => {
    let alive = true;
    void rpc
      .aiSnapshot()
      .then((snap) => {
        if (!alive) return;
        const names = snap.providers.tts.map((p) => p.name);
        setProviders(names);
        setProvider(names.includes("edge_tts") ? "edge_tts" : (names[0] ?? ""));
      })
      .catch((e) => alive && setErr(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  // (Re)load the catalog whenever the provider changes.
  const loadVoices = (prov: string, refresh: boolean) => {
    if (!prov) return;
    setLoading(true);
    setErr("");
    void rpc
      .ttsVoices(prov, refresh)
      .then((res) => {
        setVoices(res.voices);
        setHasCache(res.meta.has_cache || res.voices.length > 0);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    if (provider) loadVoices(provider, false);
    setVoiceId("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return voices;
    return voices.filter((v) =>
      [v.display_name, v.voice_id, v.language, v.gender, ...v.tags]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [voices, query]);

  const canConfirm = !!provider && !!voiceId.trim();

  return (
    <div
      onClick={() => settle(null)}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        style={{
          background: color.bgRaised,
          border: `1px solid ${color.border}`,
          borderRadius: radius.md,
          padding: 20,
          width: 460,
          maxWidth: "90vw",
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
          display: "flex",
          flexDirection: "column",
          gap: space.md,
        }}
      >
        <div style={{ color: color.textPrimary, fontSize: font.lg, fontWeight: 600 }}>
          {tr("material.dub.picker_title")}
        </div>

        {/* Provider */}
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: font.xs, color: color.textSecondary }}>
            {tr("material.dub.engine_label")}
          </span>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            style={inputStyle}
          >
            {providers.length === 0 && <option value="">—</option>}
            {providers.map((p) => (
              <option key={p} value={p}>
                {PROVIDER_LABELS[p] ?? p}
              </option>
            ))}
          </select>
        </label>

        {/* Voice search + list */}
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: font.xs, color: color.textSecondary }}>
            {tr("material.dub.voice_label")}
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={tr("material.dub.voice_search_placeholder")}
            style={inputStyle}
          />
        </label>
        <div
          style={{
            border: `1px solid ${color.border}`,
            borderRadius: radius.sm,
            height: 200,
            overflowY: "auto",
            background: color.bgInset,
          }}
        >
          {loading ? (
            <div style={listNote}>{tr("material.dub.loading")}</div>
          ) : filtered.length === 0 ? (
            <div style={listNote}>
              {hasCache ? tr("material.dub.no_match") : tr("material.dub.no_cache")}
              {"  "}
              <button onClick={() => loadVoices(provider, true)} style={linkBtn}>
                {tr("material.dub.refresh")}
              </button>
            </div>
          ) : (
            filtered.map((v) => {
              const sel = v.voice_id === voiceId;
              return (
                <button
                  key={v.voice_id}
                  onClick={() => setVoiceId(v.voice_id)}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-start",
                    gap: 2,
                    width: "100%",
                    textAlign: "left",
                    padding: "6px 10px",
                    background: sel ? color.accent : "transparent",
                    color: sel ? "#fff" : color.textPrimary,
                    border: "none",
                    cursor: "pointer",
                    fontSize: font.sm,
                  }}
                >
                  <span>
                    {v.display_name || v.voice_id}
                    {v.gender ? `  · ${v.gender}` : ""}
                  </span>
                  <span style={{ fontSize: font.xs, opacity: 0.8 }}>
                    {[v.language, ...v.tags].filter(Boolean).join(" · ")}
                  </span>
                </button>
              );
            })
          )}
        </div>

        {/* Manual voice id (edge accepts any short-name) + advanced max speed */}
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: font.xs, color: color.textSecondary }}>
            {tr("material.dub.voice_id_label")}
          </span>
          <input
            value={voiceId}
            onChange={(e) => setVoiceId(e.target.value)}
            placeholder={tr("material.dub.voice_id_placeholder")}
            style={inputStyle}
          />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: font.xs, color: color.textSecondary }}>
            {tr("material.dub.max_speed_label")}
          </span>
          <input
            type="number"
            min={1}
            max={3}
            step={0.1}
            value={maxSpeed}
            onChange={(e) => setMaxSpeed(Math.max(1, Number(e.target.value) || 1.5))}
            style={{ ...inputStyle, width: 80 }}
          />
        </label>

        {err && <div style={{ color: "#e57373", fontSize: font.xs }}>{err}</div>}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: space.lg, marginTop: 4 }}>
          <button onClick={() => settle(null)} style={btnGhost}>
            {tr("common.cancel")}
          </button>
          <button
            disabled={!canConfirm}
            onClick={() =>
              settle({ provider, voiceId: voiceId.trim(), options: { max_speed: maxSpeed } })
            }
            style={{ ...btnPrimary, opacity: canConfirm ? 1 : 0.5, cursor: canConfirm ? "pointer" : "default" }}
          >
            {tr("material.dub.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: color.bgInset,
  color: color.textPrimary,
  border: `1px solid ${color.border}`,
  borderRadius: radius.sm,
  padding: "6px 8px",
  fontSize: font.sm,
  outline: "none",
};

const listNote: React.CSSProperties = {
  padding: 12,
  color: color.textSecondary,
  fontSize: font.sm,
};

const linkBtn: React.CSSProperties = {
  background: "transparent",
  color: color.accent,
  border: "none",
  cursor: "pointer",
  fontSize: font.sm,
  padding: 0,
};

const btnGhost: React.CSSProperties = {
  background: color.bgHover,
  color: color.textPrimary,
  border: `1px solid ${color.border}`,
  borderRadius: radius.sm,
  padding: "6px 16px",
  fontSize: font.md,
  cursor: "pointer",
};

const btnPrimary: React.CSSProperties = {
  background: color.accent,
  color: "#fff",
  border: "none",
  borderRadius: radius.sm,
  padding: "6px 16px",
  fontSize: font.md,
};
