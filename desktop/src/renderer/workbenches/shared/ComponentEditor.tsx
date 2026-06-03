/**
 * ComponentEditor — the metadata-driven property panel (contract.ts ① realised).
 * Reads a component's engine-owned FieldSpec[] (composition/components/fieldSpec)
 * and renders one control per field, committing through the same
 * onPatch → creation.update_component path the workbenches already use. One
 * editor serves every plugin: after the wire normalisation, clip + news_desk
 * share one wire shape per component, so one FieldSpec list drives both.
 *
 * Labels are always tr(spec.labelKey) — never the raw internal key.
 */

import { Fragment } from "react";
import { tr } from "../../i18n/tr";
import type { Component } from "../../ipc/client";
import { fieldsForKind, type FieldSpec } from "@composition/components/fieldSpec.js";
import { INPUT_STYLE, ColorInput, NumberInput, TextInput } from "./fieldControls";
import { readValue, fieldPresent, buildPatch } from "./nestedPatch";

export function ComponentEditor(props: {
  component: Component;
  disabled: boolean;
  onPatch: (fields: Record<string, unknown>) => void;
  /** Host-supplied dynamic select options by field key (e.g. subtitle language). */
  enums?: Record<string, readonly string[]>;
}) {
  const { component, disabled, onPatch, enums } = props;
  const specs = (fieldsForKind(component.kind) ?? []).filter((s) => {
    // A flat field is part of the kind's schema — always show it, reading a
    // missing key as the control's empty default (the user edit then writes
    // the key). Pre-normalisation instances may lack a flat key, e.g. an old
    // image watermark with no `image_path`; the row must still appear so the
    // field is reachable instead of silently vanishing. Nested leaves stay
    // presence-gated, since their parent sub-object can be legitimately absent
    // (e.g. an optional chapter mode block).
    if (s.path && !fieldPresent(component, s)) return false;
    if (s.visibleWhen && !s.visibleWhen(component)) return false;
    return true;
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
      {specs.length === 0 && <span style={{ color: "#666", fontSize: 12 }}>{tr("clip.property.no_fields")}</span>}
      {renderRows(specs, component, enums, disabled, onPatch)}
    </div>
  );
}

/** Render the visible fields, emitting a full-width section header when the
 *  section changes (the first visible field carrying a new `section`). */
function renderRows(
  specs: readonly FieldSpec[],
  component: Component,
  enums: Record<string, readonly string[]> | undefined,
  disabled: boolean,
  onPatch: (fields: Record<string, unknown>) => void,
) {
  let lastSection: string | undefined;
  return specs.map((spec) => {
    let header: React.ReactNode = null;
    if (spec.section && spec.section !== lastSection) {
      header = <div style={SECTION_STYLE}>{tr(spec.section)}</div>;
      lastSection = spec.section;
    }
    return (
      <Fragment key={spec.path ? spec.path.join(".") : spec.key}>
        {header}
        <FieldControlRow
          spec={spec}
          value={readValue(component, spec)}
          {...(enums?.[spec.key] ? { options: enums[spec.key] } : {})}
          disabled={disabled}
          onCommit={(v) => onPatch(buildPatch(component, spec, v))}
        />
      </Fragment>
    );
  });
}

function FieldControlRow(props: {
  spec: FieldSpec;
  value: unknown;
  options?: readonly string[];
  disabled: boolean;
  onCommit: (value: unknown) => void;
}) {
  const { spec, value, options: dynOptions, disabled, onCommit } = props;
  const label = <label style={{ color: "#999", fontSize: 12 }}>{tr(spec.labelKey)}</label>;

  switch (spec.control) {
    case "checkbox":
      return (
        <>
          {label}
          <input
            type="checkbox"
            checked={Boolean(value)}
            disabled={disabled}
            onChange={(e) => onCommit(e.target.checked)}
          />
        </>
      );
    case "number": {
      const stored = typeof value === "number" ? value : Number(value) || 0;
      const d = spec.display;
      if (d) {
        const dec = d.decimals ?? (d.step < 1 ? 1 : 0);
        const pow = 10 ** dec;
        const shown = Math.round(stored * d.factor * pow) / pow;
        return (
          <>
            {label}
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <NumberInput value={shown} step={d.step} disabled={disabled} onCommit={(v) => onCommit(v / d.factor)} />
              {d.suffix && <span style={{ color: "#888", fontSize: 12 }}>{d.suffix}</span>}
            </span>
          </>
        );
      }
      return (
        <>
          {label}
          <NumberInput value={stored} step={spec.step ?? 1} disabled={disabled} onCommit={onCommit} />
        </>
      );
    }
    case "select": {
      const cur = value == null ? "" : String(value);
      // Host-supplied dynamic options (e.g. subtitle language) override static.
      const opts = dynOptions ?? spec.options ?? [];
      const list = opts.includes(cur) ? opts : [cur, ...opts];
      return (
        <>
          {label}
          <select value={cur} disabled={disabled} onChange={(e) => onCommit(e.target.value)} style={INPUT_STYLE}>
            {list.map((o) => (
              <option key={o} value={o}>
                {spec.optionLabelKeys?.[o] ? tr(spec.optionLabelKeys[o]!) : o || tr("clip.property.unset")}
              </option>
            ))}
          </select>
        </>
      );
    }
    case "image": {
      const path = typeof value === "string" ? value : "";
      const browse = async () => {
        const p = await window.vc.pickImage();
        if (p) onCommit(p);
      };
      return (
        <>
          {label}
          <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input value={path} readOnly placeholder={tr("watermark.no_file")} title={path} style={INPUT_STYLE} />
            <button onClick={() => void browse()} disabled={disabled} style={BTN}>
              {tr("watermark.browse")}
            </button>
            {path && (
              <button onClick={() => onCommit("")} disabled={disabled} style={BTN}>
                {tr("watermark.clear")}
              </button>
            )}
          </span>
        </>
      );
    }
    case "color":
      return (
        <>
          {label}
          <ColorInput value={String(value ?? "")} disabled={disabled} onCommit={onCommit} />
        </>
      );
    case "text":
    default:
      return (
        <>
          {label}
          <TextInput value={String(value ?? "")} disabled={disabled} onCommit={onCommit} />
        </>
      );
  }
}

const SECTION_STYLE: React.CSSProperties = {
  gridColumn: "1 / -1",
  fontSize: 11,
  color: "#888",
  fontWeight: 700,
  margin: "8px 0 2px",
};

const BTN: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ccc",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "2px 10px",
  fontSize: 12,
  cursor: "pointer",
  flex: "0 0 auto",
};
