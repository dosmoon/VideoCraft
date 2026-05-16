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

## 下一步候选（按优先级）

1. **真实使用攒反馈** — 把这一整套跑一遍真实素材，看 publish.md / chapter videos 出来的效果
2. **subtitle Phase 2** — cue 内联编辑（仿 chapter_editor inline 模式：点 row → seek + 在下方编辑文本/时间）。先验证 dogfood 中是否真的需要在 news_desk 里改字幕
3. **subtitle Phase 3** — 增删 cue + 重新导入按钮（带本地编辑覆盖警告）
4. **多发言人 → 名牌组件** — 等 AI 提取多发言人 schema 出现
5. **组件框架推广到 clip_script** — clip_script 同样走 ADR-0003 解耦？需要先想清楚 clip 形态跟 news_desk 的差异（clip 是切片产出 N 个 short，news_desk 是整片）

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
