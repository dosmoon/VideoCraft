/**
 * News-video material instance resolution (ADR-0008 Phase B4).
 *
 * Constructs a NewsVideoModel over the real (main-process) fs for a given
 * instance. The instance dir is resolved via the plugin-agnostic
 * `project.material_instance_dir` RPC (the base layer never hard-codes a
 * material name — ADR-0004/0008).
 *
 * Shared by the material backend (clientBackend.ts) and the creation plugins
 * that consume news_video material (clip preview / news_desk preview + imports,
 * C7): creations access material data ONLY through the TS model
 * ([[feedback_material_via_model_only]]), never the Python sidecar.
 */

import { realFs } from "../../renderer/ipc/fs";
import { rpcCall } from "../../renderer/ipc/client";
import { NewsVideoModel } from "./model";

export async function loadNewsVideoModel(instance: string): Promise<NewsVideoModel> {
  const dir = await rpcCall<string>("project.material_instance_dir", {
    type: "news_video",
    instance,
  });
  return new NewsVideoModel(realFs, dir);
}
