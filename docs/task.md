# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## 本会话主题：插件化大重构（ADR-0004 落地）

会话起点 HEAD: `7d2e603`。

### 决定

升级到**三层插件架构**——`Base / Materials / Creations`。完整 why + how 见 [docs/adr/0004-three-tier-plugin-architecture.md](adr/0004-three-tier-plugin-architecture.md)。

核心动作：
- 新建 `src/materials/` 和 `src/creations/`，都是 type-extensible 自注册插件包
- 把当前唯一的素材类型「**新闻视频素材**」（源视频 + 字幕 + AI 分析 + 章节 + context）聚合进 `materials/news_video/`
- 把三个创作类型（news_desk / clip / bilingual_video）从 `tools/` 迁到 `creations/`
- 删 `core/derivative_types.py`，注册机制改成插件自报家门
- 重写 `VideoCraftHub.py`：2 tab → 3 tab（**素材 / 创作 / 文件**），preview tab 0 改名「**主窗口**」，所有插件特有 sidebar section 由插件自渲染
- 「派生作品」字面全清零，UI 改叫「创作」

### Slice 推进计划

| Slice | 内容 | 状态 |
|---|---|---|
| A | ADR-0004 + 本 task.md handoff | ✅ |
| B | `creations/` + `materials/` 空骨架 + abstract base | ⬜ |
| C | 迁 `creations/news_desk` ← `tools/news_desk` | ⬜ |
| D | 迁 `creations/clip` + `creations/bilingual_video`（← `tools/subtitle`） | ⬜ |
| E | 删 `core/derivative_types.py`，调用切到 creations registry | ⬜ |
| F | 建 `materials/news_video/` 骨架 + 迁 `SourceContext` (15 字段) | ⬜ |
| G | 插件特有 UI 文件从 `src/ui/` 迁到插件包 | ⬜ |
| H | 重写 `VideoCraftHub.py` — 三 tab + 插件自渲染 + 主窗口改名 | ⬜ |
| I | i18n key 全量改名 derivative → creation；「派生作品」字面清零 | ⬜ |
| J | tab 级 [+] 收口 + type-picker 通用化（素材/创作共用） | ⬜ |

依赖链：A → B → (C ∥ D) → E → F → G → H → I → J

### 关键不变量（实施时必须守住）

- `core/` 零 Tk，零插件名字
- 各插件 sidebar 渲染必须**自己**画自己的节点，Hub 不再有 `_build_<插件特有>_section`
- 素材→创作的数据流通过 `MaterialType.artifact_resolver(instance, key) → Path`，创作插件按 [[ADR-0003]] 做快照
- UI 文件归属：只有一种插件用 = 归该插件；多种/框架级 = 归 `src/ui/`
- 三栏 sidebar 命名：**素材 / 创作 / 文件**（不是「资源/项目/文件」，不是「派生作品」）
- preview tab 0 改名「**主窗口**」（不再叫「项目」）
- 创作 tab 内 **不按 type 分栏**，instance 平铺；type 信息靠 instance 行体现
- `[+]` 按钮上移到 tab 级，由两个 tab 各自的 tab header 区域承担

### UI 文件归属表（slice G 用）

| 现位置 (src/ui/) | 目标位置 |
|---|---|
| source_preview_pane.py | materials/news_video/ui/ |
| srt_preview_pane.py | materials/news_video/ui/ |
| news_context_pane.py | materials/news_video/ui/ |
| source_basic_info_dialog.py | materials/news_video/ui/ |
| source_context_dialog.py | materials/news_video/ui/ |
| source_add_dialog.py | materials/news_video/ui/ |
| source_prepare_modal.py | materials/news_video/ui/ |
| subs_lang_picker.py | materials/news_video/ui/ |
| subtitles_dialogs.py | materials/news_video/ui/ |
| subtitles_progress_modal.py | materials/news_video/ui/ |
| subtitle_analysis_preview.py | materials/news_video/ui/ |
| chapter_editor.py | materials/news_video/ui/ |
| new_derivative_dialog.py | **留 `ui/` 但改名 + 通用化**（slice J） |
| composition_preview.html | 跟 core/composition/ 走（slice B 时移） |
| dialog_utils.py / collapsible_frame.py / web_preview*.py / vlc_player.py / video_preview_pane.py / ai_error_dialog.py / disclaimer_dialog.py / new_project_dialog.py | **留 `src/ui/`**（真通用） |

### 接力起点（每片完成后更新这行）

- Slice A 完成 → HEAD: 待 commit；下一步开 Slice B

---

## 仍生效的开发约定

- prompt 改动必须 git commit（不能只改 src/core/prompts.py 不刷盘 prompts/*.md，反过来也是）
- 改 UI 布局/模块结构前 grep `docs/`（[[feedback_check_design_docs]]）
- UI 文案先 grep `src/i18n/*.json` 找用户实际看见的词（[[feedback_user_facing_naming]]）
- 新 `tk.Toplevel` 弹窗照 `src/ui/dialog_utils.py` docstring 模板写
- 创作（前「派生作品」）**任何**新代码必须遵守 [[ADR-0003]]——render/export 只读 instance 状态，不回扫上游
- pre-alpha 阶段，命名/迁移不要套"用户习惯/保守方案"（[[feedback_pre_alpha_no_legacy]]）

---

## 不在本会话范围（备忘）

- 第二种素材类型的拆分（普通视频素材 / 访谈视频素材）——等真出现再做
- 通用插件 manifest.json schema——当前 Python 自注册够用
- chapter_editor 双击迟钝是 WebView2 焦点系统级问题（已 focus_force 修过）
- subtitle Phase 2/3：cue 编辑能力
- image_watermark 还在引用模式（ADR-0003 灰区）
