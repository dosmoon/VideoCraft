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

type WorkbenchProps = { type: string; instance: string; onClose: () => void };

const REGISTRY: Record<string, ComponentType<WorkbenchProps>> = {
  clip: ClipWorkbench,
};

export function CreationWorkbench(props: WorkbenchProps) {
  const W = REGISTRY[props.type];
  if (!W) {
    return (
      <div style={{ padding: 24, color: "#777", fontSize: 13 }}>
        <p>
          “{props.type}” 工作台尚未迁移到新壳。
        </p>
      </div>
    );
  }
  return <W {...props} />;
}
