/**
 * Shared chrome for the material right-panel detail views (subtitle viewer,
 * chapter editor, hotclips viewer, analysis text). Gives them one responsive
 * shell so they fill the panel's width/height instead of each hard-coding a
 * narrow maxWidth + small fonts:
 *
 *   DetailScaffold = height:100% flex column → fixed header + optional pinned
 *   region (e.g. a video that must stay on screen while the body scrolls) +
 *   a flex body. With scroll="body" the body scrolls (lists/cards); with
 *   scroll="none" the body is a flex column for a single fill child (a <pre>
 *   that fills + scrolls itself).
 */

import type { ReactNode } from "react";
import { color, radius, font } from "../../ui/tokens";
import { ArrowLeft } from "../../ui/icons";
import { tr } from "../../i18n/tr";

const backBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "4px 10px",
  background: color.bgHover,
  color: color.textPrimary,
  border: "none",
  borderRadius: radius.sm,
  fontSize: font.sm,
  cursor: "pointer",
  flexShrink: 0,
};

/** Header row: back (optional) + title + subtitle + inline meta + right actions. */
export function DetailHeader(props: {
  title: string;
  onBack?: () => void;
  subtitle?: string;
  meta?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0, minWidth: 0 }}>
      {props.onBack && (
        <button onClick={props.onBack} style={backBtn}>
          <ArrowLeft size={14} strokeWidth={2} />
          {tr("material.back_btn_text")}
        </button>
      )}
      <strong style={{ fontSize: font.lg, color: color.textPrimary, flexShrink: 0 }}>{props.title}</strong>
      {props.subtitle && <span style={{ fontSize: font.sm, color: color.textMuted }}>{props.subtitle}</span>}
      {props.meta}
      {props.right && <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>{props.right}</div>}
    </div>
  );
}

/** Full-height detail shell: header + optional pinned region + flex body. */
export function DetailScaffold(props: {
  header: ReactNode;
  pinned?: ReactNode;
  children: ReactNode;
  scroll?: "body" | "none";
}) {
  const scroll = props.scroll ?? "body";
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: 20, boxSizing: "border-box", gap: 12 }}>
      <div style={{ flexShrink: 0 }}>{props.header}</div>
      {props.pinned && <div style={{ flexShrink: 0 }}>{props.pinned}</div>}
      <div
        style={
          scroll === "body"
            ? { flex: 1, minHeight: 0, overflowY: "auto" }
            : { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }
        }
      >
        {props.children}
      </div>
    </div>
  );
}
