/**
 * Real integration test for the Electron-side HTTP transport (ADR-0010).
 *
 * Drives the ACTUAL Sidecar class against a real spawned `python -m core_rpc.server`
 * — exercising the port handshake, POST /rpc (sync + error), and the SSE event
 * stream end to end (the parts typecheck can't prove). Skipped automatically where
 * the repo venv (myenv) is absent, so it is CI-safe.
 */

import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { Sidecar, SidecarError } from "../electron/sidecar";

const here = fileURLToPath(new URL(".", import.meta.url)); // desktop/src/
const repoRoot = resolve(here, "../../");
const py =
  process.platform === "win32"
    ? resolve(repoRoot, "myenv/Scripts/python.exe")
    : resolve(repoRoot, "myenv/bin/python");

function waitFor(pred: () => boolean, timeoutMs: number): Promise<void> {
  return new Promise((res, rej) => {
    const deadline = Date.now() + timeoutMs;
    const tick = () => {
      if (pred()) return res();
      if (Date.now() > deadline) return rej(new Error("waitFor timed out"));
      setTimeout(tick, 25);
    };
    tick();
  });
}

(existsSync(py) ? describe : describe.skip)("Sidecar HTTP transport (real subprocess)", () => {
  it("handshakes, answers /rpc, and streams job progress over SSE", async () => {
    const sc = new Sidecar({ command: py, args: ["-u", "-m", "core_rpc.server"], cwd: repoRoot, env: {} });
    const notifs: Array<{ method: string; params: any }> = [];
    sc.onNotification((method, params) => notifs.push({ method, params }));
    // Wait for the SSE stream to be subscribed before firing the job, else its
    // notifications could be dropped (the hub does not buffer).
    const sseOpen = new Promise<void>((res) => sc.once("sse-open", () => res()));
    sc.start();
    try {
      // sync request/response
      const ping = (await sc.call("system.ping")) as { protocol: number; ok: boolean };
      expect(ping.ok).toBe(true);
      expect(ping.protocol).toBe(1);

      // UTF-8 round-trip
      const echo = (await sc.call("system.echo", { msg: "你好 🎬", n: 7 })) as Record<string, unknown>;
      expect(echo).toEqual({ msg: "你好 🎬", n: 7 });

      // JSON-RPC error → SidecarError
      await expect(sc.call("does.not.exist")).rejects.toBeInstanceOf(SidecarError);

      // job + SSE notifications
      await sseOpen;
      const res = (await sc.call("system.demo_job", { steps: 3, delay_ms: 20 })) as { job_id: string };
      const jobId = res.job_id;
      await waitFor(() => notifs.some((n) => n.method === "event.job" && n.params.job_id === jobId), 5000);
      const progress = notifs.filter((n) => n.method === "progress.demo" && n.params.job_id === jobId);
      const terminal = notifs.filter((n) => n.method === "event.job" && n.params.job_id === jobId);
      expect(progress.length).toBe(3);
      expect(terminal.at(-1)!.params.status).toBe("succeeded");
    } finally {
      sc.dispose();
    }
  }, 30000);
});
