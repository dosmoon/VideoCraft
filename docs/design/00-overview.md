# VideoCraft 设计总览

> 重写于 2026-06-10（v0.3.5）。Tk 时代的旧版总览及配套设计文档已移入 [`docs/_archive/`](../_archive/README.md)。
> 本文是 `docs/design/` 的入口路标：只概述当前形态 + 指路，决策正文在 [`docs/adr/`](../adr/README.md)，实现细节在各专题文档。

## 项目定位

面向内容创作者的**节目生成器**：从源视频（YouTube / 本地 / 录播）出发，经 ASR、翻译、AI 分析，生成多种节目形态的成片（AI 切片、新闻编导等，规划 5 种形态）。Windows-first 桌面应用，中英双语。

与并行产品线 Phase（通用 NLE 视频编辑器）互不替代。产品战略见 [08-product-strategy.md](08-product-strategy.md)。

---

## 当前架构（2026-06）

```
┌─ Electron 壳（desktop/）─────────────────────────────┐
│  main（desktop/electron/）   窗口 / 菜单 / vc:* IPC   │
│  renderer（desktop/src/）    全部 UI + 全部插件逻辑    │
│   ├─ hub / workbenches      项目浏览 + 创作工作台      │
│   ├─ composition            OTIO 式多轨 timeline IR    │
│   │                         + GPU 合成器 + WebCodecs   │
│   └─ creations / materials  纯 TS 插件（零插件专属 Py）│
└──────────────┬───────────────────────────────────────┘
               │ HTTP + SSE（localhost，握手 VC_RPC_PORT）
┌─ Python sidecar（core_rpc/ + src/core/）──────────────┐
│  plugin-agnostic 能力网关：ASR / 翻译 / AI 分析 /      │
│  源获取(yt-dlp) / ffmpeg 类任务 / 模型与环境管理       │
└───────────────────────────────────────────────────────┘
```

关键决策（详见对应 ADR，改架构层代码前先扫 [`docs/adr/`](../adr/README.md)）：

| 决策 | ADR |
|------|-----|
| 插件全 TS，Python = 能力网关，文件 I/O 归 Electron | [ADR-0008](../adr/0008-plugins-ts-python-capability-gateway.md) |
| sidecar 传输 = FastAPI HTTP + SSE（替代 stdio JSON-RPC） | [ADR-0010](../adr/0010-sidecar-http-transport.md) |
| composition = 统一多轨 timeline IR（OTIO 式，纯函数 compile） | [ADR-0006](../adr/0006-composition-timeline-ir.md) |
| 空间裁剪 = `Clip.crop` 一等字段（preview ≡ render） | [ADR-0011](../adr/0011-spatial-crop-clip-transform.md) |
| 项目数据 = materials/creations 组件化目录 | [ADR-0005](../adr/0005-componentized-data-layer.md) |
| 创作与素材解耦 + 快照原则 | [ADR-0003](../adr/0003-editor-modules-decoupling.md) + [快照原则](derivative-snapshot-principle.md) |
| Python 依赖管理 = uv（pyproject.toml + uv.lock 唯一权威） | [ADR-0009](../adr/0009-uv-project-dependency-management.md) |

渲染引擎与数据模型的设计正文：[composition-otio-foundation.md](composition-otio-foundation.md)；迁移期完整设计（含实现进度，纯历史背景）：[electron-migration-design.md](../_archive/electron-migration-design.md)（已归档）。

---

## 数据模型

- **项目 = 文件夹**，`.videocraft/project.json` 标识，任意文件夹可打开。见 [02-project-model.md](02-project-model.md)。
- **一项目 = 一源视频 + N 个创作**：素材（material，如 news_video）做数据准备；创作（creation，如 clip / news_desk）各自独立工作台。
- **快照原则**：创作建立时快照上游产物（字幕 / 章节 / hotclips），创作只对自己负责，不反向同步。
- 插件访问素材数据必须经 Material Model，不直戳路径 / schema。

## AI 三层

`core.ai` 统一门面（文本 LLM / ASR / TTS），三档 = 用户旅程三阶段，缺一不可：

1. **内置**：faster-whisper + edge-tts + llama.cpp（开箱即用，零配置）
2. **aistack**：独立本地网关服务（[github.com/dosmoon/aistack](https://github.com/dosmoon/aistack)，端口 11500，高性价比）
3. **云 API**：质量天花板

设计见 [04-ai-router.md](04-ai-router.md)；aistack 消费端笔记见 [aistack-integration.md](aistack-integration.md)。

## 打包 / 发布

electron-builder NSIS 安装包 + PyInstaller onedir 冻结 sidecar + 瘦装包引导下载；GitHub Actions CI 出包。
操作手册 = [`docs/packaging.md`](../packaging.md)，版本规则 = [`docs/versioning.md`](../versioning.md)，设计 = [packaging-design.md](packaging-design.md)。

---

## 核心设计原则

1. **Project = 文件夹**，自动生成 `.videocraft/project.json` 标识
2. **插件语言边界**：创作 / 素材插件 = 纯 TS；Python 只做 plugin-agnostic 能力，不认识任何插件类型
3. **preview ≡ render**：预览和导出走同一 composition 引擎，禁止两套绘制逻辑
4. **快照决策性上游**：创作自治，不被上游变化牵连
5. **增量演进 + 足够简单**，pre-alpha 不留兼容层、不做大爆炸重构
6. **中英双语热切换**：UI 字符串走 renderer 侧 `tr(key)`，zh/en 对称。见 [12-i18n.md](12-i18n.md)
7. **绿色便携**：所有用户数据落 `<repo>/user_data/`（打包态 = 安装目录内），绝不写 `%APPDATA%`
8. **任何下载 / 配置不强制**：AI 模型、云 key 强引导可跳过，非 AI 功能不被 AI gate 堵死

---

## 文件结构（顶层）

```
desktop/                  # Electron 应用
├── electron/             # main 进程 + preload（窗口/菜单/vc:* IPC/sidecar 拉起）
├── src/
│   ├── renderer/         # UI：hub / workbenches / aiconsole / models / settings / i18n / ipc
│   ├── composition/      # timeline IR + 组件库 + GPU 合成 + crop
│   ├── creations/        # 创作插件（clip / news_desk）+ 导出设置
│   └── materials/        # 素材插件（news_video）
├── electron-builder.yml  # 打包配置
└── dev.ps1               # 开发启动（renderer 改动必整重启）

core_rpc/                 # sidecar 服务端（FastAPI server / dispatch / jobs / methods）
src/
├── core/                 # 纯逻辑能力层：ai/ env/ models/ + asr/translate/字幕/视频 ops
├── i18n.py + i18n/       # Python 侧少量本地化（UI 主体字符串在 renderer）
└── project.py            # Project 模型 + recent.json

packaging/                # build_sidecar.ps1 / fetch_ffmpeg.ps1 / generate_build_info.ps1
.github/workflows/        # build-windows.yml（tag 触发出包 + 草稿 Release）
user_data/                # 用户数据（绿色便携，含 models/ keys/ settings/ 日志）
prompts/                  # prompt 模板
docs/                     # 本文档树；BACKLOG.md = 计划权威；docs/task.md = 当前任务接力
```

---

## 文档导航

| 文件 | 内容 | 状态 |
|------|------|------|
| [02-project-model.md](02-project-model.md) | Project 模型与 JSON 版本策略 | 现行 |
| [04-ai-router.md](04-ai-router.md) | AI 架构：core.ai 门面 + 路由 + AI 控制台 | 现行 |
| [06-core-layer.md](06-core-layer.md) | core 能力层：模块清单与约定 | 现行 |
| [08-product-strategy.md](08-product-strategy.md) | 产品战略与用户画像 | 现行 |
| [09-file-naming-convention.md](09-file-naming-convention.md) | 文件命名规范 | 现行 |
| [12-i18n.md](12-i18n.md) | 本地化（i18n） | 现行 |
| [aistack-integration.md](aistack-integration.md) | aistack 消费端集成笔记 | 现行 |
| [composition-otio-foundation.md](composition-otio-foundation.md) | composition 数据模型 + 渲染引擎 + AI 生成管线（地基正文） | 现行 |
| [derivative-snapshot-principle.md](derivative-snapshot-principle.md) | 派生层快照原则（横切约定） | 现行 |
| [packaging-design.md](packaging-design.md) | P3 打包 / 分发设计（§10 签名方案待证书） | 已实施 |
| [composition-timeline-v0.md](composition-timeline-v0.md) | ADR-0006 的详细设计参考 | 参考 |

Tk 时代旧文档（01-architecture / 03-ui-hub / 05-use-cases / 07-operations-registry / 10-media-format-modules / 11-hub-layout-persistence 等）见 [`docs/_archive/`](../_archive/README.md)。
