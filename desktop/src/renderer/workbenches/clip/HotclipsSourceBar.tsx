/**
 * HotclipsSourceBar — the clip workbench's "candidate source" selector, shown
 * right under the shared MaterialBindingBar (mirrors the news_desk Style tab's
 * "chapter source" import row).
 *
 * A material can hold hotclips in several languages (`<lang>.hotclips.json`);
 * which one this clip instance cuts from is a HUMAN decision — never inferred
 * (translated subtitles exist precisely to cut clips in another language).
 * Switching is an explicit action and clears the per-candidate state
 * (selections + overrides are keyed by candidate index and would mis-apply to
 * the other language's list), so a non-empty instance asks for confirmation
 * inline first (a two-button bar within this row, not a modal).
 */

import { useState } from "react";
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
const CONFIRM_BTN: React.CSSProperties = {
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

export function HotclipsSourceBar(props: {
  type: string;
  instance: string;
  /** Currently locked candidate language ("" when not yet decided). */
  lang: string;
  /** Hotclips languages available (upstream + instance snapshots). */
  availableLangs: string[];
  /** True when the instance has selections/overrides that a switch would clear. */
  hasCandidateState: boolean;
  /** Full-reload trigger (the workbench's shared refresh key bump). */
  onChanged: () => void;
}) {
  const { type, instance, lang, availableLangs, hasCandidateState, onChanged } = props;
  const [pending, setPending] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const apply = async (next: string) => {
    setBusy(true);
    setErr("");
    try {
      await rpc.updateConfig(type, instance, {
        source_subtitle: next,
        selected_clip_indices: [],
        clips_overrides_clear: true,
      });
      setPending(null);
      onChanged();
    } catch (e) {
      setErr(e instanceof RpcError ? `[${e.code}] ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onPick = (next: string) => {
    if (!next || next === lang) return;
    // First-time pick (nothing locked yet) or an empty instance: no state to
    // lose — apply at once. Otherwise ask inline before clearing.
    if (!lang || !hasCandidateState) void apply(next);
    else setPending(next);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 16px 0", flexWrap: "wrap" }}>
      <span style={{ fontSize: 12, color: "#888" }}>{tr("clip.source.label")}</span>
      {availableLangs.length === 0 ? (
        <span style={{ fontSize: 12, color: "#777" }}>{tr("clip.source.none")}</span>
      ) : (
        <select
          value={pending ?? lang}
          onChange={(e) => onPick(e.target.value)}
          disabled={busy}
          style={SEL}
        >
          {!lang && <option value="">{tr("clip.source.placeholder")}</option>}
          {availableLangs.map((l) => (
            <option key={l} value={l}>
              {l}.hotclips.json
            </option>
          ))}
        </select>
      )}
      {pending && (
        <>
          <span style={{ fontSize: 12, color: "#c87" }}>{tr("clip.source.switch_hint")}</span>
          <button onClick={() => void apply(pending)} disabled={busy} style={{ ...CONFIRM_BTN, opacity: busy ? 0.6 : 1 }}>
            {tr("clip.source.switch_confirm")}
          </button>
          <button onClick={() => setPending(null)} disabled={busy} style={PLAIN_BTN}>
            {tr("common.cancel")}
          </button>
        </>
      )}
      {err && <span style={{ color: "#ff6b6b", fontSize: 12 }}>✗ {err}</span>}
    </div>
  );
}
