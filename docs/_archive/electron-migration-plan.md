# Electron 迁移规划（启动稿 / 交接）

> **本文是启动稿,不是完整迁移方案。** 目的:让新对话能直接接手,产出正式迁移计划。
> 写于 2026-05-29,承接一次长对话的架构讨论结论(那次会话同时修了一批 WebView 预览的 bug,见文末"触发背景")。

---

## 一、为什么迁移(结论)

- **痛点根源**:Tkinter 没有浏览器/视频组件,现在靠"把 WebView2 跨进程 `SetParent` 进 Tk frame"实现视频预览。这套 hack 三根支柱——`SetParent` 嵌入 + `AttachThreadInput` 合并输入 + stdin 管道通讯——每根都有反复出现、越来越难排查的 bug。
- **趋势**:VideoCraft 的视频组件会持续变丰富复杂,UI 是长期增长的投资。
  - ⚠️ **不是 timeline/逐帧编辑**——那是 **Phase** 的路线。VideoCraft 走"**用 UI 生成时间序列的视频组件**",composition 模块设计时就定清楚不做逐帧编辑。
- **结论**:UI 外壳迁到 web-native。**选 Electron**(MIT、扛长期复杂度、生态/工具链成熟)。

## 二、排除/降级的选项

- **Qt / PySide6 — 排除**:LGPL,会给 MIT 项目的分发附加 copyleft 义务(须允许重新链接 Qt 等),破坏许可洁净。
- **pywebview 整窗 — 降为备选**:BSD、留 Python、也能消除嵌入 hack;但做大型长期 app 不够成熟。只在"想最小改动"时考虑;长期复杂度押注下劣于 Electron。

## 三、目标架构

- **单进程 Python core 当后端**(IPC:stdio JSON-RPC 或 localhost WebSocket),是**唯一状态所有者**。
- **Electron 前端(React/TS)当 UI**,瘦客户端。
- **双 client 过渡**:过渡期 Tk 与 Electron 都是 core 的客户端;一个 Hub 按需 spawn Electron 窗口;最终 Electron Hub 接管、Tk 退役。
- **不要把 Electron 嵌进 Tk**(会重演今天的痛)。**迁移单位 = 整个窗口/工作台,不是子面板**(否则预览又得跨框架嵌入)。

## 四、引擎 / UI 分界(本会话代码探查结果,迁移底图)

**留 Python(引擎,几乎零 Tk,IPC-ready,不重写):**
- `materials/news_video/`: `model.py`(449) / `schema.py` / `paths.py` / `ai_fill.py` —— 边界最干净
- `creations/news_desk/`: `config.py` / `presets.py` / `components/` / `publish.py`
- `creations/clip/`: `config.py` / `presets.py` / `composer.py` / `candidates.py` / `render_queue.py`(回调边界干净) / `publish.py`
- `core/composition/`: **整层纯引擎,零 Tk**(`compile/timeline/render(880)/style/layout/fonts/text_layout/...`)
- `core/ai/`: `router.py` / `config.py` / `providers/*` / `tiers/stats/errors` —— **路由逻辑很薄(~300 行)**

**迁 Electron(UI 重写):**
- `materials/news_video/ui/*`、`sidebar.py`
- `creations/news_desk/news_desk_tool.py`(1179)
- `creations/clip/clip_tool.py`(1179) / `clip_editor.py` / `style_panel.py`(663)
- `tools/router/ai_console.py`(2045) / `prompt_console.py` / `voice_picker.py`
- **composition 预览层**:`preview.py`(只吐 JSON,不 import tkinter)+ `composition_preview.html`(canvas overlay)→ Electron 里是原生 renderer,复用视觉逻辑;`ui/web_preview.py` 的 SetParent hack **整体删除**

⚠️ **关键区分**:composition 的**渲染引擎(`render.py` + ffmpeg + libass)留后端**,Electron 不碰;只有**预览/overlay 层**迁过去。

**结论**:迁移工作量 ≈ 几乎全是"重写那 5 块 Tk UI 大块",引擎早已干净分离。不是重写视频引擎,是**给一个干净引擎换前端**。

## 五、需要拆缝的地方(不是干净边界)

- `news_desk_tool.py` / `clip_tool.py`:混着"组件 CRUD + 预览生命周期 + 渲染编排",迁移时把编排逻辑抽薄。
- `render_queue.py`:worker 线程 + `master.after()` 回调 → IPC 时换成"完成消息流"。

## 六、铁律

1. **先做 core/IPC 解耦**——不后悔的第一步,无论 Electron 进度如何都该做;保证整个迁移期间**状态只有一个家**(呼应 creation config single-owner 原则)。
2. **增量迁移,新旧并存,不大爆炸**(大爆炸式重写 = Electron 迁移翻车的唯一真因)。
3. 从**最痛、最 web-native 的一块**起步:**clip 工作台(含预览)做第一个 Electron 试点**,验证 IPC + 窗口协作链路。
4. **单一状态所有者**:core 单进程,两个 UI 都是瘦客户端。绝不让 Tk 和 Electron 各自跑一份 core(两个所有者 → 同步 bug)。

## 七、新对话要做的事(交付物)

1. **读资料对齐意图与边界**:
   - `docs/draft/project-restructure.md`、`architecture-vision.md`(看这轮重构的意图)
   - `docs/adr/0003`(派生解耦)、`0005`(组件化数据层)、`0006`(composition timeline IR)
   - `docs/design/01-architecture`、`06-core-layer`、`04-ai-router`、`02-project-model`
   - 确认"引擎/UI 边界是不是设计时就有意铺好的"(探查结果强烈暗示是)
2. **产出正式迁移方案**(放 `docs/draft/`,成熟后升级为 ADR):
   - core IPC 后端的**接口/协议设计**(能力清单:项目 / 材料 / 创作 / AI / 渲染 / 预览)
   - **状态所有权 + 事件广播**模型(谁改了,两个 UI 怎么同步)
   - Electron 工程骨架 + **与 Python sidecar 的打包方案**(PyInstaller / embedded python;ffmpeg / 模型 bundle)
   - **试点工作台(clip)** 的端到端切片计划
   - 迁移顺序 + 里程碑 + 回退点
3. **评估打包/分发体积**影响(Electron + Python + ffmpeg + 模型)。

## 八、范围红线

- core 业务逻辑**不重写**,只解耦 + 暴露 IPC。
- 此阶段**不做 timeline 编辑**(那是 Phase)。
- **不碰 aistack repo**(独立服务,自己的会话维护)。

---

## 触发背景(本会话修过的 WebView 预览 bug,作为迁移动机佐证)

这套 Tk+嵌入式 WebView 架构本会话连续踩了三类坑,都长在"跨进程裂缝"上:
- canvas 合成层 reparent 后不呈现(`--disable-accelerated-2d-canvas` 修)
- 改 clip range 重载整段视频(CJK 路径致 vid.src 永远不等,lastSrcUrl guard 修)
- 主线程同步写 stdin 管道,背压 + AttachThreadInput → 整 UI 死锁(消息队列 + writer 线程修)

功能越丰富,这道裂缝的失败模式越多——这正是迁移的核心动机。
