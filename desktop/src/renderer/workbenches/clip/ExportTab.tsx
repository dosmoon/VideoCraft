/**
 * Export tab (导出) — placeholder for Inc5.
 *
 * Faithful target (clip_tool._build_tab_export): batch render of the selected
 * candidates + cancel; a status Treeview (one row per candidate); right-click /
 * double-click row ops (play / open folder / re-render / delete / error detail);
 * a publish sidecar JSON. Each candidate renders through the SAME
 * buildClipTimeline the preview uses → continued by the engine export path
 * (resolveFrameAt → WebCodecs encode, substrate spike C).
 *
 * Needs RPC: render orchestration (render.start job + progress + cancel events).
 */

export function ExportTab(_props: { type: string; instance: string }) {
  return (
    <div style={{ padding: 24, color: "#777", fontSize: 13 }}>
      <strong style={{ color: "#aaa" }}>导出</strong>
      <p style={{ marginTop: 8 }}>
        批量渲染 + 取消 + 状态表 + 行操作 + sidecar JSON —— Inc5（复用 buildClipTimeline → WebCodecs 编码）。
      </p>
    </div>
  );
}
