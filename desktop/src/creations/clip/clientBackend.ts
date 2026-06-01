/**
 * Clip config backend — TS owner behind the `creation.*` client surface
 * (ADR-0008 Phase A4).
 *
 * The clip workbench tabs are UNCHANGED: they still call `rpc.updateComponent`,
 * `rpc.applyPreset`, `rpc.planRender`, … The client (ipc/client.ts) dispatches
 * `type === "clip"` to these functions instead of the Python sidecar, so clip
 * config/preset/render now live entirely in TS while news_desk stays on Python
 * until A5. When A5/A6 land, the generic `creation.*` RPCs go away and the
 * dispatch with them.
 *
 * Stateless load-mutate-save per call: each op loads the owner from disk (via
 * window.vc.fs), applies one mutation, and saves — disk is the single source of
 * truth, so there is no in-memory cache to keep coherent across tabs. Candidate
 * data + the source path still come from Python (creation.preview_data /
 * material.get_artifact) in Phase A — render.ts takes candidates as input, so no
 * material bridge is needed yet (that's Phase B).
 */

import { realFs } from "../../renderer/ipc/fs";
import { rpcCall } from "../../renderer/ipc/client";
import type { Component, PresetList, ProjectBrief, RenderPlan, RenderedClip } from "../../renderer/ipc/client";
import { ClipConfigOwner } from "./configOwner";
import * as render from "./render";

async function instanceDir(instance: string): Promise<string> {
  return rpcCall<string>("project.creation_instance_dir", { type: "clip", instance });
}

async function withOwner<T>(instance: string, fn: (o: ClipConfigOwner, dir: string) => Promise<T> | T): Promise<T> {
  const dir = await instanceDir(instance);
  const owner = await ClipConfigOwner.load(realFs, `${dir}/config.json`);
  return fn(owner, dir);
}

/** Candidates from the Python preview provider (Phase A bridge). */
async function candidates(instance: string): Promise<Record<string, unknown>[]> {
  const pd = await rpcCall<{ candidates?: Record<string, unknown>[] }>("creation.preview_data", {
    type: "clip",
    instance,
  });
  return Array.isArray(pd.candidates) ? pd.candidates : [];
}

/** Project title + source language for publish docs (content follows the source). */
async function publishMeta(): Promise<{ projectTitle: string | null; langIso: string }> {
  const cur = await rpcCall<ProjectBrief | null>("project.current");
  const meta = (cur?.meta ?? {}) as { source?: { title?: string }; language?: { source?: string } };
  return { projectTitle: meta.source?.title ?? null, langIso: meta.language?.source || "zh" };
}

export const clipBackend = {
  loadConfig: (instance: string) => withOwner(instance, (o) => o.toJSON()),

  bindMaterial: (instance: string, materialType: string, materialInstance: string) =>
    withOwner(instance, async (o) => {
      o.bindMaterial(materialType, materialInstance);
      await o.save();
      return o.toJSON();
    }),

  listComponents: (instance: string) => withOwner(instance, (o) => o.components as unknown as Component[]),

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

  listAddableComponents: () => Promise.resolve(ClipConfigOwner.addableKinds()),

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

  planRender: (instance: string): Promise<RenderPlan> =>
    withOwner(instance, async (o, dir) => render.planRender(o, dir, await candidates(instance)) as unknown as RenderPlan),

  commitRender: (instance: string, srcIdx: number, outIdx: number, durationSec: number): Promise<RenderedClip[]> =>
    withOwner(instance, async (o, dir) => {
      const { projectTitle, langIso } = await publishMeta();
      const rendered = await render.commitRender(
        { owner: o, fs: realFs, instanceDir: dir, candidates: await candidates(instance), projectTitle, langIso },
        srcIdx,
        outIdx,
        durationSec,
      );
      return rendered as unknown as RenderedClip[];
    }),

  deleteRender: (instance: string, outIdx: number): Promise<RenderedClip[]> =>
    withOwner(instance, async (o, dir) => {
      const { projectTitle, langIso } = await publishMeta();
      const rendered = await render.deleteRender({ owner: o, fs: realFs, instanceDir: dir, projectTitle, langIso }, outIdx);
      return rendered as unknown as RenderedClip[];
    }),
};
