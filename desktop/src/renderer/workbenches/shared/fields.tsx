/**
 * Shared property-form field rows — extracted from news_desk/ChapterProperties so
 * both the news_desk chapter editor and the material workbench (context / chapter
 * schedule editors) draw the same controls. Every row commits on blur / Enter (not
 * per-keystroke) and re-syncs when its `value` prop changes.
 */

import { useEffect, useState } from "react";
import { ColorSwatchPicker } from "./fieldControls";
import { color, font, radius } from "../../ui/tokens";

const LABEL: React.CSSProperties = { color: color.textSecondary, fontSize: font.md, flexShrink: 0 };
const INPUT: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  padding: "3px 8px",
  background: color.bgInset,
  color: color.textPrimary,
  border: `1px solid ${color.border}`,
  borderRadius: radius.sm,
  fontSize: font.md,
};

export function Section({ title }: { title: string }) {
  return (
    <div style={{ fontSize: font.sm, color: color.textMuted, fontWeight: 700, margin: "10px 0 3px" }}>{title}</div>
  );
}

export function CheckRow(props: {
  label: string;
  value: boolean;
  disabled: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0" }}>
      <input
        type="checkbox"
        checked={props.value}
        disabled={props.disabled}
        onChange={(e) => props.onChange(e.target.checked)}
      />
      <span style={{ color: color.textPrimary, fontSize: font.md }}>{props.label}</span>
    </label>
  );
}

export function TextRow(props: {
  label: string;
  value: string;
  disabled: boolean;
  onCommit: (v: string) => void;
  labelWidth?: number;
  inputMaxWidth?: number;
}) {
  const [v, setV] = useState(props.value);
  useEffect(() => setV(props.value), [props.value]);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0" }}>
      <span style={{ ...LABEL, width: props.labelWidth ?? 86 }}>{props.label}</span>
      <input
        value={v}
        disabled={props.disabled}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => v !== props.value && props.onCommit(v)}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        style={{ ...INPUT, ...(props.inputMaxWidth != null ? { maxWidth: props.inputMaxWidth } : {}) }}
      />
    </div>
  );
}

/** Multiline text — commits on blur (Enter inserts a newline, unlike TextRow). */
export function TextAreaRow(props: {
  label: string;
  value: string;
  disabled: boolean;
  onCommit: (v: string) => void;
  rows?: number;
  labelWidth?: number;
}) {
  const [v, setV] = useState(props.value);
  useEffect(() => setV(props.value), [props.value]);
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "2px 0" }}>
      <span style={{ ...LABEL, width: props.labelWidth ?? 86, marginTop: 4 }}>{props.label}</span>
      <textarea
        value={v}
        disabled={props.disabled}
        rows={props.rows ?? 3}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => v !== props.value && props.onCommit(v)}
        style={{ ...INPUT, maxWidth: "none", resize: "vertical", fontFamily: "inherit", lineHeight: 1.4 }}
      />
    </div>
  );
}

export function NumRow(props: {
  label: string;
  value: number;
  disabled: boolean;
  onCommit: (v: number) => void;
  labelWidth?: number;
}) {
  const [v, setV] = useState(String(props.value));
  useEffect(() => setV(String(props.value)), [props.value]);
  const commit = () => {
    const n = Number(v);
    if (!Number.isNaN(n) && n !== props.value) props.onCommit(n);
    else setV(String(props.value));
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0" }}>
      <span style={{ ...LABEL, width: props.labelWidth ?? 86 }}>{props.label}</span>
      <input
        type="number"
        step="any"
        value={v}
        disabled={props.disabled}
        onChange={(e) => setV(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        style={INPUT}
      />
    </div>
  );
}

export function ColorRow(props: {
  label: string;
  value: string;
  disabled: boolean;
  onCommit: (v: string) => void;
  labelWidth?: number;
}) {
  const [v, setV] = useState(props.value);
  useEffect(() => setV(props.value), [props.value]);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0" }}>
      <span style={{ ...LABEL, width: props.labelWidth ?? 86 }}>{props.label}</span>
      <input
        value={v}
        disabled={props.disabled}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => v !== props.value && props.onCommit(v)}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        style={{ ...INPUT, maxWidth: 110 }}
      />
      <ColorSwatchPicker value={props.value} disabled={props.disabled} onCommit={props.onCommit} />
    </div>
  );
}
