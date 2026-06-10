"""VideoCraft core RPC sidecar.

A thin JSON-RPC 2.0 dispatch layer over the existing Python core/business
code (see docs/_archive/electron-migration-design.md §2-3). The Electron main
process spawns this as a child and talks to it over HTTP + SSE (ADR-0010);
the renderer is a thin client that issues `ipc.call(method, params)` requests.

Layering (this package contains NO business logic — it only forwards):
  protocol.py  — JSON-RPC 2.0 framing + error objects
  registry.py  — @rpc_method decorator + Context handed to every handler
  jobs.py      — long-task registry (job_id + progress/terminal notifications)
  session.py   — single in-memory owner of the open Project (per ADR ownership)
  dispatch.py  — dispatch_message(): the testable, transport-free core
  methods/     — actual bindings, one module per RPC domain
  server.py    — stdio main loop (binary framing + off-thread writer)
"""
