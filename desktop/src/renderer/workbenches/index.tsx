/**
 * CreationWorkbench — generic host that dispatches to a per-plugin workbench by
 * creation type. The Hub renders this and stays plugin-agnostic; each creation
 * plugin owns its own workbench module under workbenches/<type>/.
 *
 * Registry is keyed by the RPC creation type name. A type with no registered
 * workbench falls back to a "not yet ported" notice (e.g. news_desk later).
 */

import type { ComponentType } from "react";
import { ClipWorkbench } from "./clip/ClipWorkbench";
import { NewsDeskWorkbench } from "./news_desk/NewsDeskWorkbench";
import { MaterialWorkbench as NewsVideoWorkbench } from "./material/MaterialWorkbench";

type WorkbenchProps = { type: string; instance: string; onClose: () => void };

const REGISTRY: Record<string, ComponentType<WorkbenchProps>> = {
  clip: ClipWorkbench,
  news_desk: NewsDeskWorkbench,
};

// Material-side workbenches, dispatched by material type (parallel to creations).
const MATERIAL_REGISTRY: Record<string, ComponentType<WorkbenchProps>> = {
  news_video: NewsVideoWorkbench,
};

function NotPorted({ type }: { type: string }) {
  return (
    <div style={{ padding: 24, color: "#777", fontSize: 13 }}>
      <p>“{type}” 工作台尚未迁移到新壳。</p>
    </div>
  );
}

export function CreationWorkbench(props: WorkbenchProps) {
  const W = REGISTRY[props.type];
  return W ? <W {...props} /> : <NotPorted type={props.type} />;
}

export function MaterialWorkbench(props: WorkbenchProps) {
  const W = MATERIAL_REGISTRY[props.type];
  return W ? <W {...props} /> : <NotPorted type={props.type} />;
}
