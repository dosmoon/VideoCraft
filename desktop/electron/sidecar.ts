/**
 * Python sidecar manager (ADR-0010 — HTTP transport).
 *
 * Spawns the core_rpc sidecar and talks to it over HTTP instead of the legacy
 * newline-JSON-over-stdio loop (which deadlocked when a native C-extension was
 * first imported on a job thread while the main thread was parked in a blocking
 * stdin read). The sidecar is a FastAPI/uvicorn server:
 *   - requests       : call(method, params) → POST /rpc (one JSON-RPC object)
 *   - notifications  : onNotification(cb)   ← GET /events (Server-Sent Events)
 *
 * Startup handshake: the sidecar binds an ephemeral 127.0.0.1 port and prints a
 * single `VC_RPC_PORT <n>` line to stdout; we read it to learn the base URL, then
 * open the SSE stream. After that line, stdout is unused; stderr is logged here.
 *
 * Public API (start / call / onNotification / dispose / SidecarError) is identical
 * to the old stdio implementation, so main.ts / preload / renderer are unchanged.
 */

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { EventEmitter } from "node:events";
import { delimiter } from "node:path";

import type { SidecarLaunch } from "./paths";

/**
 * How to launch the sidecar. Resolved once by `resolveAppPaths` (paths.ts) so
 * the dev↔packaged seam lives there, not here — this class just spawns whatever
 * command/args/cwd it is handed and speaks HTTP+SSE to the resulting server.
 */
export type SidecarOptions = SidecarLaunch;

interface RpcError {
  code: number;
  message: string;
  data?: unknown;
}

interface RpcResponse {
  jsonrpc: "2.0";
  id?: number | string | null;
  result?: unknown;
  error?: RpcError;
  method?: string;
  params?: unknown;
}

/** Thrown when the sidecar returns a JSON-RPC error object. */
export class SidecarError extends Error {
  code: number;
  data: unknown;
  constructor(err: RpcError) {
    super(err.message);
    this.name = "SidecarError";
    this.code = err.code;
    this.data = err.data;
  }
}

export class Sidecar extends EventEmitter {
  private child: ChildProcessWithoutNullStreams | null = null;
  private nextId = 1;
  private baseUrl: string | null = null;
  private stdoutBuf = "";
  private stderrBuf = "";
  private disposed = false;
  private sseAbort: AbortController | null = null;

  // Resolves once the port handshake arrives; call() awaits it so requests
  // issued during the brief spawn→listen window don't race a missing baseUrl.
  private readonly ready: Promise<void>;
  private resolveReady!: () => void;
  private rejectReady!: (err: Error) => void;

  constructor(private readonly opts: SidecarOptions) {
    super();
    this.ready = new Promise<void>((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });
  }

  start(): void {
    if (this.child) return;
    // command/args/cwd are pre-resolved (dev: venv python -m core_rpc.server from
    // repo root; packaged: resources/sidecar/core_rpc.exe). ELECTRON_RUN_AS_NODE
    // leaks into child env in this launch context and is irrelevant to a plain
    // python child, but strip it to be safe; force UTF-8 I/O. opts.env carries
    // VC_USER_DATA (where the sidecar puts models / settings / py-extra).
    const env: Record<string, string | undefined> = {
      ...process.env,
      ELECTRON_RUN_AS_NODE: undefined,
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      ...this.opts.env,
    };
    if (this.opts.extraPath) {
      // Prepend the bundled-binary dir (ffmpeg/ffprobe) to PATH. Mutate the
      // EXISTING key — on Windows that is "Path", and adding a separate "PATH"
      // would leave the child with two conflicting entries.
      const pathKey = Object.keys(env).find((k) => k.toUpperCase() === "PATH") ?? "PATH";
      env[pathKey] = `${this.opts.extraPath}${delimiter}${env[pathKey] ?? ""}`;
    }
    this.child = spawn(this.opts.command, this.opts.args, {
      cwd: this.opts.cwd,
      env,
    }) as ChildProcessWithoutNullStreams;

    this.child.stdout.setEncoding("utf-8");
    this.child.stdout.on("data", (chunk: string) => this.onStdout(chunk));
    this.child.stderr.setEncoding("utf-8");
    this.child.stderr.on("data", (chunk: string) => this.onStderr(chunk));

    this.child.on("exit", (code, signal) => {
      const err = new Error(`sidecar exited (code=${code} signal=${signal})`);
      // Died before announcing its port → unblock anyone awaiting readiness.
      if (!this.baseUrl) this.rejectReady(err);
      this.baseUrl = null;
      this.child = null;
      if (this.sseAbort) {
        this.sseAbort.abort();
        this.sseAbort = null;
      }
      if (!this.disposed) this.emit("exit", code, signal);
    });
    this.child.on("error", (err) => this.emit("error", err));
  }

  /** Parse the one-line `VC_RPC_PORT <n>` handshake from stdout, then ignore it. */
  private onStdout(chunk: string): void {
    if (this.baseUrl) return; // post-handshake stdout is unused
    this.stdoutBuf += chunk;
    let nl: number;
    while ((nl = this.stdoutBuf.indexOf("\n")) >= 0) {
      const line = this.stdoutBuf.slice(0, nl).trim();
      this.stdoutBuf = this.stdoutBuf.slice(nl + 1);
      const m = line.match(/^VC_RPC_PORT (\d+)$/);
      if (m) {
        this.baseUrl = `http://127.0.0.1:${m[1]}`;
        this.resolveReady();
        void this.openEvents();
        return;
      }
      if (line) console.error("[sidecar] (stdout)", line);
    }
  }

  private onStderr(chunk: string): void {
    // Buffer + flush whole lines so multi-line tracebacks stay readable.
    this.stderrBuf += chunk;
    let nl: number;
    while ((nl = this.stderrBuf.indexOf("\n")) >= 0) {
      const line = this.stderrBuf.slice(0, nl);
      this.stderrBuf = this.stderrBuf.slice(nl + 1);
      console.error("[sidecar]", line);
    }
  }

  /** Open the SSE notification stream and translate frames into "notification"
   *  events. Reconnects on an unexpected drop while the child is still alive. */
  private async openEvents(): Promise<void> {
    if (!this.baseUrl || this.disposed) return;
    this.sseAbort = new AbortController();
    let resp: Response;
    try {
      resp = await fetch(`${this.baseUrl}/events`, {
        headers: { Accept: "text/event-stream" },
        signal: this.sseAbort.signal,
      });
    } catch {
      this.scheduleEventsReconnect();
      return;
    }
    if (!resp.ok || !resp.body) {
      this.scheduleEventsReconnect();
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let opened = false;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        if (!opened) {
          // First bytes (the server's ": connected" frame) prove our subscriber
          // is registered server-side. Lifecycle signal — harmless to ignore.
          opened = true;
          this.emit("sse-open");
        }
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          this.handleSseFrame(buf.slice(0, idx));
          buf = buf.slice(idx + 2);
        }
      }
    } catch {
      // aborted (dispose) or connection dropped — fall through to reconnect.
    }
    this.scheduleEventsReconnect();
  }

  private scheduleEventsReconnect(): void {
    // Only retry if the process is still up and we're not tearing down. If the
    // child exited, its "exit" handler already cleared baseUrl → no retry.
    if (this.disposed || !this.child || !this.baseUrl) return;
    setTimeout(() => void this.openEvents(), 500);
  }

  private handleSseFrame(frame: string): void {
    const data: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("data:")) data.push(line.slice(5).trim());
      // ": ..." comment frames (connected / keepalive) carry no data → ignored.
    }
    if (data.length === 0) return;
    let msg: RpcResponse;
    try {
      msg = JSON.parse(data.join("\n")) as RpcResponse;
    } catch {
      return;
    }
    if (typeof msg.method === "string") {
      this.emit("notification", msg.method, msg.params);
    }
  }

  /** Issue a JSON-RPC request over POST /rpc; resolves with `result` or rejects
   *  (SidecarError on a JSON-RPC error, Error on a transport failure). */
  async call(method: string, params?: Record<string, unknown>): Promise<unknown> {
    await this.ready;
    if (!this.baseUrl || this.disposed) throw new Error("sidecar not running");
    const body = JSON.stringify({ jsonrpc: "2.0", method, params: params ?? {}, id: this.nextId++ });
    const resp = await fetch(`${this.baseUrl}/rpc`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    if (resp.status === 204) return null; // notification — no reply (call always has an id)
    if (!resp.ok) throw new Error(`sidecar /rpc HTTP ${resp.status}`);
    const msg = (await resp.json()) as RpcResponse;
    if (msg.error) throw new SidecarError(msg.error);
    return msg.result ?? null;
  }

  /** Subscribe to server→client notifications (events + job progress). */
  onNotification(cb: (method: string, params: unknown) => void): void {
    this.on("notification", cb);
  }

  dispose(): void {
    this.disposed = true;
    if (this.sseAbort) {
      this.sseAbort.abort();
      this.sseAbort = null;
    }
    // Best-effort graceful stop (force_exit on the server side), then kill so the
    // child is gone regardless of whether /shutdown was received.
    if (this.baseUrl) {
      void fetch(`${this.baseUrl}/shutdown`, { method: "POST" }).catch(() => {});
    }
    this.baseUrl = null;
    if (this.child) {
      this.child.kill();
      this.child = null;
    }
  }
}
