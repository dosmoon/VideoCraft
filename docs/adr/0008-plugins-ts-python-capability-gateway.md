# ADR-0008: 插件逻辑入 TS;Python = 能力网关

- **状态**: Active
- **决定日期**: 2026-06-01

> 实施细节(跨阶段地基 C1–C7、Phase A/B 分步、Cutover、风险、必读文件)在
> [`docs/draft/electron-migration-design.md`](../draft/electron-migration-design.md)
> 顶部「🚩 架构转向」节。本 ADR 只钉决策的 why + 边界 + 不变量。

## 决定

三个迁移本体——**clip / news_desk 创作 + news_video 素材**——收敛为**纯 Electron/TypeScript 插件,零插件专属 Python**。Python 退成**plugin-agnostic 的能力网关**:只暴露按文件路径+参数调用的通用 job(ASR / 翻译 / 分析 / AI 填充 / 源获取 / ffmpeg probe / 字幕质检 / 章节保存),**不再认识 clip/news_desk/news_video 是什么**。

配套两条边界:
- **文件 I/O 归 Electron 主进程**(Node fs,`window.vc.fs.*`,扩展自 `vc:writeFile`)。所有项目/实例/数据文件(config.json / presets / context.json / SRT 快照 / analysis.json / 渲染 mp4)由 renderer 经主进程读写;Python 只在能力 job 内部碰文件。
- **创作/素材的单一内存所有者移到 renderer(TS)**,经主进程 fs 独写落盘;Python 不再持创作/素材内存态。

分阶段落地:Phase A 创作先,Phase B 素材后;**前提 = Tk 退役完成**(clip Tk 仍依赖 `creations/clip/config.py`)。

## 为什么

迁移期为了快速接通,创作/素材都落成了**双语插件**——每个横跨 TS renderer(≈1900 行/插件) 和 Python sidecar(per-plugin 业务面 ≈1200 行/插件),经 ADR-0004 的 provider dispatch 桥接。读懂或改一个插件要在两种语言、两个进程间来回跳。**长期看,跨 Python+TS 的功能模块不可维护**——这是触发本决策的痛点(2026-06-01)。

为什么可行(而非空想):代码探查(3 路 Explore + 1 路 Plan)证实 per-plugin 的 Python **几乎全是纯 JSON/dict/markdown 逻辑、零重依赖**(config 所有者 / presets / component_defs / preview / export / import / publish);TS 侧**已有 ~85% 目标**(mapping / assemble / 组件库含默认值 / fieldSpec / 工作台 UI)。插件里**唯一**真正绑 Python 的是**能力**(faster-whisper / LLM / yt-dlp / ffmpeg)——这些无 JS 等价物,且与现有 aistack 服务一致,理应作为通用网关保留,而非塞进每个插件。

被否决的替代:
- **字面零 Python**(连 ASR/LLM 也重写 Node)——不可行,无等价库。
- **维持双语 provider 模式**(ADR-0004 原样)——正是要消除的不可维护源。
- **把文件 I/O 也留在 Python 通用持久层**——可行,但 renderer 已用 `vc-media://`/`vc:writeFile` 直接做数据文件 I/O,把 config/数据文件也归主进程 fs 更彻底地让 Python 退出数据路径;选了它。

## 如何应用

改创作/素材/插件边界相关代码前先读本 ADR + 设计文档「架构转向」节。不变量:

1. **Python 零插件名**:能力网关方法签名只收路径+参数(`asr(videoPath, outSrtPath, lang)`),不收 `(type, instance)`,不 import `creations.*`/`materials.*`。框架仅保留目录生命周期(`project.{list,create,rename,delete}_instance`)。
2. **单一所有者在 renderer**:每个 creation/material 实例的内存所有者唯一、住 renderer、写串行化;经 `vc.fs.writeJson`(原子 `.tmp`+rename、`newline:"\n"`、indent 2,复刻 Python `*.save()` 以保 golden)落盘。沿用 [[project_creation_config_owner]] 的"单一 writer"精神,只是换进程。
3. **路径安全**:`assertInProject(absPath)` 是主进程 fs 的安全边界——只放行 当前项目根 + `<userData>/presets`,拒 `..`/盘符逃逸;项目根从代理的 `project.open/close` 嗅探。
4. **快照仍是拷贝非引用**(ADR-0003 不变):copy-once 动作移到 TS,用 `vc.fs.stat` 守;"上游变更不影响已快照实例"必须有测。
5. **每步 build-green**:TS 替代 wire + 测好之前,绝不删对应 Python 方法;`vc-media://` 全程不动,`vc.fs.*` 是增量。

## 取代关系

- **supersede ADR-0004 的 provider-dispatch 部分**(`CreationType.{config_owner_cls,preview/render/import_provider}`、`core_rpc` 的 creation/material 域泛型派发)。ADR-0004 的"框架 / Materials / Creations 三层 + 零硬编码插件名"原则**仍 Active**——本决策反而强化它(Python 框架层更纯)。
- **supersede** `docs/design/01-architecture.md` 的"单进程 + Tab 嵌入 / 无需 IPC"。
- **不影响** ADR-0006(Composition Timeline IR = 数据模型,继续权威)、ADR-0003(快照)、ADR-0005(组件化数据层)、ADR-0007(组件编辑 UI = FieldSpec)。
