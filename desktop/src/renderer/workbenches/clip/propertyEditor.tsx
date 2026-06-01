/**
 * PropertyPanel — type-driven editor for a component's style fields. Picks a
 * control by the field's runtime value type (boolean→checkbox, number→numeric,
 * string→text with a #RRGGBB swatch). Text/number inputs commit on blur/Enter
 * (not per keystroke) so editing doesn't fire an RPC write per character.
 *
 * Moved verbatim out of Hub when the clip workbench became a per-plugin module;
 * still generic — hoist to a shared dir if a second workbench needs it.
 */

import { tr } from "../../i18n/tr";
import type { Component } from "../../ipc/client";
import { INPUT_STYLE, NumberInput, TextInput } from "../shared/fieldControls";

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
