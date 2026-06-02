/**
 * runJob — consume a sidecar long-task (core_rpc.jobs) from the renderer.
 *
 * Unlike the creation-side export (which runs the GPU encode in the renderer),
 * material ops (source acquire, ASR, translate, analysis, AI fill) run on Python
 * sidecar threads. Each start RPC returns {job_id} immediately, then the sidecar
 * emits `progress.<kind>` ticks and a terminal `event.job` — all by job_id.
 *
 * Subscribe-FIRST: we attach the notification listener before issuing the start
 * call and buffer anything that arrives until the job_id is known, then replay
 * matching events. Without this an instantaneous job could emit its terminal
 * event.job before we subscribed and the promise would hang.
 */

import { rpc, RpcError } from "./client";

/** A `progress.<kind>` payload: job_id + whatever the worker passed to job.progress. */
export interface JobProgress {
  job_id: string;
  phase?: string;
  pct?: number | null;
  speed_bps?: number | null;
  eta_sec?: number | null;
  done?: number | null;
  total?: number | null;
  status_text?: string | null;
  [key: string]: unknown;
}

export class JobCancelled extends Error {
  constructor() {
    super("cancelled");
    this.name = "JobCancelled";
  }
}

export interface RunJobHandle<T> {
  promise: Promise<T>;
  jobId: string;
  cancel: () => void;
}

/**
 * Start a job (via the supplied start thunk — typically an rpc.startXxx stub) and
 * resolve on its terminal event.job. Rejects with JobCancelled on cancel or an
 * Error carrying the server message on failure.
 */
export async function runJob<T = unknown>(
  start: () => Promise<{ job_id: string }>,
  onProgress?: (p: JobProgress) => void,
): Promise<RunJobHandle<T>> {
  let jobId: string | null = null;
  let settled = false;
  const buffered: { method: string; params: unknown }[] = [];
  let resolveFn!: (v: T) => void;
  let rejectFn!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolveFn = res;
    rejectFn = rej;
  });

  let _progN = 0; // TEMP diagnostic
  const process = (method: string, params: unknown) => {
    if (settled) return;
    if (method.startsWith("progress.")) {
      _progN += 1;
      if (_progN <= 3 || _progN % 25 === 0) console.log(`[runJob] progress #${_progN} ${method} job=${(params as {job_id?:string})?.job_id}`);
      onProgress?.(params as JobProgress);
      return;
    }
    if (method === "event.job") {
      console.log(`[runJob] TERMINAL ${method}`, params);
      settled = true;
      const p = params as { status?: string; result?: unknown; error?: unknown };
      if (p.status === "succeeded") resolveFn(p.result as T);
      else if (p.status === "cancelled") rejectFn(new JobCancelled());
      else rejectFn(new Error(String(p.error ?? "job failed")));
    }
  };

  const handle = (method: string, params: unknown) => {
    if (jobId === null) {
      buffered.push({ method, params }); // job_id unknown yet — buffer
      return;
    }
    const pj = (params as { job_id?: string } | null)?.job_id;
    if (pj !== jobId) {
      if (method === "event.job" || method.startsWith("progress.")) console.log(`[runJob] SKIP (job mismatch) ${method} got=${pj} want=${jobId}`);
      return;
    }
    process(method, params);
  };

  const unsub = rpc.onNotification(handle);
  try {
    const { job_id } = await start();
    jobId = job_id;
    console.log(`[runJob] started job=${jobId}, buffered=${buffered.length}`);
    // Replay anything that arrived for us before job_id was known.
    for (const b of buffered) {
      if ((b.params as { job_id?: string } | null)?.job_id === jobId) process(b.method, b.params);
    }
    buffered.length = 0;
  } catch (err) {
    unsub();
    throw err;
  }
  void promise.finally(unsub);

  const id = jobId as string;
  return {
    promise,
    jobId: id,
    cancel: () => {
      void rpc.cancelJob(id);
    },
  };
}

// ── React convenience hook ────────────────────────────────────────────────────

import { useCallback, useRef, useState } from "react";

export interface JobUiState {
  running: boolean;
  progress: JobProgress | null;
  error: string;
}

/**
 * useJob — a small wrapper that tracks running/progress/error and exposes
 * run()/cancel(). run() resolves with the job result on success, or undefined on
 * failure/cancel (the error lands in `error`; JobCancelled is silent).
 */
export function useJob() {
  const [state, setState] = useState<JobUiState>({ running: false, progress: null, error: "" });
  const handleRef = useRef<RunJobHandle<unknown> | null>(null);

  const run = useCallback(
    async <T,>(start: () => Promise<{ job_id: string }>): Promise<T | undefined> => {
      setState({ running: true, progress: null, error: "" });
      try {
        const h = await runJob<T>(start, (p) => setState((s) => ({ ...s, progress: p })));
        handleRef.current = h as RunJobHandle<unknown>;
        const result = await h.promise;
        setState({ running: false, progress: null, error: "" });
        return result;
      } catch (err) {
        if (err instanceof JobCancelled) {
          setState({ running: false, progress: null, error: "" });
          return undefined;
        }
        const msg = err instanceof RpcError ? `[${err.code}] ${err.message}` : err instanceof Error ? err.message : String(err);
        setState({ running: false, progress: null, error: msg });
        return undefined;
      } finally {
        handleRef.current = null;
      }
    },
    [],
  );

  const cancel = useCallback(() => handleRef.current?.cancel(), []);

  return { ...state, run, cancel };
}
