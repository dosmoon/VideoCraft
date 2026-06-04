/**
 * Python sidecar manager (migration doc §2-3).
 *
 * Spawns the core_rpc sidecar (`python -m core_rpc.server`) as a child and
 * speaks newline-delimited JSON-RPC 2.0 over its stdio:
 *   - requests  : call(method, params) → Promise, correlated by integer id
 *   - responses : matched back to the pending promise by id
 *   - notifications (no id) : emitted to `onNotification` listeners
 *
 * The sidecar reserves stdout for JSON-RPC only; its stderr is logged here.
 * Framing is line-based — stdout is decoded as UTF-8 and split on '\n'
 * (the sidecar writes one compact JSON object per line).
 */

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { EventEmitter } from "node:events";
import { delimiter } from "node:path";

import type { SidecarLaunch } from "./paths";

/**
 * How to launch the sidecar. Resolved once by `resolveAppPaths` (paths.ts) so
 * the dev↔packaged seam lives there, not here — this class just spawns whatever
 * command/args/cwd it is handed and speaks JSON-RPC over the child's stdio.
 */
export type SidecarOptions = SidecarLaunch;

type Pending = {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
};

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
  private readonly pending = new Map<number, Pending>();
  private stdoutBuf = "";
  private stderrBuf = "";
  private disposed = false;

  constructor(private readonly opts: SidecarOptions) {
    super();
  }

  start(): void {
    if (this.child) return;
    // command/args/cwd are pre-resolved (dev: venv python -m core_rpc.server
    // from repo root; packaged: resources/sidecar/core_rpc.exe).
    // ELECTRON_RUN_AS_NODE leaks into child env in this launch context and is
    // irrelevant to a plain python child, but strip it to be safe; force UTF-8
    // I/O so the JSON-RPC framing is byte-clean on Windows. opts.env carries
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
      for (const p of this.pending.values()) p.reject(err);
      this.pending.clear();
      this.child = null;
      if (!this.disposed) this.emit("exit", code, signal);
    });
    this.child.on("error", (err) => this.emit("error", err));
  }

  private onStdout(chunk: string): void {
    this.stdoutBuf += chunk;
    let nl: number;
    while ((nl = this.stdoutBuf.indexOf("\n")) >= 0) {
      const line = this.stdoutBuf.slice(0, nl).trim();
      this.stdoutBuf = this.stdoutBuf.slice(nl + 1);
      if (line) this.handleMessage(line);
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

  private handleMessage(line: string): void {
    let msg: RpcResponse;
    try {
      msg = JSON.parse(line) as RpcResponse;
    } catch {
      console.error("[sidecar] non-JSON line:", line);
      return;
    }
    // Notification (server→client event): no id, has a method.
    if ((msg.id === undefined || msg.id === null) && typeof msg.method === "string") {
      this.emit("notification", msg.method, msg.params);
      return;
    }
    const id = msg.id;
    if (typeof id !== "number") return;
    const pend = this.pending.get(id);
    if (!pend) return;
    this.pending.delete(id);
    if (msg.error) pend.reject(new SidecarError(msg.error));
    else pend.resolve(msg.result ?? null);
  }

  /** Issue a JSON-RPC request; resolves with `result` or rejects (SidecarError). */
  call(method: string, params?: Record<string, unknown>): Promise<unknown> {
    if (!this.child) return Promise.reject(new Error("sidecar not running"));
    const id = this.nextId++;
    const req = JSON.stringify({ jsonrpc: "2.0", method, params: params ?? {}, id });
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.child!.stdin.write(req + "\n", "utf-8", (err) => {
        if (err) {
          this.pending.delete(id);
          reject(err);
        }
      });
    });
  }

  /** Subscribe to server→client notifications (events + job progress). */
  onNotification(cb: (method: string, params: unknown) => void): void {
    this.on("notification", cb);
  }

  dispose(): void {
    this.disposed = true;
    if (this.child) {
      // Closing stdin ends the sidecar's read loop → clean shutdown.
      this.child.stdin.end();
      this.child.kill();
      this.child = null;
    }
  }
}
