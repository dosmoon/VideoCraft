/**
 * ChapterProperties — the chapter component's editor. The generic PropertyPanel
 * only renders primitive fields, so the chapter's nested modes/style were
 * invisible (the user saw only "name"). This editor exposes them: the two layer
 * toggles (top strip / start card) and each layer's style fields. All edits go
 * through the pure patchMode/patchStrip/patchCard builders, which re-send the
 * whole nested object so update_component's shallow merge keeps siblings.
 *
 * Schedule (the chapter rows) is imported from the material's analysis.json
 * (the ImportRow above this panel) — per-row editing is a later increment.
 */

import type { Component } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { Section, CheckRow, TextRow, NumRow, ColorRow } from "../shared/fields";
import {
  patchMode,
  patchStrip,
  patchCard,
  readModes,
  readStrip,
  readCard,
} from "./chapterPatch";

export function ChapterProperties(props: {
  component: Component;
  disabled: boolean;
  onPatch: (fields: Record<string, unknown>) => void;
}) {
  const { component, disabled, onPatch } = props;
  const modes = readModes(component);
  const strip = readStrip(component);
  const card = readCard(component);
  const name = typeof component["name"] === "string" ? (component["name"] as string) : "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <TextRow label={tr("news_desk.chapter.name")} value={name} disabled={disabled} onCommit={(v) => onPatch({ name: v })} />

      <Section title={tr("news_desk.chapter.mode_section")} />
      <CheckRow
        label={tr("news_desk.chapter.mode_top_strip")}
        value={modes.top_strip}
        disabled={disabled}
        onChange={(v) => onPatch(patchMode(component, "top_strip", v))}
      />
      <CheckRow
        label={tr("news_desk.chapter.mode_start_card")}
        value={modes.start_card}
        disabled={disabled}
        onChange={(v) => onPatch(patchMode(component, "start_card", v))}
      />

      {modes.top_strip && (
        <>
          <Section title={tr("news_desk.chapter.strip_style_section")} />
          <ColorRow label={tr("news_desk.chapter.bg_color")} value={strip.bg_color} disabled={disabled}
            onCommit={(v) => onPatch(patchStrip(component, "bg_color", v))} />
          <ColorRow label={tr("news_desk.chapter.text_color")} value={strip.text_color} disabled={disabled}
            onCommit={(v) => onPatch(patchStrip(component, "text_color", v))} />
          <NumRow label={tr("news_desk.chapter.fontsize")} value={strip.fontsize} disabled={disabled}
            onCommit={(v) => onPatch(patchStrip(component, "fontsize", v))} />
        </>
      )}

      {modes.start_card && (
        <>
          <Section title={tr("news_desk.chapter.card_style_section")} />
          <ColorRow label={tr("news_desk.chapter.title_color")} value={card.title_color} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "title_color", v))} />
          <NumRow label={tr("news_desk.chapter.title_fontsize")} value={card.title_fontsize} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "title_fontsize", v))} />
          <ColorRow label={tr("news_desk.chapter.body_color")} value={card.body_color} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "body_color", v))} />
          <NumRow label={tr("news_desk.chapter.body_fontsize")} value={card.body_fontsize} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "body_fontsize", v))} />
          <ColorRow label={tr("news_desk.chapter.card_bg_color")} value={card.bg_color} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "bg_color", v))} />
          <NumRow label={tr("news_desk.chapter.bg_opacity")} value={card.bg_opacity} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "bg_opacity", v))} />
          <ColorRow label={tr("news_desk.chapter.accent_color")} value={card.accent_color} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "accent_color", v))} />
          <NumRow label={tr("news_desk.chapter.duration_sec")} value={card.duration_sec} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "duration_sec", v))} />
        </>
      )}

      <p style={{ color: "#666", fontSize: 11, marginTop: 8 }}>
        {tr("news_desk.chapter.schedule_hint")}
      </p>
    </div>
  );
}
