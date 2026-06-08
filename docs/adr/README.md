# 架构决策记录 (ADR)

本目录记录 VideoCraft 的架构级决策。改架构层代码（数据 schema、服务边界、核心数据流、跨模块契约）前，先扫一遍这里，确认不要违背已有决策。被 `Superseded` 标记的看取代它的新 ADR。

## 为什么有这个目录

之前架构决策散落在两处：

- `memory/` 下的 `project_*.md` —— 用 Claude Code 才能读，且绑死本机用户目录（`C:\Users\<user>\.claude\…`），换机就丢
- commit message + 设计文档（`docs/design/`）—— 设计文档讲"现在系统长什么样"，不讲"为什么不那么做、为什么从 A 改成 B"

ADR 补的就是后者：**决策的 why + 状态变迁**，跟代码一起入库，跟着 repo 走。

## 什么进 ADR、什么不进

进：

- 数据 schema 决议（envelope 结构、字段含义、向后兼容策略）
- 跨模块契约（哪一层负责什么、什么不该跨边界）
- 重大重构/退役（旧机制为什么退，新机制为什么这么设计）
- 反复被自己推翻、需要"钉死"的判断

不进：

- 个人偏好（注释用英文、commit 用英文）→ 留在 `memory/feedback_*.md`
- 当前任务进度 / 阶段性 TODO → `docs/task.md` 或 plan
- 实现细节 / API 文档 → `docs/design/`
- 单点 bug 修复 → commit message

## 格式（轻量版）

每份 ADR 顶部三段，**不强制** Nygard 四段式（Context / Decision / Consequences / Status）。简短能讲清就行：

```markdown
# ADR-XXXX: 标题

- **状态**: Active | Superseded by ADR-YYYY | Retired (YYYY-MM-DD)
- **决定日期**: YYYY-MM-DD

## 决定

一两句话说清"我们决定 X"。

## 为什么

讲清楚 trade-off、被否决的方案、触发这个决定的痛点。这是 ADR 的核心。

## 如何应用

具体到代码层面：谁该读这个、改什么的时候要先看这个、有哪些不变量。
```

## 命名

`NNNN-kebab-case-topic.md`，NNNN 从 0001 开始递增，**不复用**编号。

退役/被取代的 ADR **不删**，只改顶部状态字段。历史可追溯比目录干净更重要。

## 与 memory 的分工

memory 里对应的 `project_*.md` 改成**指针**，正文不重复：

```markdown
本决策已迁出 memory，详见 `docs/adr/0001-chapters-envelope.md`。
```

这样换机后 Claude 读 repo 能直接恢复架构上下文，memory 只剩用户偏好和当前任务。

## 现有 ADR

- [0001 - 章节 analysis.json envelope](0001-chapters-envelope.md)
- [0002 - 字幕单行不变量](0002-subtitle-oneline-invariant.md)
- [0003 - 派生作品全面解耦](0003-editor-modules-decoupling.md)
- [0004 - 三层架构（Base / Materials / Creations 插件化）](0004-three-tier-plugin-architecture.md)
- [0005 - Project 数据层全面插件化 + 组件化](0005-componentized-data-layer.md)
- [0006 - Composition Engine Timeline IR](0006-composition-timeline-ir.md)
- [0007 - 组件编辑 UI = 引擎独占的 FieldSpec 元数据](0007-component-edit-ui-metadata.md)
- [0008 - 插件逻辑入 TS;Python = 能力网关](0008-plugins-ts-python-capability-gateway.md)（supersede 0004 的 provider-dispatch 部分）
- [0009 - Python 依赖管理 = 正统 uv 项目（pyproject 单源 + uv.lock）](0009-uv-project-dependency-management.md)
- [0010 - Electron↔Python sidecar 传输 = FastAPI HTTP + SSE](0010-sidecar-http-transport.md)（supersede stdio JSON-RPC）
- [0011 - 空间裁剪 = per-clip `Clip.crop` 变换（退役 DrawDeps 旁路）](0011-spatial-crop-clip-transform.md)
