# Electron 迁移正式方案

> **状态**:草案 / 2026-05-29 · 承接 [`electron-migration-plan.md`](electron-migration-plan.md)(启动稿)
> **性质**:正式迁移方案。成熟后升级为 ADR(预定 ADR-0007),并正式 supersede [`docs/design/01-architecture.md`](../design/01-architecture.md) 的"单进程 + Tab 嵌入 / 无需 IPC"决策。
> **读者**:接手迁移实施的后续会话 / 作者本人。
> **前置**:已读 ADR-0003/0005/0006、design 01/02/04/06、architecture-vision.md、project-restructure.md(对齐结论见 §0)。

---

## 0. 对齐结论(代码探查 + 文档复核已完成)

启动稿断言"引擎/UI 边界是设计时就有意铺好的"。**复核结果:成立,且比启动稿描述的更彻底。**

| 证据 | 来源 | 含义 |
|---|---|---|
| `core/composition/` 全层 **零 tkinter import**(20 文件 grep 验证) | 实测 | 引擎是纯函数库,直接 IPC-ready |
| `core/ai/` **零 tkinter**;严格三层,UI 禁 import `core.ai` | 实测 + [04-ai-router](../design/04-ai-router.md) | AI 能力天然是后端服务 |
| `materials/*/{model,schema,paths,ai_fill}.py`、`creations/*/{config,presets,composer,candidates,render_queue,publish}.py` **全部零 tkinter** | 实测 | 业务层已与 UI 分离 |
| `CompileContext` 注释明写 "pure data — no UI callbacks" | [ADR-0006](../adr/0006-composition-timeline-ir.md) | 编译器/编辑器接口 = timeline IR,跨进程无障碍 |
| `MaterialInstanceModel.subscribe(callback)` 已存在(`model.py:394`) | 实测 | 变更广播机制已有骨架 |
| 创作 config 单一内存所有者 + 素材经 Material Model | [creation-config-owner] / [ADR-0005] | 单一状态所有者原则已是现行铁律 |

**唯一需要 supersede 的旧决策**:`01-architecture.md` 明确写"放弃 subprocess、无需 IPC、AI Router 进程内单例、多工具共享进程内全局状态"。本方案反转它——但反转的只是**外壳进程模型**,业务/引擎代码一行不重写。

> 一句话:**这不是重写视频引擎,是给一个早已干净分离的引擎换前端。** 迁移成本 ≈ 重写素材/创作模块 UI + 框架外壳 + 一层 IPC(遗留 menubar 工具不迁,见 §0.5)。

---

## 0.5 范围(2026-05-29 收窄)

VideoCraft = Tier1 框架 + **素材模块** + **创作模块** 两条插件轴(见 [[project_ir_nle_standard]] / ADR-0004)。**Electron 只建支撑这个结构运行的部分**;现有 menubar 那一长串遗留独立工具不迁。产品本体(素材/创作)走 **sidebar**,不在 menubar。

**建(框架服务 + 产品本体)**:
- 框架外壳:启动器 → with-project Hub → sidebar(素材 + 创作两栏)+ 预览 tab
- 素材模块运行:源准备、分析 kind 运行、context 编辑、sidebar 面板
- 创作模块运行:各创作工作台(clip / news_desk / 字幕烧录 / 未来录播自动剪辑)+ 预览/渲染
- 依赖的框架服务:项目管理(File)、AI 路由/key/统计(AI console,**去 Prompts tab**)、本地模型管理、preferences/about

**不迁(遗留 menubar,逐项)**:
- Download / Speech / Translate —— 能力**重归素材**(源获取 = source-prep;ASR/翻译 = 分析 kind 插件,产 SRT 物件),不做独立工具
- Video 全部 8 项(split / concat / extract_mp3 / volume / extract_clip / auto_split / bitrate / word_subtitle)—— 纯砍
- Text2Video 全部(tts / srt_from_text / audio_video / daily_news / composer)—— 砍;将来要则重表达为创作模块
- AI → prompt_console —— prompt hub 已弃([[refactor_architecture]] 横幅)
- Publish(tiktok / youtube)—— **暂不做,用时再说**
- voice_picker —— 仅当素材/创作的 TTS 流程用到才保留(框架组件),否则砍

**⚠️ 本文多处已被后续决策取代,数据模型 + 渲染引擎 + 进程拓扑一律以 [`composition-otio-foundation.md`](composition-otio-foundation.md) 为准**:
- **§4"渲染后端留 ffmpeg"作废** → 自建 GPU 合成器走 OTIO + libass-wasm,预览=导出同源;
- **§2.3 dual-client 已删** → 磁盘即真相源,任一时刻只一个 app;
- **§1 拓扑图里 Python sidecar 的 "Render"、§2.2 的 "Render 域 / Preview 域" 作废** → **composition(IR + 组件库 + compositor + 预览 + 渲染)整块在 TS renderer**;Python sidecar 只剩 **project / material / analysis / AI**(ffmpeg 降为 mux,从 main 进程调)。composition 重构 ≡ 建 Electron renderer。
- §1 "Renderer:composition 预览(复用 .html 视觉)" 作废 → 不是复用旧 .html 近似预览,是 TS 原生 compositor。

---

## 1. 目标架构

```
┌─────────────────────────────────────────────────────────────┐
│  Electron 主进程 (Node/TS)                                    │
│   - 窗口生命周期 / 菜单 / 文件对话框                          │
│   - spawn Python core sidecar,持有其 stdio                   │
│   - 把 renderer 的 IPC 调用转发给 sidecar,反向广播事件        │
└───────────────┬─────────────────────────────┬───────────────┘
                │ JSON-RPC over stdio          │ Electron contextBridge
                ▼                              ▼
┌──────────────────────────┐      ┌───────────────────────────┐
│  Python core sidecar      │      │  Renderer (React/TS)        │
│  ★ 唯一状态所有者          │      │  - Hub / 工作台 UI          │
│  - Project / Material /   │      │  - composition 预览(原生    │
│    Creation / AI / Render │      │    canvas,复用 .html 视觉)  │
│  - 已有 core/* 代码        │      │  - <video> 直读 file://     │
│  - 0 行业务重写            │      │    (媒体字节不过 IPC)        │
└──────────────────────────┘      └───────────────────────────┘
```

**结构性承诺**:

1. **媒体字节不过 IPC**。现状 `composition_preview.html` 的 `<video>` 已经直接 `file:///` 读源视频;Electron renderer 同理。IPC 只传**结构化数据**(timeline JSON、config、进度数字)。这消除了"大 payload 过管道"的性能顾虑,也是当前 stdin 管道死锁 bug 的根除(那个 bug 长在"主线程同步写大 payload 到子进程 stdin")。
2. **不把 Electron 嵌进 Tk,也不把 Tk 嵌进 Electron**。迁移单位 = **整个窗口/工作台**。子面板级混合嵌入会重演 SetParent 之痛。
3. **状态是文件型的,任一时刻只开一个 app**。VideoCraft 全部状态落盘(`project.json` / `config.json` / `materials/` / `creations/`),**磁盘即真相源**。Tk 和 Electron 不同时运行,因此不需要运行时同步/事件广播层(早期草案设想的"同时双客户端 + `event.*` 广播"已删,属过度设计)。

### 1.1 为什么这个进程边界不会重演现在的 bug

最该警惕的反问是:"现在的痛就是跨进程,Electron 又引入 Python sidecar 跨进程,不是搬家吗?" **不是——是换了一个 bug 类别。**

| | 现状(Tk + 嵌入 WebView2) | Electron + Python sidecar |
|---|---|---|
| 谁画窗口 | **两个 UI 工具包合成进一个窗口**(Tk frame 里 SetParent 一个 WebView2) | Chromium **一家**渲染整窗 |
| 痛的来源 | reparent 后 GPU canvas 不呈现、AttachThreadInput 抢输入焦点、闪屏、stdin 桥死锁 | 无——无 SetParent / 无 AttachThreadInput / 无合成 |
| 进程边界性质 | **UI 合成边界**(两套渲染要假装是一个窗口) | **纯数据边界**(Python 什么都不画,只回 JSON) |

现在的 bug 全长在"让两套异构 UI 表现得像一个窗口"这件事上。Electron 模型里 Python sidecar **不渲染任何东西**,IPC 只是 JSON 一问一答,和任何 client/server 同级。那一类合成 bug **被消灭,不是被搬家**——这是选 Electron 的核心理由。

---

## 2. IPC 协议设计

### 2.1 传输层选型:stdio JSON-RPC 2.0(推荐)

| 候选 | 取舍 |
|---|---|
| **stdio JSON-RPC 2.0** ✅ | Electron 主进程 spawn python child,天然持有 stdin/stdout。单一双工通道,request/response + notification(服务端推送)都覆盖。无端口、无防火墙弹窗、无端口冲突。**推荐。** |
| localhost WebSocket | 也能推送,但要选端口、处理占用冲突、本机防火墙可能弹窗;多一层 socket 生命周期管理。仅在未来需要"core 服务多个外部客户端"时才值得。本期不需要。 |

**协议形态**:JSON-RPC 2.0。
- `request`(有 id):客户端发起的有返回值调用,如 `project.list_materials`。
- `notification`(无 id,服务端→客户端):事件广播 + 长任务进度,如 `event.material.changed`、`progress.render`。
- 长任务(ASR / 渲染 / AI 调用)走 **"立即返回 job_id + 后续 progress 通知 + 终态通知"** 模式,不阻塞通道。

> ⚠️ 当前 stdin 死锁的教训直接转化为协议约束:**写管道必须 off-thread + 消息队列**(已在 Tk 侧用 writer 线程修过,见 commit `392980e`)。Electron 主进程的 stdio 写默认异步,问题自然消失;但 Python sidecar 的读写循环要单独的 reader/writer 线程,不在请求处理线程里直接 write。

### 2.2 能力清单(RPC 方法面)

按域组织。**每个方法都映射到已存在的 core API**——这张表同时是"迁移时哪些代码被 IPC 包一层"的清单。

#### Project 域(映射 `src/project.py` + `Project` 类)
| RPC | 映射 | 类型 |
|---|---|---|
| `project.recent_list` | `recent.json` 读 | 同步 |
| `project.create(source, name, parent_dir)` | 新建项目 + 源准备 | **长任务**(下载/拷贝有进度) |
| `project.open(folder)` / `project.close` | Project 加载 | 同步 |
| `project.list_material_types` / `list_material_instances` | `Project.list_material_*` | 同步 |
| `project.create_material_instance(type, name)` | 同名方法 | 同步 |
| `project.list_creations(type)` / `create_creation_instance` | creation ops | 同步 |

#### Material 域(映射 `MaterialInstanceModel` 协议 + `NewsVideoModel`)
| RPC | 映射 | 类型 |
|---|---|---|
| `material.slot_readiness(type, inst)` | `model.slot_readiness()` | 同步 |
| `material.get_artifact(type, inst, key)` | `model.get_artifact()` → 返回**路径字符串**(renderer 直读) | 同步 |
| `material.add_source_video(...)` | `NewsVideoModel.add_source_video` | **长任务** |
| `material.generate_subtitles(...)` | ASR 流程 | **长任务**(进度 + 可取消) |
| `material.ai_fill_context(...)` | `model.ai_fill_context(progress_cb, cancel_token)` | **长任务** |
| (事件) `event.material.changed{type,inst}` | `model.subscribe()` 回调转广播 | notification |

> `subscribe(callback)` 已存在——迁移时把回调实现改成"向所有 IPC 客户端 emit `event.material.changed`"即可,Model 内部零改动。

#### Creation 域(映射 `creations/*/config.py` 单一所有者 dataclass)
| RPC | 映射 | 类型 |
|---|---|---|
| `creation.load_config(type, inst)` | config dataclass 加载 | 同步 |
| `creation.update_config(type, inst, patch)` | 单一所有者写 + 广播 | 同步 + 事件 |
| `creation.bind_material(type, inst, material_ref)` | `bound_material` + 快照(ADR-0003/0005) | **可能长任务**(快照拷字幕) |
| `creation.list_components` / `add` / `remove` / `update_component` | 组件 CRUD | 同步 + 事件 |
| (事件) `event.creation.changed{type,inst}` | config 变更广播 | notification |

#### AI 域(映射 `core.ai` facade,**沿用现有 facade,不重写**)
| RPC | 映射 | 类型 |
|---|---|---|
| `ai.complete` / `complete_json` | facade | **长任务**(可取消) |
| `ai.describe(task,tier)` / `list_models(provider)` | facade | 同步 / 长任务 |
| `ai.get_routing` / `set_task_routing` | `router.set_task_routing()` | 同步 |
| `ai.list_providers` / `update_provider` / `test_provider` | router 配置 | 同步 / 长任务 |
| (事件) `event.ai.stats` | `stats.py` 计数变更 | notification(节流) |

> AI 域是最干净的——`core.ai` 本就是"UI 不许碰"的基础设施层,IPC 化等于把 facade 的函数签名直接转成 RPC schema。

#### Render 域(映射 `render_composition` + `render_queue.py`)
| RPC | 映射 | 类型 |
|---|---|---|
| `render.start(request_or_batch)` → `job_id` | `RenderQueue.start(jobs)` 逻辑搬后端 | **长任务** |
| `render.cancel(job_id)` | `RenderQueue.cancel()` | 同步 |
| (事件) `progress.render{job_id,done,total,out_idx,pct}` | `on_progress` 回调 → 通知 | notification |
| (事件) `event.render.job{job_id, out_idx, status, error?}` | `on_succeeded`/`on_failed`/`on_all_done` | notification |

> `render_queue.py` 的回调契约(`on_progress/on_succeeded/on_failed/on_all_done`)**原样保留**;唯一改动是 `_post` 从 `master.after(0,...)`(Tk marshal)换成"emit notification"。`render_composition(req, on_progress, cancel_check)` 一字不改。

#### Preview 域(映射 `compile_timeline` + `preview.py` 的 JSON 翻译)
| RPC | 映射 | 类型 |
|---|---|---|
| `preview.compile(type, inst, clip_range)` → timeline payload | `compile_timeline()` + `preview.set_timeline` 内的 JSON 翻译逻辑 | 同步 |
| (renderer 本地) `<video>` 直读源 + canvas 画 overlay | 复用 `composition_preview.html` 视觉逻辑,移植成 React 组件 | 不过 IPC |

> **关键**:`preview.set_timeline()` 现在做的事 = 把 timeline IR 翻译成 `setOverlays/setCues/setExtraWatermarks/setClipMeta` 一串 JS 调用。迁移时:**JSON 翻译逻辑留 Python**(它依赖 `wrap_subtitle_elements` / `wrap_hook_outro` 等引擎纯函数,绝不能在 JS 重抄——见 ADR-0006 不变量 #6);**翻译结果(payload)经 `preview.compile` RPC 一次性返回给 renderer**;renderer 的 canvas 消费这些 payload。`web_preview.py` / `web_preview_host.py` 的 SetParent + AttachThreadInput + stdin 桥 **整体删除**。

### 2.3 状态所有权:磁盘即真相源(单 app 运行)

**不引入运行时同步/广播层。** VideoCraft 状态全部落盘,任一时刻只运行一个 app(Tk 或 Electron,见 §1 承诺 3)。因此:

```
   单个 app 进程内:
   ┌──────────────────────────────────────────┐
   │  Electron renderer  ──RPC──▶  core sidecar │
   │      (瘦客户端)              ★ 内存所有者    │
   │                              - Project       │
   │                              - Material Model │
   │                              - Creation config│
   │                              ▼ 写盘            │
   │                          project/config.json  │ ← 真相源
   └──────────────────────────────────────────┘
```

**规则**:
1. **一个 app 内**:renderer 是瘦客户端,所有写走 RPC 进 core;core 是该进程内的单一内存所有者(沿用 [creation-config-owner] 现行铁律),写成功后落盘。
2. **app 内的视图刷新**仍可用轻量 `event.*` notification(如长任务进度、`event.creation.changed` 让同窗口多个面板同步)——这是**进程内 UI 刷新**,不是跨 app 同步。
3. **过渡期 Tk 与 Electron 不并发**:用户开哪个就用哪个,关掉再开另一个时从磁盘重新加载。无需任何跨进程状态协调——这正是省掉双倍工作量的关键(见 §5 决策记录)。
4. 事件粒度 = 实例级(`{type, instance}`);不做字段级 diff(YAGNI)。

---

## 3. Electron 工程骨架 + Python sidecar 打包

### 3.1 工程结构(新增,不动 `src/`)

```
<repo>/
├── src/                      # 现有 Python(core 引擎 + 过渡期 Tk UI)
├── desktop/                  # 新增:Electron 前端
│   ├── package.json
│   ├── electron/
│   │   ├── main.ts           # 主进程:spawn sidecar、窗口、菜单
│   │   ├── preload.ts        # contextBridge 暴露 ipc.call/ipc.on
│   │   └── sidecar.ts        # 管理 python child + JSON-RPC 收发
│   ├── src/                  # React renderer
│   │   ├── hub/              # Hub 外壳 + sidebar + tab 区
│   │   ├── workbenches/
│   │   │   └── clip/         # ★ 首个试点
│   │   ├── preview/          # composition canvas(移植自 .html)
│   │   └── ipc/              # 类型化 RPC client(对应 §2.2 能力清单)
│   └── vite.config.ts
└── core_rpc/                 # 新增:Python sidecar 入口
    └── server.py             # JSON-RPC dispatch → 调 src/core/* 与业务层
```

`core_rpc/server.py` 是**薄 dispatch 层**:读 stdin JSON-RPC → 查方法表 → 调已有 core/业务函数 → 写 stdout。长任务包一个 job 注册表 + 进度回调转 notification。**它不含业务逻辑。**

### 3.2 打包方案

| 组件 | 方案 |
|---|---|
| Python sidecar | **PyInstaller onedir**(非 onefile,避免每次启动解压到 temp)。打进 Electron `resources/`。用现有 `myenv/`(uv 管理)冻结依赖。 |
| Electron app | electron-builder,产 Windows 安装包 / 便携包。Windows-first(对齐 architecture-vision §3:跨平台延后)。 |
| ffmpeg / ffprobe | bundle 进 resources(现已经是外部组件,`core/env` 检测)。 |
| libass / 字体 | libass 随 ffmpeg;字体走系统 `C:/Windows/Fonts`(现状,见第一轮 dogfood commit `9dce838`)。 |
| AI 模型 / Node runtime | **不 bundle**,运行时按需下载到 `user_data/`(铁律:[no-forced-downloads] + [portable-data])。 |
| 用户数据 | 全部 `<repo or install>/user_data/`,绝不写 %APPDATA%([portable-data])。 |

### 3.3 体积评估(粗估)

| 项 | 体积 |
|---|---|
| Electron runtime | ~80–120 MB |
| Python(PyInstaller onedir,含 numpy/Pillow/ASR 客户端等) | ~150–300 MB(取决于是否含 faster-whisper 等重依赖;若内嵌 AI 重依赖延后下载可压到 ~120 MB) |
| ffmpeg + ffprobe | ~80–120 MB |
| **基线安装包(不含模型)** | **~300–500 MB** |
| 模型(可选,运行时下载) | faster-whisper / Qwen 各数百 MB ~ 数 GB,落 user_data |

对比现状(Python + Tk + WebView2 复用系统 Edge):Electron 多扛 ~100 MB runtime + ~150 MB python 冻结。对一个本就要 bundle ffmpeg + 按需下载 GB 级模型的工具,这个增量可接受。**WebView2 依赖消失**(不再需要系统 Edge runtime),反而少一个外部前置。

---

## 4. 试点工作台:clip 端到端切片计划

选 clip 作首个 Electron 工作台(启动稿铁律 3:最痛、最 web-native、含预览,验证 IPC + 预览 + 渲染全链路)。

**clip 涉及的 RPC 子集**(验证面足够全):
- Project/Material:`get_artifact`(取字幕/源)、`bind_material`
- Creation:`load_config` / `update_component`(样式 tab)/ `list_components`
- Preview:`preview.compile` → canvas(crop 拖拽 = renderer 本地交互 + `event` 回 config)
- Render:`render.start` 批量切片 + `progress.render` + `event.render.job`(验证长任务 + 取消)
- AI:候选 tab 若调 hotclips,走 `ai.complete_json`

**端到端切片(每片可独立验证、Tk 仍可跑)**:

| 切片 | 内容 | 验证标志 |
|---|---|---|
| **E0** | `core_rpc/server.py` 骨架 + stdio JSON-RPC 收发 + reader/writer 线程 + 1 个 echo 方法 | Electron spawn sidecar,echo 往返通 |
| **E1** | Project/Material 只读 RPC(recent/open/list/get_artifact)+ Electron Hub 外壳 + sidebar 列表(只读) | Electron 能开项目、列素材/创作,数据来自 core |
| **E2** | Preview 域:`preview.compile` + canvas 组件移植(`composition_preview.html` 视觉逻辑 → React)+ `<video>` file:// 直读 | clip 预览在 Electron 里出画面,布局与 Tk 一致(肉眼对) |
| **E3** | Creation 域:样式 tab 双向绑定(`update_component` + `event.creation.changed` 回灌预览) | 改样式 → 预览实时变;关掉再开状态持久 |
| **E4** | Render 域:批量切片 `render.start` + 进度流 + 取消 + 终态 | Electron 里跑通导出,产物与 Tk 路径 byte 等价 |
| **E5** | 闭环:用 Electron clip 跑完"开项目→选素材→调样式→预览→导出",关掉重开状态从磁盘恢复 | clip 工作台在 Electron 里**独立可用**,体验无闪屏/卡顿 |

E5 通过 = **IPC + 预览 canvas + 渲染长任务 + 磁盘真相源全部验证**,可放心铺第二个工作台。(无需"双客户端同时跑"验证——§2.3 已决定不做并发。)

---

## 5. 迁移顺序 / 里程碑 / 回退点

```
M0  core/IPC 解耦(无悔第一步,与 Electron 进度无关)
     ├── core_rpc/server.py + JSON-RPC + job 注册表
     ├── 把 render_queue 的 _post、material 的 subscribe 回调
     │   抽象成"emit"接口(Tk 侧暂时仍 master.after 实现)
     └── 写一批 RPC 契约测试(server 侧,不依赖任何 UI)
     ★ 回退点:M0 即使 Electron 永不做也独立有价值——状态只有一个家。

M1  Electron 骨架 + clip 试点(§4 的 E0~E5)
     ★ 回退点:Electron clip 不达标 → 停在此,Tk 继续主用,无损失。

M2  第二、三个工作台迁 Electron(news_desk → ai_console)
     按 clip 验证过的模式复制,新旧并存。

M3  Material sidebar + Hub 主壳全量迁 Electron;新建项目/派生对话框迁过去
     Electron Hub 能独立 spawn 工作台窗口(启动稿:Hub 按需 spawn)。

M4  Tk 退役:删 src/ui/web_preview*.py、video_preview_pane.py、
     composition_preview.html 的 Tk 宿主、所有 Tk UI 模块。
     core + core_rpc + desktop 成为唯一形态。
     ★ supersede 01-architecture.md → 写 ADR-0007。
```

**铁律落实**(启动稿 §六):
1. ✅ M0 先做 core/IPC 解耦,无悔第一步。
2. ✅ 增量,新旧并存(M1~M3 双客户端共存),无大爆炸。
3. ✅ clip 第一个试点(M1)。
4. ✅ 单一所有者贯穿(§2.3),core 单进程。

**每个 M 的回退成本**:M0 纯增量;M1~M3 期间 Tk 始终可独立跑(in-process,零改动);只有 M4 删 Tk 是不可逆的,且只在 Electron 全量验证后执行。

### 5.1 功能冻结的真实范围(澄清成本)

迁移期的"冻结"**只冻 Tk-UI 侧功能**,不是冻结整个产品:

- **照常推进**:`architecture-vision.md` roadmap 的主体——composition v0.2(karaoke / smart-crop / hook 卡模板)、AI router 增强、plugin 化、prompt 工程——**几乎全是引擎/后端活**(`core/composition`、`core/ai`、`core/prompts`),不在 UI 层。引擎被 Tk 和 Electron **共用**,迁移期照常做,两个前端都受益。
- **冻结**:已开始迁移的那个工作台,不再往 Tk 版加新交互(避免给"将要删的代码"投资)。未迁的工作台仍可改。
- **结论**:没有"python 功能写两遍"。真实增量 = `Electron UI(任何迁移躲不掉)+ 薄 IPC dispatch(core_rpc)+ 一个小回调抽象(render/ASR 进度从 master.after 改成可 emit)`。core 业务/引擎代码零重写。

### 5.2 决策记录(2026-05-29 会话)

- 否决"继续堆 Tk"(A):预览的卡顿/闪屏/异构 bug 是 **Tk 托不住 web/视频表面**的结构性问题,堆功能只增技术债。
- 否决"只换预览机制"(B):预览嵌在工作台内,Tk 无原生浏览器组件 → 富预览必须把异构窗口合成进 Tk → 换汤不换药。
- 采纳"便宜版 Electron 全迁"(C):砍同时双客户端、磁盘做真相源、只冻 Tk-UI、引擎主线继续。

---

## 6. 范围红线(承自启动稿 §八)

- ❌ core 业务逻辑**不重写**,只 IPC 包一层。
- ❌ 不做 timeline 逐帧编辑(那是 Phase)。
- ❌ 不碰 aistack repo。
- ❌ 不做跨平台(Windows-first)。
- ❌ 预览的渲染前数据变换(wrap 等)**绝不在 JS/renderer 重抄**——必须经 `preview.compile` 由 Python 引擎纯函数算好(ADR-0006 不变量 #6,违反 = preview≠render 静默分裂)。

---

## 7. 待决问题(实施前确认)

1. **renderer 技术栈**:React + TS(假设)。是否引 UI 组件库(如 Radix / shadcn)还是裸 CSS?——影响 §3.3 体积与开发速度。
2. **canvas 移植粒度**:`composition_preview.html` 的 canvas 逻辑直接移植成一个大 React 组件,还是借机重构?——倾向"先 1:1 移植保证 preview≡render,再谈重构"。
3. **PyInstaller vs 嵌入式 Python**:onedir PyInstaller(推荐)vs 直接 bundle 一个 embeddable python + myenv。前者更省心,后者更透明。
4. **i18n**:现有 `src/i18n/{zh,en}.json` 806 key 是 Tk 侧的;Electron renderer 需要自己的 i18n 方案(如 i18next),key 可复用 JSON 但加载机制不同。
