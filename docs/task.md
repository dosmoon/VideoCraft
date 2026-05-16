# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## news_desk dogfood 第二轮 — 已收尾

HEAD: `983e11f` (已 push origin/main)，workspace clean。

这轮从 chapter_editor 修 bug 开始，一路走到导出全链路重塑，落了一个**架构级 ADR**。

### 本次会话的 commit 串

| commit | 内容 |
|---|---|
| `9e5a547` | 修 sidebar「新闻背景 (AI)」5/5 误显示（用 read_context 而非 combined_dict） |
| `0513206` | chapter_editor 加可编辑详情 + 拆分语义新增章节 + 双击起点列 |
| `ff56ccf` | chapter_editor 字段编辑全收进底部详情面板 |
| `eacc1e9` | chapter_editor 用 focus_force 治 WebView2 焦点 |
| `ed613ad` | chapter_editor 接入 core.composition.CompositionPreview（不再自造 video HTML） |
| `ae9ef1b` | composition.preview 默认 = 最小行为（[[feedback_minimal_defaults]]） |
| `8a104c5` | chapter_editor 用 ffprobe 真实尺寸算字幕 wrap budget |
| `509cd10` | chapter_editor 字幕字号调小 + 加 stroke + Spinbox |
| `bca3c8f` | news_desk/chapter import 用 clear+extend 不替换 list 对象 |
| `85e69dd` | composition.preview 画图层顺序对齐 burn z_order |
| `2340ba2` | news_desk 列表 UI 顺序真正驱动 render z-order，端到端 |
| `c99c4aa` | news_desk 导出 bundle 初版（publish/transcript/chapters_md/chapter_videos 4 勾） |
| `b8968b1` | 导出对话框加字幕语言下拉 |
| `4957b39` | **ADR-0003 派生作品全面解耦** |
| `43b72d6` | **Phase 1**: subtitle 组件改快照模式 + 导出全部从 instance 派生 |
| `02c798a` | "snapshot" 字面去 jargon |
| `983e11f` | candidate titles 一起从 chapter 快照 + publish.md 第一个 section |

### 关键架构变更

- **[[ADR-0003]]**：派生作品全面解耦——源层 = 数据准备工坊，派生层 = N 个独立编辑器
- **subtitle 组件**：路径引用 → 本地快照（`<instance_dir>/subtitles/<id>.srt`）。Phase 2/3（cue 编辑、增删）没做，独立 session
- **chapter 组件** import 现在一次同时快照 `schedule` + `titles`（同源 analysis.json）
- **导出对话框**：3 勾选项（publish/transcript/chapter_videos），全部从 instance 状态派生
- **publish.md**：候选标题首屏 + 章节详情（refined + key_points + 文字稿）合并成一个文件

### 学到的元规则（已存为 memory）

- [[feedback_minimal_defaults]] — 共享模块默认 = 最小行为；看见多个消费者 opt-out 就是默认选错的信号

---

## 下一手 — 已选定：sidebar 三栏拆分

**践行 [[ADR-0003]] 的可视化对齐**：左边栏拆成 3 个 tab，对应数据层 vs 编辑器层 vs 文件层。

```
┌─[资源]─[项目]─[文件]─┐
│                       │
└───────────────────────┘
```

### 三栏内容定义

1. **资源 (Resources)** — 以源视频为根的"梳状 AI 分析数据树"
   - 当前 sidebar 里这些归这里：源视频卡 / 新闻背景(AI) / 字幕列表（含 +生成 menu）/ 标题与章节子节点
   - 本质：**source 层数据准备工坊的产出**——多个独立编辑器可共享消费的标准化资产
   - 跟编辑器层无运行时耦合

2. **项目 (Projects)** — 独立编辑器模块实例
   - 当前的「派生作品」整段挪过来——news_desk / clip_script / bilingual_video / 未来更多形态
   - **改名建议**：「派生作品」→「项目」（跟 [[ADR-0003]] 一致：派生作品不是派生，是独立编辑器实例）
   - 每个实例展开 = 实例下的可见 artifacts（output.mp4 / publish.md 等）

3. **文件 (Files)** — 文件资源管理器视图
   - 项目目录树（folder 结构）
   - 方便用户跳过模型直接看磁盘上的东西

### 关键设计点（开工前讨论）

- **空状态**：没源视频时「资源」tab 长什么样？引导用户先「下载」/「转字幕」？
- **跨 tab 跳转**：点「资源」里某个 artifact，是否在「项目」tab 里高亮用到它的项目？目前所有 artifact 都属 source 层，没显式 binding——但 subtitle 组件按 ADR-0003 现在快照了，跟 source 字幕不一定一致。怎么显示这种漂移？
- **预览 tab 0 的关系**：右栏 preview tab 0 跟左侧三 tab 怎么联动？目前是单击 sidebar artifact = 切 preview tab 0 内容，需要扩展到三 tab 各自的选中物
- **改名「派生作品」**：UI 文案改不改？memory `feedback_user_facing_naming` 提醒过用户实际看见的词要 grep i18n。这次改名是个 i18n 级动作

### 接力起点

- HEAD `2387735` (workspace clean)
- 关键代码定位：`src/VideoCraftHub.py` 的 sidebar 构造（grep `_build_sidebar`、`_build_news_context_section`、`派生作品`/derivative）
- ADR-0003 在 `docs/adr/0003-editor-modules-decoupling.md`，开工前重读

### 其它候选（次优先级）

- 真实使用攒反馈（跑完整素材跑一遍 publish.md / chapter videos）
- subtitle Phase 2（cue 内联编辑）
- subtitle Phase 3（增删 cue + 重新导入按钮）
- 多发言人 → 名牌组件
- 组件框架推广到 clip_script

老 instance 没 titles 字段——用户必须重新点一次 chapter import 才能在 publish.md 看到候选标题。是 ADR-0003 一致性的代价。

---

## 仍生效的开发约定

- prompt 改动必须 git commit（不能只改 src/core/prompts.py 不刷盘 prompts/*.md，反过来也是）
- 改 UI 布局/模块结构前 grep `docs/`（[[feedback_check_design_docs]]）
- UI 文案先 grep `src/i18n/*.json` 找用户实际看见的词（[[feedback_user_facing_naming]]）
- 新 `tk.Toplevel` 弹窗照 `src/ui/dialog_utils.py` docstring 模板写
- 派生作品**任何**新代码必须遵守 [[ADR-0003]]——render/export 只读 instance 状态，不回扫上游

---

## 不在本任务范围（备忘）

- chapter_editor 双击迟钝是 WebView2 焦点系统级问题，focus_force 已尽可能修，剩余偶发不彻底
- subtitle Phase 2/3：cue 编辑能力。今天没做
- image_watermark 还在引用模式（ADR-0003 灰区）
- chapter `_import_from_analysis` 整覆盖：保留 partial-merge 的需求记着
