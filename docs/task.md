# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## 本会话主题：插件化大重构（ADR-0004）— 已收尾

会话起点 HEAD: `7d2e603`。
会话结尾 HEAD: 待 commit slice J。

10 个 slice (A→J) 全部落地。完整决策见 [docs/adr/0004-three-tier-plugin-architecture.md](adr/0004-three-tier-plugin-architecture.md)。

### 已完成 slice

| Slice | HEAD | 内容 |
|---|---|---|
| A | `9edfd1e` | ADR-0004 写入 + task.md 计划版交接锚 |
| B | `bba5dda` | `creations/` + `materials/` 空骨架 + abstract base |
| C | `743e9a5` | 迁 `creations/news_desk` ← `tools/news_desk` |
| D | `3f99c1b` | 迁 `creations/clip` + `creations/bilingual_video` ← `tools/{clip,subtitle}` |
| E | `6dd8933` | 删 `core/derivative_types.py`；调用切到 `creations` registry；插件自报家门 |
| F | `8154221` | 建 `materials/news_video/`；迁 `SourceContext` (15 字段) + AI fill |
| G | `156feed` | 12 个插件特有 UI 文件从 `src/ui/` 迁到 `materials/news_video/ui/`；删 shim |
| H | `ee1e00f` | sidebar 2 tab → 3 tab（**素材/创作/文件**）；preview tab 0 → 「主窗口」；创作 tab 平铺、无 type 分栏 |
| I | `6b63743` | i18n key 全量改名 `derivative` → `creation`；「派生作品」字面清零 |
| J | 本 commit | 去掉创作 section 内冗余「创作」标题（tab 标签已经叫创作）；[+] 留在 tab 顶 |

### 关键不变量已守住

- ✅ `core/` 无 Tk、无插件 type 名字
- ✅ 素材/创作两套 type registry 独立，机制泛型、条目插件自注册
- ✅ 素材 plugin 跟 base 解耦；创作 plugin 跟素材通过显式契约消费（artifact_resolver 字段已声明，实际 wiring 留待消费端首次需要）
- ✅ UI 文件归属：通用工具留 `src/ui/`；插件特有迁到插件包
- ✅ 三栏 sidebar = 素材 / 创作 / 文件
- ✅ preview tab 0 = 主窗口

### 已知 warts（这次没修，留 TODO）

- **`core/subtitle_analysis_runners.py:33` 直接 import `materials.news_video.schema.combined_prompt_block`** — core/ 不该认识插件 schema。`# TODO(ADR-0004)` 注释在位。cleanest fix = 参数化 runner，让调用方（知道 material 类型的那一层）注入 prompt block。等第二种素材类型出现或字幕分析消费端重构时一并做
- **Plugin self-render via `MaterialType.sidebar_renderer` / `create_handler` / `artifact_resolver` 未 wire** — 字段已经声明在 `materials.MaterialType` dataclass 上，Hub 还是自己 hard-code 着 `_build_source_section` / `_build_news_context_section` / `_build_subtitles_section`。MaterialType.sidebar_renderer 是 None。等下一次"sidebar 渲染要改动"时连 wiring 一起做，或者第二种素材类型登场时强制做
- **素材 tab 没有 tab 级 [+]** — Source section 自带 [+]，但 ADR-0004 的对称设计是 tab 级 [+]。当前只有 1 种素材类型，tab 级 [+] 等同于 Source [+]，所以这步留到 第二种素材类型出现时一并做

### 已知小不一致

- `dialog.new_creation.title_typed` 的 `{type}` 参数当前传的是已经 i18n 过的 display name（`creations.display_name(type_name)`），与原 `dialog.new_derivative.title_typed` 行为一致。但 ADR-0004 模型下，「类型」概念展示词应该是 `material.<x>` / `creation.<x>` 双重 namespace。slice 重命名只 touched creation 命名空间，材料命名空间还没有用例。等第二种素材或创作类型登场时补
- 老 instance 在 `<project>/derivatives/<type>/<inst>/` 下不动；目录名沿用 `derivatives/`（不改成 `creations/` 是为避免破坏既有 project 的兼容；用户磁盘上的目录不能 hot-rename）。代码层概念已经全切到 creations

---

## Slice K — 用户对 J 的反馈：素材 sidebar 真正封装进 news_video 插件

J 之后用户指出：
- 素材 tab 没有 tab 级 [+]（设计要求 [+] 是 tab-level、registry-driven popup）
- Hub 仍直接构造 source/news_context/subtitles 3 个 section——这不是封装，是壁纸贴新墙
- 新闻视频"本身就是结构化的"，所有 schema + UI + 加载逻辑应该完整封装在 `materials/news_video/`

### K.1 已完成（HEAD `c7b9a07`）

架构 seam 落地 + 用户可见 UX 补齐：
- `materials/news_video/sidebar.py` 加 `NewsVideoSidebar` 类 + `render()` 入口；`MaterialType.sidebar_renderer` / `create_handler` 都 wire 上了
- Hub `_build_materials_tab` 重写：迭代 `materials.all_types()`，让每个 type 的 `sidebar_renderer` 画自己的面板；Hub 不再知道任何 type 的 section 名字
- Hub 加了 tab 级 [+] popup menu（registry-driven，每个 MaterialType 一条目，带 icon + display name）
- Hub 把当前的 section 构造代码改名 `_build_materials_tab_legacy` / `_refresh_materials_tab_legacy`——**plugin class 当前还是 delegate 回 hub 的 legacy 方法**

### K.2 待做（pure refactor，无行为变化）

把 ~500 行 news_video-specific 代码从 `VideoCraftHub.py` 真正搬到 `materials/news_video/sidebar.py` 的 `NewsVideoSidebar` 类内：

待迁方法：
- `_build_source_section` / `_build_news_context_section` / `_build_subtitles_section`
- `_refresh_source_section` / `_refresh_news_context_section` / `_refresh_subtitles_section`
- `_on_source_button` / `_on_subtitles_primary` / `_invoke_asr` / `_invoke_translate` / `_import_subtitle_file`
- `_subtitles_section_snapshot`
- 各 section 内的 row helper（per-language SRT row, analysis sub-rows, etc.）

适配规则：
- `self.project` → `self.hub.project`
- `self.root` → `self.hub.root`
- `self.show_*_preview` 调用保持 → `self.hub.show_*_preview()`（preview 路由是 hub 概念）
- `self._refresh_project_tab` → 改成 `self.refresh()` 或 `self.hub._refresh_project_tab()`（确认哪种）
- Hub 端删完之后，`_build_materials_tab_legacy` / `_refresh_materials_tab_legacy` 也跟着删；`NewsVideoSidebar.__init__` / `refresh` 直接做活

预估：单 commit 完成，~500 行 cut/paste + ~50 处变量适配。低风险（pure mechanical refactor）但篇幅大；下一个会话起手做这个。

### K 之后的 UI 设计问题（也需要拍板）

当前 K.1 实现：news_video 面板**始终渲染**（即使源视频未添加）；用户看到 3 个空槽位 + 各自的 [+ 添加] 内联按钮。

设计层面待澄清：
- 这是不是用户预期？还是希望"源视频未添加时素材 tab 全空、只看见 [+]，点 [+] 后才出现 news_video 面板"？
- 后者意味着把 source video 当作"创建 instance 的动作"而非"填满第一个槽"。当前单源项目模型下两种解释都讲得通，但 UX 不同
- 推荐先用 K.1 跑一段时间，等真实使用觉得别扭再决定。

---

## 后续候选方向（K.2 之后）

1. **真实使用攒反馈** — 三栏 UI + 插件 seam 都在了，跑完整素材 + 创作流程看哪里别扭
2. **subtitle Phase 2/3**（[[ADR-0003]] 残留）：cue 内联编辑 / 增删 cue / 重新导入按钮
3. **第二种素材类型尝试**（普通视频素材，无新闻 context）— 一次性清掉所有 ADR-0004 残留 warts（runner 参数化、artifact_resolver wiring）
4. **第二种创作类型** — 同上效果
5. **AI 调用预算治理** — [[feedback_ai_call_budget]] 已经记着

---

## 仍生效的开发约定

- prompt 改动必须 git commit（不能只改 src/core/prompts.py 不刷盘 prompts/*.md，反过来也是）
- 改 UI 布局/模块结构前 grep `docs/`（[[feedback_check_design_docs]]）
- UI 文案先 grep `src/i18n/*.json` 找用户实际看见的词（[[feedback_user_facing_naming]]）
- 新 `tk.Toplevel` 弹窗照 `src/ui/dialog_utils.py` docstring 模板写
- 创作（前「派生作品」）**任何**新代码必须遵守 [[ADR-0003]]——render/export 只读 instance 状态，不回扫上游
- 新代码必须遵守 [[ADR-0004]]——core/ 零 Tk 零插件名；插件 self-register；UI 文件按归属规则放
- pre-alpha 阶段，命名/迁移不要套"用户习惯/保守方案"（[[feedback_pre_alpha_no_legacy]]）
