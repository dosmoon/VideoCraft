/**
 * News-desk config backend — TS owner behind the `creation.*` client surface
 * (ADR-0008 Phase A5). Mirrors clip's clientBackend: the client dispatches
 * `type === "news_desk"` here for config / components / presets / render, while
 * preview_data + imports stay on the Python sidecar in Phase A (they need
 * material file access — deferred to Phase B). Stateless load-mutate-save per op.
 */

import { realFs } from "../../renderer/ipc/fs";
import { rpcCall } from "../../renderer/ipc/client";
import type { Component, PresetList, ProjectBrief, RenderPlan, RenderedClip } from "../../renderer/ipc/client";
import { NewsDeskConfigOwner } from "./configOwner";
import { buildNewsDeskPreview, emptyNewsDeskPreview, type NewsDeskPreviewResult } from "./preview";
import { importNewsDeskResource, listNewsDeskImports, type DubImport } from "./imports";
import { loadNewsVideoModel } from "../../materials/news_video/resolve";
import * as render from "./render";

async function instanceDir(instance: string): Promise<string> {
  return rpcCall<string>("project.creation_instance_dir", { type: "news_desk", instance });
}

async function withOwner<T>(instance: string, fn: (o: NewsDeskConfigOwner, dir: string) => Promise<T> | T): Promise<T> {
  const dir = await instanceDir(instance);
  const owner = await NewsDeskConfigOwner.load(realFs, `${dir}/config.json`);
  return fn(owner, dir);
}

/** News-desk preview inputs (ADR-0008 B4): resolves the bound material + project
 *  meta duration, then delegates the SRT resolution to buildNewsDeskPreview. */
async function loadPreview(instance: string): Promise<NewsDeskPreviewResult> {
  return withOwner(instance, async (owner, dir) => {
    if (!owner.boundMaterial) return emptyNewsDeskPreview();
    const model = await loadNewsVideoModel(owner.boundMaterial.instance_name);
    // Duration from project meta.source (Python's model.get_source_meta() reads
    // the same project-level descriptor; meta survives independent of the file).
    const cur = await rpcCall<ProjectBrief | null>("project.current");
    const s = ((cur?.meta as { source?: { duration_sec?: number } } | undefined)?.source ?? {});
    const durationSec = Number(s.duration_sec) || 0;
    return buildNewsDeskPreview(owner.components, dir, realFs, model.sourceVideoPath, durationSec);
  });
}

/** Bound material context + project meta for publish.md (content follows source). */
async function publishInputs(owner: NewsDeskConfigOwner): Promise<{
  context: Record<string, unknown>;
  projectTitle: string | null;
  sourceUrl: string | null;
  langIso: string;
}> {
  let context: Record<string, unknown> = {};
  const bm = owner.boundMaterial;
  if (bm) {
    try {
      // Read the bound material's context via the TS model (ADR-0008 B5: creations
      // access material data through the TS model, never the Python sidecar).
      context = (await (await loadNewsVideoModel(bm.instance_name)).readContext()) as Record<
        string,
        unknown
      >;
    } catch {
      context = {};
    }
  }
  const cur = await rpcCall<ProjectBrief | null>("project.current");
  const meta = (cur?.meta ?? {}) as { source?: { title?: string; url?: string }; language?: { source?: string } };
  return {
    context: context && typeof context === "object" ? context : {},
    projectTitle: meta.source?.title ?? null,
    sourceUrl: meta.source?.url ?? null,
    langIso: meta.language?.source || "zh",
  };
}

export const newsDeskBackend = {
  loadConfig: (instance: string) => withOwner(instance, (o) => o.toJSON()),

  bindMaterial: (instance: string, materialType: string, materialInstance: string) =>
    withOwner(instance, async (o) => {
      o.bindMaterial(materialType, materialInstance);
      await o.save();
      return o.toJSON();
    }),

  listComponents: (instance: string) => withOwner(instance, (o) => o.components as unknown as Component[]),

  previewData: (instance: string): Promise<unknown> => loadPreview(instance),

  updateComponent: (instance: string, componentId: string, patch: Record<string, unknown>) =>
    withOwner(instance, async (o) => {
      const c = o.updateComponent(componentId, patch);
      await o.save();
      return (c ?? {}) as unknown as Component;
    }),

  updateConfig: (instance: string, patch: Record<string, unknown>) =>
    withOwner(instance, async (o) => {
      o.applyPatch(patch);
      await o.save();
      return o.toJSON();
    }),

  listAddableComponents: () => Promise.resolve(NewsDeskConfigOwner.addableKinds()),

  addComponent: (instance: string, kind: string) =>
    withOwner(instance, async (o) => {
      o.addComponent(kind);
      await o.save();
      return o.components as unknown as Component[];
    }),

  removeComponent: (instance: string, componentId: string) =>
    withOwner(instance, async (o) => {
      o.removeComponent(componentId);
      await o.save();
      return o.components as unknown as Component[];
    }),

  moveComponent: (instance: string, componentId: string, delta: number) =>
    withOwner(instance, async (o) => {
      o.moveComponent(componentId, delta);
      await o.save();
      return o.components as unknown as Component[];
    }),

  listPresets: (instance: string): Promise<PresetList> => withOwner(instance, (o) => o.listPresets()),

  applyPreset: (instance: string, name: string) =>
    withOwner(instance, async (o) => {
      await o.applyPreset(name);
      await o.save();
      return o.toJSON();
    }),

  savePreset: (instance: string, name: string): Promise<PresetList> =>
    withOwner(instance, async (o) => {
      await o.savePreset(name);
      await o.save();
      return o.listPresets();
    }),

  deletePreset: (instance: string, name: string): Promise<PresetList> =>
    withOwner(instance, async (o) => {
      await o.deletePreset(name);
      return o.listPresets();
    }),

  // Material-artifact imports (ADR-0008 B4 TS port of creations/news_desk/imports.py).
  // list_imports reports the bound material's subtitle languages + analysis files;
  // import_resource SNAPSHOTS one into a component (snapshot principle, ADR-0003):
  // a subtitle copies the chosen language's SRT into the instance and points its
  // srt_path at it; a chapter fills its schedule from an analysis.json envelope.
  listImports: (
    instance: string,
  ): Promise<{ subtitleLangs: string[]; analyses: string[]; dubVersions: DubImport[] }> =>
    withOwner(instance, async (o) => {
      if (!o.boundMaterial) return { subtitleLangs: [], analyses: [], dubVersions: [] };
      return listNewsDeskImports(await loadNewsVideoModel(o.boundMaterial.instance_name));
    }),

  importResource: (instance: string, componentId: string, params: Record<string, unknown>): Promise<Component> =>
    withOwner(instance, async (o, dir) => {
      if (!o.boundMaterial) throw new Error("creation is not bound to a material");
      const model = await loadNewsVideoModel(o.boundMaterial.instance_name);
      const updated = await importNewsDeskResource(o, realFs, dir, model, componentId, params);
      return updated as unknown as Component;
    }),

  planRender: (instance: string): Promise<RenderPlan> =>
    withOwner(instance, async (_o, dir) => {
      const { mediaRef, durationSec } = await loadPreview(instance);
      return render.planRender(dir, mediaRef, durationSec) as unknown as RenderPlan;
    }),

  // src_idx is unused (single output); out_idx is pinned to 1 by the renderer.
  commitRender: (instance: string, _srcIdx: number, _outIdx: number, durationSec: number): Promise<RenderedClip[]> =>
    withOwner(instance, async (o, dir) => {
      const pub = await publishInputs(o);
      const rendered = await render.commitRender({ owner: o, fs: realFs, instanceDir: dir, ...pub }, durationSec);
      return rendered as unknown as RenderedClip[];
    }),

  deleteRender: (instance: string, _outIdx: number): Promise<RenderedClip[]> =>
    withOwner(instance, async (o, dir) => {
      const rendered = await render.deleteRender({ owner: o, fs: realFs, instanceDir: dir });
      return rendered as unknown as RenderedClip[];
    }),
};
