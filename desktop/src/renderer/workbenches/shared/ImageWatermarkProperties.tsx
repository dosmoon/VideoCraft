/**
 * ImageWatermarkProperties — dedicated editor for an image-watermark component,
 * shared across creations (clip + news_desk). The generic PropertyPanel renders
 * image_path as a plain text field with no file picker, so a hand-typed path is
 * easy to get subtly wrong (→ the image silently fails to load). This always
 * shows an image-file row with a 浏览… button (native dialog via
 * window.vc.pickImage) + 清除, then delegates the remaining primitive fields
 * (scale / opacity / position / margins) to the shared PropertyPanel (image_path
 * hidden so it isn't duplicated).
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
          {tr("watermark.image_file")}
        </label>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input value={path} readOnly placeholder={tr("watermark.no_file")} title={path} style={inputStyle} />
          <button onClick={() => void browse()} disabled={disabled} style={btn}>
            {tr("watermark.browse")}
          </button>
          {path && (
            <button onClick={() => onPatch({ image_path: "" })} disabled={disabled} style={btn}>
              {tr("watermark.clear")}
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
