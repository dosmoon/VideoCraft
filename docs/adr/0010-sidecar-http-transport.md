# ADR-0010: Electron↔Python sidecar 传输 = FastAPI HTTP + SSE（取代 stdio JSON-RPC）

- **状态**: Active
- **决定日期**: 2026-06-05

> 实施细节在代码：`core_rpc/server.py`（`build_app` + uvicorn 启动 + 握手）、
> `desktop/electron/sidecar.ts`（HTTP 客户端 + SSE）。本 ADR 只钉决策的 why +
> 边界 + 不变量 + 踩过的 gotchas。supersede `electron-migration-design.md` §2.1
> 描述的 stdio reader/writer 线程模型。

## 决定

Electron 主进程与 Python `core_rpc` sidecar 之间的传输，从**换行分隔 JSON-RPC over stdio** 换成 **FastAPI / uvicorn HTTP 服务 + SSE**：

- `POST /rpc` —— 一条 JSON-RPC 请求对象 → `dispatch_message(ctx, body)` → 响应对象。
- `GET /events` —— Server-Sent Events 流，推所有 server→client 通知（`progress.*`、`event.job`、`event.project.*`、`event.materials.changed`、`event.creations.changed`、`event.models`）。
- `POST /shutdown` —— 优雅停。

sidecar 绑临时 loopback 端口（`127.0.0.1:0`），**listening 之后**向 stdout 打一行 `VC_RPC_PORT <n>` 握手；Electron 读它建 `baseUrl`。`fastapi==0.136.3` + `uvicorn==0.49.0` 进 base 档（`pyproject [project.dependencies]`，ADR-0009）。

**这是壳替换**：`dispatch.py` / `registry.py` / `protocol.py` / `methods/`（全部 63 方法）/ `jobs.py` / `session.py` 全部 transport-agnostic，**零改动**；`sidecar.ts` 公共 API（`start`/`call`/`onNotification`/`dispose`/`SidecarError`）不变 ⟹ `main.ts` / `preload.ts` / renderer（`ipc/client.ts`、`runJob.ts`、40+ 组件）零改动。

## 为什么

一连串「死锁」其实同根：sidecar 一个进程兼了三个互相敌对的角色 —— ① 主线程**永久阻塞**读 stdin 等下一条请求（`server.py` 旧 `for raw in in_buf`）② 长任务在 job daemon 线程跑 ③ 进程内开子进程（ffmpeg/pip）共享管道/env。叠加出的病灶：

- **native import 死锁**（截图那个 ASR 卡"加载模型"）：job 线程**首次** import ctranslate2/llama_cpp，撞上某线程卡在 `sys.stdin.buffer` 阻塞读 → C-ext init 永久挂。旧修法 = 启动 warmup 人肉清单，但只覆盖启动时已装的 extra，打包态 runtime-install 进 py-extra 的 native 漏掉 → 洞重开。
- 同病不同症：clip cut 的 ffmpeg 管道死锁、`sys.executable -m pip` 在冻结态卡死、frozen-spawns-frozen 卡 bootstrap —— 全是「进程内并发 + 共享 stdio/管道/fd/env」的脆弱性，过去逐个打点补丁。

HTTP/uvicorn **没有任何阻塞 stdin 读**（事件循环走 async I/O），native import 那一整类触发条件结构性消失。**aistack 早就在 FastAPI/uvicorn 下跑 ctranslate2 worker 线程不死锁** = 目标架构可行的实证；本决策把内置（Tier 1）这条对齐到 aistack（Tier 2）已用的进程外 HTTP 模型。

被否决的替代：

- **继续打点补丁**（install 后 re-warm / 重启 sidecar / 每处 native 加 warmup 清单）：治标，不解管道/pip/spawn 那几类，留全局脆弱性。用户明确否决「当鸵鸟」。
- **保留 stdio，把读移到 worker 线程**：经最小复现确认无效 —— 触发是「阻塞 stdin 读」本身，在任何线程都炸，不是主线程特有。
- **WebSocket 代替 SSE**：通知是单向 server→client，SSE 够用且更简单，与 aistack 的 SSE 一致；请求/响应走普通 POST，不需要双向帧。

## 如何应用

改传输、加端点、动 sidecar 生命周期前先读本 ADR。不变量：

1. **dispatch 层 transport-agnostic**：handler 绝不碰传输；新端点/新传输只动 `server.py` 的 `build_app` + `sidecar.ts`。
2. **握手在 listening 之后打**（轮询 `server.started` 再 print），不在 `serve()` 前 —— 否则 client 撞「已 bind 未 listen」的 socket = `ECONNREFUSED`（踩过，TS 客户端 boot 即炸）。
3. **stdout 只承载 `VC_RPC_PORT` 一行**；一切日志/traceback 走 stderr。污染 stdout = 握手解析炸。
4. **emit→SSE 桥**：job 线程的 `emit` 经 `loop.call_soon_threadsafe` 投递到事件循环；hub **不缓冲** ⟹ 通知发出前订阅者须已注册（renderer 启动即长开 SSE，远早于任何 job；测试里靠 `: connected` / `sse-open` 信号同步）。
5. **请求处理串行**（`dispatch_lock`）保留旧单线程 stdio 循环的顺序保证 —— 63 个 handler 假设顺序访问共享 `Session`；HTTP 否则会让它们在 threadpool 并发。job 不受此锁约束，仍各自 daemon 线程并发（`JobRegistry` 不变）。
6. **`sidecar.ts` 公共 API 是契约**：`call`/`onNotification`/`dispose`/`SidecarError` 不变；动它必同步 `main.ts`/`preload.ts`/renderer。
7. **PyInstaller 必 `collect_submodules` uvicorn/fastapi/starlette**（uvicorn 按 dotted-string 动态 import protocol/loop/lifespan，静态分析抓不全）。
8. **warmup 去负重**：`core/ai/warmup.py` 降级为「首次 ASR 延迟优化」（后台线程，best-effort），不再是死锁修法；`runtime_extras.install` 成功后补 `importlib.invalidate_caches()`（runtime 装进 py-extra 后 `find_spec` 才看得到）。

### gotchas（别再踩）

- **`from __future__ import annotations` × FastAPI 闭包路由**：路由 handler 在 `build_app` 闭包内定义，但参数注解（`request: Request`）必须能从**模块全局**解析 —— 注解被 stringify，`get_type_hints` 看不到闭包局部 import。所以 `FastAPI`/`Request`/`JSONResponse`/`run_in_threadpool` 等名字在**模块顶层** import，不在 `build_app` 内。否则 FastAPI 把 `request` 误判成 query 字段 → 422。
- **`/shutdown` 设 `force_exit=True`**（不只 `should_exit`）：否则开着的 `/events` SSE 长连接会卡住 uvicorn 的 graceful-shutdown 连接等待。
- **`build_sidecar.ps1` 烟测改 HTTP**（起进程→读握手→`POST /rpc`→`/shutdown`）：旧版往 stdin 喂 JSON 现在会**永久挂** —— server 忽略 stdin、起 uvicorn 后长驻。
