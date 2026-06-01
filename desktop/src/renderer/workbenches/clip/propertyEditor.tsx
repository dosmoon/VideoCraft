/**
 * PropertyPanel — type-driven editor for a component's style fields. Picks a
 * control by the field's runtime value type (boolean→checkbox, number→numeric,
 * string→text with a #RRGGBB swatch). Text/number inputs commit on blur/Enter
 * (not per keystroke) so editing doesn't fire an RPC write per character.
 *
 * Moved verbatim out of Hub when the clip workbench became a per-plugin module;
 * still generic — hoist to a shared dir if a second workbench needs it.
 */

import { useEffect, useState, type CSSProperties } from "react";
import { tr } from "../../i18n/tr";
import type { Component } from "../../ipc/client";

// Structural / separately-handled fields — never shown in the property editor.
const HIDDEN_FIELDS = new Set(["id", "kind", "enabled"]);

export function PropertyPanel(props: {
  component: Component;
  disabled: boolean;
  onCommit: (key: string, value: unknown) => void;
  /** Fields rendered as a dropdown of fixed choices (e.g. subtitle language). */
  enums?: Record<string, readonly string[]>;
  /** Extra field keys to omit (e.g. a field a dedicated editor renders itself). */
  hide?: readonly string[];
}) {
  const { component, disabled, onCommit, enums, hide } = props;
  const hidden = hide ? new Set([...HIDDEN_FIELDS, ...hide]) : HIDDEN_FIELDS;
  // Only primitive fields are editable here; nested values (if any) are skipped.
  const editable = Object.keys(component).filter((k) => {
    if (hidden.has(k)) return false;
    const t = typeof component[k];
    return t === "string" || t === "number" || t === "boolean";
  });
  return (
    <div
      style={{
        padding: "4px 8px 10px 4px",
        display: "grid",
        gridTemplateColumns: "auto 1fr",
        gap: "6px 10px",
        alignItems: "center",
      }}
    >
      {editable.length === 0 && <span style={{ color: "#666", fontSize: 12 }}>{tr("clip.property.no_fields")}</span>}
      {editable.map((k) => (
        <PropertyField
          key={k}
          label={k}
          value={component[k]}
          disabled={disabled}
          {...(enums?.[k] ? { options: enums[k] } : {})}
          onCommit={(v) => onCommit(k, v)}
        />
      ))}
    </div>
  );
}

function PropertyField(props: {
  label: string;
  value: unknown;
  disabled: boolean;
  options?: readonly string[];
  onCommit: (value: unknown) => void;
}) {
  const { label, value, disabled, options, onCommit } = props;
  // Fixed-choice field (e.g. subtitle language) → dropdown. Keep the current
  // value selectable even if it's not in the offered list.
  if (options) {
    const cur = value == null ? "" : String(value);
    const opts = options.includes(cur) ? options : [cur, ...options];
    return (
      <>
        <label style={{ color: "#999", fontSize: 12 }}>{label}</label>
        <select
          value={cur}
          disabled={disabled}
          onChange={(e) => onCommit(e.target.value)}
          style={INPUT_STYLE}
        >
          {opts.map((o) => (
            <option key={o} value={o}>
              {o || tr("clip.property.unset")}
            </option>
          ))}
        </select>
      </>
    );
  }
  return (
    <>
      <label style={{ color: "#999", fontSize: 12 }}>{label}</label>
      {typeof value === "boolean" ? (
        <input
          type="checkbox"
          checked={value}
          disabled={disabled}
          onChange={(e) => onCommit(e.target.checked)}
        />
      ) : typeof value === "number" ? (
        // INTERIM step: an opacity field is a 0-100 integer (step 1); every
        // other numeric field here is a 0-1 fraction (step 0.01). This keys off
        // the field NAME, not its current value — a fraction field at 0 or 1.0
        // must still step by 0.01. The real fix is component-owned field
        // metadata (unit/range/step) driving this; see the engine-owned edit-UI
        // plan (contract.ts ①). Until then this covers the fields in use.
        <NumberInput
          value={value}
          step={/opacity/i.test(label) ? 1 : 0.01}
          disabled={disabled}
          onCommit={onCommit}
        />
      ) : (
        <TextInput value={String(value)} disabled={disabled} onCommit={onCommit} />
      )}
    </>
  );
}

function TextInput(props: { value: string; disabled: boolean; onCommit: (v: string) => void }) {
  const { value, disabled, onCommit } = props;
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const isColor = /^#[0-9a-fA-F]{6}$/.test(v);
  return (
    <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
      <input
        value={v}
        disabled={disabled}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => v !== value && onCommit(v)}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        style={INPUT_STYLE}
      />
      {isColor && (
        <span style={{ width: 14, height: 14, borderRadius: 3, background: v, border: "1px solid #444" }} />
      )}
    </span>
  );
}

function NumberInput(props: { value: number; step: number; disabled: boolean; onCommit: (v: number) => void }) {
  const { value, step, disabled, onCommit } = props;
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  const commit = () => {
    const n = Number(v);
    if (v.trim() !== "" && !Number.isNaN(n) && n !== value) onCommit(n);
    else setV(String(value)); // reject empty / NaN / no-op → snap back to current
  };
  const bump = (dir: 1 | -1) => {
    const cur = Number(v.trim() === "" ? value : v);
    if (Number.isNaN(cur)) return;
    const next = Math.round((cur + dir * step) * 1000) / 1000; // round off float drift
    setV(String(next));
    if (next !== value) onCommit(next);
  };
  // type="text" + inputMode="decimal", NOT type="number": a controlled number
  // input blanks e.target.value mid-decimal (typing "0." yields "" and the
  // keystroke is lost, so fractional fields like image_scale couldn't be typed),
  // and its native spinner stepped by 1 even for fractions (0.25 → 1.25). We
  // render our own ▲▼ steppers instead (keyboard Up/Down work too).
  return (
    <span style={{ display: "flex", alignItems: "stretch", maxWidth: 160 }}>
      <input
        type="text"
        inputMode="decimal"
        value={v}
        disabled={disabled}
        onChange={(e) => setV(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.currentTarget.blur();
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            bump(1);
          } else if (e.key === "ArrowDown") {
            e.preventDefault();
            bump(-1);
          }
        }}
        style={{ ...INPUT_STYLE, maxWidth: undefined, borderRadius: "3px 0 0 3px", flex: 1, minWidth: 0 }}
      />
      <span style={{ display: "flex", flexDirection: "column" }}>
        <StepButton dir={1} disabled={disabled} onBump={bump} />
        <StepButton dir={-1} disabled={disabled} onBump={bump} />
      </span>
    </span>
  );
}

function StepButton(props: { dir: 1 | -1; disabled: boolean; onBump: (dir: 1 | -1) => void }) {
  const { dir, disabled, onBump } = props;
  return (
    <button
      type="button"
      disabled={disabled}
      // Keep focus on the input so a pending typed value isn't committed/lost.
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => onBump(dir)}
      style={{
        width: 18,
        height: 11,
        padding: 0,
        lineHeight: "11px",
        fontSize: 8,
        background: "#2a2a2e",
        color: "#bbb",
        border: "1px solid #333",
        borderLeft: "none",
        borderRadius: dir === 1 ? "0 3px 0 0" : "0 0 3px 0",
        borderTop: dir === 1 ? "1px solid #333" : "none",
        cursor: disabled ? "default" : "pointer",
      }}
    >
      {dir === 1 ? "▲" : "▼"}
    </button>
  );
}

const INPUT_STYLE: CSSProperties = {
  width: "100%",
  maxWidth: 160,
  padding: "2px 6px",
  background: "#1a1a1e",
  color: "#ddd",
  border: "1px solid #333",
  borderRadius: 3,
  fontSize: 12,
};
