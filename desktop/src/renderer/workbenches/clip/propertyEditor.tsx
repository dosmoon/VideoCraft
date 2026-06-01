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
        <NumberInput value={value} disabled={disabled} onCommit={onCommit} />
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

function NumberInput(props: { value: number; disabled: boolean; onCommit: (v: number) => void }) {
  const { value, disabled, onCommit } = props;
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  const commit = () => {
    const n = Number(v);
    if (!Number.isNaN(n) && n !== value) onCommit(n);
    else setV(String(value)); // reject NaN / no-op → snap back to current
  };
  return (
    <input
      type="number"
      step="any"
      value={v}
      disabled={disabled}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      style={INPUT_STYLE}
    />
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
