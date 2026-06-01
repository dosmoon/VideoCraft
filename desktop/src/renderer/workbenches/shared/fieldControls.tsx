/**
 * Bare property-form input controls used by the metadata-driven ComponentEditor.
 * Each commits on blur / Enter (not per keystroke) so editing doesn't fire an
 * RPC write per character, and re-syncs when its `value` prop changes.
 */

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { HexColorPicker } from "react-colorful";

const HEX6 = /^#[0-9a-fA-F]{6}$/;

export const INPUT_STYLE: CSSProperties = {
  width: "100%",
  maxWidth: 160,
  padding: "2px 6px",
  background: "#1a1a1e",
  color: "#ddd",
  border: "1px solid #333",
  borderRadius: 3,
  fontSize: 12,
};

export function TextInput(props: { value: string; disabled: boolean; onCommit: (v: string) => void }) {
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

export function ColorInput(props: { value: string; disabled: boolean; onCommit: (v: string) => void }) {
  const { value, disabled, onCommit } = props;
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
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
      <ColorSwatchPicker value={value} disabled={disabled} onCommit={onCommit} />
    </span>
  );
}

/**
 * Clickable color swatch that opens a react-colorful popover (saturation square
 * + hue bar + hex field). Electron exposes no native color dialog, and the
 * Chromium <input type="color"> picker is bare-bones — this is the standard
 * lightweight in-app picker. Commits on close (popover dismiss) to avoid an RPC
 * write per drag frame; the swatch shows the live draft while open.
 */
export function ColorSwatchPicker(props: { value: string; disabled: boolean; onCommit: (v: string) => void }) {
  const { value, disabled, onCommit } = props;
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef<HTMLSpanElement>(null);

  // Re-seed the draft from the committed value whenever the popover is closed.
  useEffect(() => {
    if (!open) setDraft(value);
  }, [value, open]);

  const close = () => {
    setOpen(false);
    const hex = draft.toUpperCase();
    if (HEX6.test(hex) && hex !== value) onCommit(hex);
  };

  // Outside-click closes (and commits). Re-subscribe on draft change so the
  // handler's closure commits the latest draft.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, draft, value]);

  const shown = open && HEX6.test(draft) ? draft : HEX6.test(value) ? value : "#000000";
  return (
    <span ref={ref} style={{ position: "relative", display: "inline-flex", flexShrink: 0 }}>
      <button
        type="button"
        disabled={disabled}
        title={value}
        onClick={() => (disabled ? undefined : open ? close() : setOpen(true))}
        style={{
          width: 20,
          height: 18,
          padding: 0,
          border: "1px solid #444",
          borderRadius: 3,
          background: shown,
          cursor: disabled ? "default" : "pointer",
        }}
      />
      {open && (
        <div
          style={{
            position: "absolute",
            zIndex: 100,
            top: "100%",
            right: 0,
            marginTop: 6,
            padding: 8,
            background: "#1e1e22",
            border: "1px solid #444",
            borderRadius: 8,
            boxShadow: "0 6px 20px rgba(0,0,0,0.5)",
          }}
        >
          <HexColorPicker color={HEX6.test(draft) ? draft : "#000000"} onChange={(c) => setDraft(c.toUpperCase())} />
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && close()}
            spellCheck={false}
            style={{ ...INPUT_STYLE, width: 200, maxWidth: 200, marginTop: 8 }}
          />
        </div>
      )}
    </span>
  );
}

export function NumberInput(props: {
  value: number;
  step: number;
  disabled: boolean;
  onCommit: (v: number) => void;
}) {
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
