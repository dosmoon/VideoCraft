# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## news_desk 章节体验全面收尾 + 布局回正 — 已上线

HEAD: `0088edd` (已 push origin/main)，workspace clean。

### 本次会话的 commit 串

| commit | 内容 |
|---|---|
| `0ff9da9` | Hero Card overlay：新 ChapterHeroCardOverlay/Style，ass renderer + WebView 镜像；chapter `start_card` 路由到 hero（不再用 ChapterPointCardOverlay）；inline_style 字段允许 per-spec style override |
| `8ed2db4` | chapter 单一 kind 模型：删 end_summary mode；inline 详情面板替换模态对话框（点 row → seek + 填详情 + 实时回写） |
| `3f3f458` | 章节导入按钮挪到工具栏 + 弹窗解释 4 段（用 UI 实际词汇 📑「标题与章节」，不再用代码内部名 subtitle.pack/refined/key_points） |
| `6a737c9` | `src/ui/dialog_utils.py::center_dialog_on_parent` canonical helper + 收编 11 个历史拷贝粘贴 |
| `df134dd` | dialog auto-size + minsize + 按钮先 pack bottom（修被裁掉的按钮） |
| `0088edd` | 布局回正：v0.3 设计文档 §2 — 左竖向 (preview 上 / list 下) + 右属性满高；「组件」→「图层」 |

### 关键模型/文档变更

- **章节是唯一 kind，模式是 view filter**：起始大卡 = "用 chapter 数据渲一次 hero card"，不是单独"大卡数据"。end_summary 删除（曾 DEFERRED，单一 kind 模型下没必要）
- **chapter.py 模块 docstring 写明**：news_desk 当前**复用 analysis.json schema**（过渡设计），未来会拥有自己的 schema（参见模块顶部 ARCHITECTURE NOTE）
- **独立性目标**：news_desk 派生**只需 source 视频**，SRT/analysis.json/context.json 都是可选；手工建一个完整章节列表 + 添加水印 + 跑通 MP4 必须能走通——这是接下来要验证的
- **WebView 修复**：N 字幕路径下 sub1+sub2 都 disabled 时，`drawSubtitles` 早 return 导致 extras 也不画 → 删掉 early return（对应历史会话）
- **图片水印真加载**：`new Image()` + file:// 缓存（早先是占位框）

### 学到的元规则（已存为 memory）

- `feedback_check_design_docs` — 改 UI 前 grep `docs/draft/` 和 `docs/design/`，别拍脑袋
- `feedback_user_facing_naming` — UI 文案绝不用代码内部名（task / field / class），先 grep i18n 找 UI 实际叫什么
- `reference_dialog_pattern` — 弹窗标准模板在 `src/ui/dialog_utils.py` docstring，照着抄

## 下一步候选

1. **真实使用攒反馈** — 拿一个真实新闻视频跑一遍：3+ 字幕 + 2+ 水印 + 章节起始大卡，预览 vs 烧录对比
2. **chapter 导入合并策略** — 当前 `_import_from_analysis` 整个覆盖（有红字警告但仍危险），加 partial-merge：保留用户手工添加 / 编辑过的 row
3. **多发言人 → 名牌组件** — 等 AI 提取多发言人 schema 出现
4. **章节其它视觉模式** — 如果 dogfood 后觉得 hero / top_strip 不够
5. **组件框架推广** — clip_script / bilingual_video 用同一 components-based 重构（大工程，先观察 news_desk 几周）

我建议 **1 → 2**：先 dogfood，再补 import 安全网。

---

## 仍生效的开发约定

- prompt 改动必须 git commit（不能只改 src/core/prompts.py 不刷盘 prompts/*.md，反过来也是）
- 修 ComponentSpec 改组件原语前回看 `[[feedback_no_code_structure_in_ux]]`
- AI 任务设计前看 `[[feedback_ai_call_budget]]` + `[[reference_claude_cli_options]]`
- 改 UI 布局/模块结构前 grep `docs/`（`[[feedback_check_design_docs]]`）
- UI 文案先 grep `src/i18n/*.json` 找用户实际看见的词（`[[feedback_user_facing_naming]]`）
- 新 `tk.Toplevel` 弹窗照 `src/ui/dialog_utils.py` docstring 模板写

---

## 不在本任务范围（备忘）

- v0.3 设计文档 `docs/draft/news_desk-ux-v0.3.md` **A/B 类分类那部分**已被 v0.4 推翻；**布局那部分仍生效**（已对齐）
- timeline 拖拽编辑——v0.4 砍掉了，列表顺序 = z-order，足够
- 名牌 / PullQuote / 引文 / 数据卡 等新组件——等需求清楚再加
