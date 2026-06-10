# docs/_archive — 历史文档归档

> 这里的文档**只读不更新**：记录的是写作当时的事实，与当前架构（Electron 壳 + FastAPI sidecar + OTIO composition，见 [`docs/design/00-overview.md`](../design/00-overview.md)）可能严重不符。
> 需要当前事实去 `docs/design/`、`docs/adr/`、`docs/draft/` 里的现行文档；ADR 不归档到这里（退役 ADR 留在 `docs/adr/` 改状态，见 [`adr/README.md`](../adr/README.md)）。

## 会话记录分卷（task.md 拆出）

| 文件 | 范围 |
|------|------|
| [task-archive-01](task-archive-01_2026-05-19_2026-06-05.md) | FastAPI 传输重构、P3 打包/Tk 退役、OTIO/Electron 迁移史（续 6~37） |
| [task-archive-02](task-archive-02_2026-06-05_2026-06-08.md) | 三轮 dogfood（source 崩 / 60fps 死锁 / clip·news_desk 修复） |
| [task-archive-03](task-archive-03_2026-06-08_2026-06-09.md) | i18n 孤儿清扫 / env-screen / crop-on-Clip 重构（ADR-0011） |

## Tk 时代设计文档（2026-06-10 自 docs/design/ 移入）

整篇描述已退役的 Tkinter 单进程架构（`src/ui`、`src/tools`、Tk Hub 均已删除）：

| 文件 | 原主题 | 现行替代 |
|------|--------|----------|
| [01-architecture.md](01-architecture.md) | 单进程 + Tk Tab 嵌入 / 无需 IPC | ADR-0008 / ADR-0010 + [design/00-overview](../design/00-overview.md) |
| [03-ui-hub.md](03-ui-hub.md) | Tk Hub（PanedWindow + Notebook + ToolFrame） | Electron renderer hub / workbenches |
| [05-use-cases.md](05-use-cases.md) | Tk 时代用例集（Toplevel 工具流） | — |
| [07-operations-registry.md](07-operations-registry.md) | 文件类型 → 右键操作注册表（`operations.py`，已删） | — |
| [10-media-format-modules.md](10-media-format-modules.md) | text2video 系列 Tk 工具（DailyNews 等，已删） | 节目形态 = 创作插件（ADR-0004/0008） |
| [11-hub-layout-persistence.md](11-hub-layout-persistence.md) | Tk 窗口 geometry/sash 持久化 | Electron 窗口状态自管 |

## 已落地 / 已被取代的设计草稿（2026-06-10 自 docs/draft/ 移入）

| 文件 | 性质 | 归档原因 |
|------|------|----------|
| [electron-migration-plan.md](electron-migration-plan.md) | 迁移启动稿 | 被 [electron-migration-design.md](electron-migration-design.md) 取代 |
| [electron-migration-design.md](electron-migration-design.md) | Electron 迁移正式方案 + 实现进度日志 | 迁移已完成（2026-06）；架构正文由 ADR-0008/0010 + [design/00-overview](../design/00-overview.md) 承载；迁移期实现细节/坑的考古入口 |
| [adr-0008-migration-tasks.md](adr-0008-migration-tasks.md) | 迁移勾选清单 | 迁移已完成（Phase A6/B5 交付） |
| [project-restructure.md](project-restructure.md) | 项目模型重塑设计 | 已全量落地（source/素材/创作目录 = 现状） |
| [clip-component-migration.md](clip-component-migration.md) | clip component 化方案 | 已落地；clip 其后又整体迁 TS |
| [ai-clip-redesign.md](ai-clip-redesign.md) | AI 切片重构设计（P1~P4） | 已落地于 Tk 时代；clip 现为 TS 插件 |
| [composition-style.md](composition-style.md) | Python CompositionStyle 渲染设计 | 引擎已重写为 TS composition（ADR-0006/0011 + [design/composition-otio-foundation.md](../design/composition-otio-foundation.md)） |
| [architecture-vision.md](architecture-vision.md) | 2026-05 下一阶段愿景 | 路线已走完/转向 Electron；5 形态规划见 design/00 + 08 |
| [news-desk-derivative.md](news-desk-derivative.md) | news_desk v0.1 设计 | 已落地并迁新架构（2026-05-31） |
| [news_desk-ux-v0.3.md](news_desk-ux-v0.3.md) | news_desk UX v0.3 | 已落地 |
| [publish-sidecar.md](publish-sidecar.md) | per-derivative publish.md 出口 | per-plugin Python（tools/<x>/publish.py）已随 ADR-0008 退役；`core/markdown_fmt.py` 仍在 |
| [chapter-verify-edit.md](chapter-verify-edit.md) | 章节验真编辑 Plan（Tk Hub preview tab） | 未实施且绑死 Tk 交互；功能若重启需按 Electron 重设计 |
| [substrate-spike-findings.md](substrate-spike-findings.md) | GPU 合成器 spike 发现录 | spike 结论已固化进迁移设计 / ADR；WebCodecs 编码上限等结论仍可查 |
| [tech-selection-embedded-ai.md](tech-selection-embedded-ai.md) | 内嵌 AI 选型 | 已落地（faster-whisper/llama.cpp/edge-tts）；sherpa 部分被推翻，见 `research-notes/sherpa-detour.md` |
| [aistack-sse-asr-issue.md](aistack-sse-asr-issue.md) | aistack SSE 提案（原 draft/archive/） | 上游已独立实现，客户端已适配 |
| [program-script-clip.md](program-script-clip.md) | 旧 AI 切片设计（原 draft/archive/） | 被 ai-clip-redesign 取代，相关代码已清 |
