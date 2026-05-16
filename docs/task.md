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

## 下一手 — 待定

本会话定的几个候选方向（按强度排序）：

1. **真实使用攒反馈** — 现在三栏 UI 就位，跑完整素材 + 创作流程，看哪里别扭。最高 ROI
2. **subtitle Phase 2/3**（[[ADR-0003]] 残留）：cue 内联编辑 / 增删 cue / 重新导入按钮
3. **第二种素材类型尝试**（普通视频素材，无新闻 context）— 一旦立项，可同时清掉上面三个 warts（runner 参数化、sidebar_renderer wiring、素材 tab 级 [+]）。是个干净的"插件化跑通"验证
4. **第二种创作类型**（比如"短视频合集"等）— 同上效果
5. **AI 调用预算治理** — [[feedback_ai_call_budget]] 已经记着；可以系统性扫一遍现有 prompt 看哪些 lean 化收益高

---

## 仍生效的开发约定

- prompt 改动必须 git commit（不能只改 src/core/prompts.py 不刷盘 prompts/*.md，反过来也是）
- 改 UI 布局/模块结构前 grep `docs/`（[[feedback_check_design_docs]]）
- UI 文案先 grep `src/i18n/*.json` 找用户实际看见的词（[[feedback_user_facing_naming]]）
- 新 `tk.Toplevel` 弹窗照 `src/ui/dialog_utils.py` docstring 模板写
- 创作（前「派生作品」）**任何**新代码必须遵守 [[ADR-0003]]——render/export 只读 instance 状态，不回扫上游
- 新代码必须遵守 [[ADR-0004]]——core/ 零 Tk 零插件名；插件 self-register；UI 文件按归属规则放
- pre-alpha 阶段，命名/迁移不要套"用户习惯/保守方案"（[[feedback_pre_alpha_no_legacy]]）
