/**
 * ImageWatermarkProperties — dedicated editor for an image-watermark component.
 *
 * The generic PropertyPanel only renders keys that exist on the component and
 * has no file picker, so an image watermark (especially one applied from a
 * preset, which drops image_path as per-project content) showed no way to set
 * its image. This editor always shows an "图片文件" row with a 浏览… button
 * (native file dialog via window.vc.pickImage) + 清除, then delegates the
 * remaining primitive fields (scale / opacity / position / margins) to the
 * shared PropertyPanel (with image_path hidden so it isn't duplicated).
 */

import type { Component } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { PropertyPanel } from "../clip/propertyEditor";

const inputStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  padding: "2px 6px",
  background: "#1a1a1e",
  color: "#ddd",
  border: "1px solid #333",
  borderRadius: 3,
  fontSize: 12,
};
const btn: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ccc",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "2px 10px",
  fontSize: 12,
  cursor: "pointer",
  flex: "0 0 auto",
};

export function ImageWatermarkProperties(props: {
  component: Component;
  disabled: boolean;
  onPatch: (fields: Record<string, unknown>) => void;
}) {
  const { component, disabled, onPatch } = props;
  const path = typeof component["image_path"] === "string" ? (component["image_path"] as string) : "";

  const browse = async () => {
    const p = await window.vc.pickImage();
    if (p) onPatch({ image_path: p });
  };

  return (
    <div>
      <div style={{ marginBottom: 10 }}>
        <label style={{ color: "#999", fontSize: 12, display: "block", marginBottom: 4 }}>
          {tr("news_desk.watermark.image_file")}
        </label>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input value={path} readOnly placeholder={tr("news_desk.watermark.no_file_selected")} title={path} style={inputStyle} />
          <button onClick={() => void browse()} disabled={disabled} style={btn}>
            {tr("news_desk.watermark.browse")}
          </button>
          {path && (
            <button onClick={() => onPatch({ image_path: "" })} disabled={disabled} style={btn}>
              {tr("news_desk.watermark.clear")}
            </button>
          )}
        </div>
      </div>
      <PropertyPanel
        component={component}
        disabled={disabled}
        hide={["image_path"]}
        onCommit={(k, v) => onPatch({ [k]: v })}
      />
    </div>
  );
}
