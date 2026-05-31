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
      <TextRow label="名称" value={name} disabled={disabled} onCommit={(v) => onPatch({ name: v })} />

      <Section title="模式" />
      <CheckRow
        label="顶部章节条"
        value={modes.top_strip}
        disabled={disabled}
        onChange={(v) => onPatch(patchMode(component, "top_strip", v))}
      />
      <CheckRow
        label="起始大卡片"
        value={modes.start_card}
        disabled={disabled}
        onChange={(v) => onPatch(patchMode(component, "start_card", v))}
      />

      {modes.top_strip && (
        <>
          <Section title="顶部章节条样式" />
          <ColorRow label="背景色" value={strip.bg_color} disabled={disabled}
            onCommit={(v) => onPatch(patchStrip(component, "bg_color", v))} />
          <ColorRow label="文字色" value={strip.text_color} disabled={disabled}
            onCommit={(v) => onPatch(patchStrip(component, "text_color", v))} />
          <NumRow label="字号" value={strip.fontsize} disabled={disabled}
            onCommit={(v) => onPatch(patchStrip(component, "fontsize", v))} />
        </>
      )}

      {modes.start_card && (
        <>
          <Section title="起始大卡片样式" />
          <ColorRow label="标题色" value={card.title_color} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "title_color", v))} />
          <NumRow label="标题字号" value={card.title_fontsize} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "title_fontsize", v))} />
          <ColorRow label="正文色" value={card.body_color} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "body_color", v))} />
          <NumRow label="正文字号" value={card.body_fontsize} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "body_fontsize", v))} />
          <ColorRow label="背景色" value={card.bg_color} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "bg_color", v))} />
          <NumRow label="背景不透明度" value={card.bg_opacity} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "bg_opacity", v))} />
          <ColorRow label="强调色" value={card.accent_color} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "accent_color", v))} />
          <NumRow label="持续秒数" value={card.duration_sec} disabled={disabled}
            onCommit={(v) => onPatch(patchCard(component, "duration_sec", v))} />
        </>
      )}

      <p style={{ color: "#666", fontSize: 11, marginTop: 8 }}>
        章节排期来自素材分析(上方导入);逐章编辑待后续迭代。
      </p>
    </div>
  );
}
