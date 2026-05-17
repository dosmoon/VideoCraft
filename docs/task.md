# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## ▶ 下次会话主题：timeline 迁移收尾 follow-ups (可选)

**Axis 1~7 全部锁定 + PR 1/2 + ADR-0006 已合 main**。设计稿在 `docs/design/composition-timeline-v0.md`，权威 ADR 在 `docs/adr/0006-composition-timeline-ir.md`。

### 已完成（本次 + 上次会话）

- ADR-0006 立项；ADR/0001~0006 README 同步
- PR 1：timeline.py + compile.py + primitives/__init__.py 脚手架（commit `c555449`）+ 24 测试
- PR 2 前置：8 个渲染字符串 golden seeded（commit `55612b0`），3 ASS + 5 snippet
- PR 2 part 1/2：删 `news_desk_overlays.py` 491 行，topic_strip + chapter_hero_card primitive 落地，libass_helpers.py 引擎级 helper（commit 在 main，本会话）
- PR 2 part 2/2：5 个 primitive（subtitle_cue / text_watermark / image_watermark / hook_text / outro_text）+ drawtext_helpers.py；render.py 979 → 816 行；统一 primitives 注册中心（commit `66cd2c0`）
- PR 3：`compile_timeline()` 真实现 + `primitives.KNOWN_KINDS` 7 kind catalog + 4 个 news_desk component 各加 `_compile()` + `ComponentDictAdapter` bridge dict→Protocol（commit `37b4e71`）
- PR 4：news_desk 切到 timeline——`CompositionRequest.timeline` 双路径 + `CompositionPreview.set_timeline()` + `_rebuild_timeline()` + 删 `_build_render_inputs`+`_rebase_overlays`；`subtitle_libass` → `subtitle_cue` 双命名 reconcile；8 新 e2e 测试验证 timeline→Spec roundtrip byte-equal vs chapter+topic_strip golden（commit `04c11f1`）
- PR 5：clip 切 timeline + 老路径删——`creations/clip/timeline_builder.py` 新增 `build_clip_timeline()`；`CompositionRequest` 压到 7 字段（删 7 个老字段）；删 `_named_overlay_jobs` / `_prepare_track_srt` / `ExtraSubtitleSpec` / `ExtraWatermarkSpec` / 3 个 news_desk-only preview Python 桥；timeline 字段变 required；7 个新架构 grep guard 锁死（commit `4dd932b`）
- 全程 217 测试 + 11 goldens byte-equal；**timeline 迁移主体完成**

### Timeline 迁移完成度

**已完成（5 PR 全部 land）**：
- 引擎统一 timeline IR + primitive registry
- news_desk 端到端走 timeline（render + preview）
- clip 渲染走 timeline
- `CompositionRequest` 干净 7 字段
- 老 5 通道 dispatch 路径整块删除
- 11 goldens byte-equal 全程守护
- 217 测试全绿

**故意 deferred（不影响主体功能，作为未来 follow-up）**：

1. **clip preview live-editing → set_timeline**
   - 现状：clip 的 UI live 编辑（每次 var 变化）通过 `set_cues` / `set_cues_secondary` / `set_clip_meta` 直接推送 preview。这 3 个 Python 桥仍留在 `CompositionPreview` 上
   - 阻塞物：clip UI 当前 var-trace 驱动，重建 timeline 喂 `set_timeline` 需要每次都跑 IO（读 SRT）。需要 cue 缓存机制或 UI 重构
   - 优先级：中。clip preview 工作正常；只是双 push 路径（news_desk 走 timeline，clip 走 bridges）

2. **JS bridge 收口到单 `window.vc.setTimeline()`**
   - 现状：`composition_preview.html` 仍有 `setOverlays / setCues / setCuesSecondary / setExtraSubtitles / setExtraWatermarks / setClipMeta` 6 个 JS 入口；`set_timeline` Python 把 timeline 拆成多个 JS 调用
   - 阻塞物：JS 重写工作量（~200 行 HTML/JS）
   - 优先级：低。Python 接口已经统一；JS 是内部 impl

3. **WatermarkStyle / HookOutroStyle 拆成窄 primitive Style**
   - 现状：`style.py` 还有统一的 `WatermarkStyle`（带 `type` discriminator）和 `HookOutroStyle`（同时管 hook + outro）
   - 阻塞物：clip UI 直接构造 `WatermarkStyle(type=...)`；拆要改 ~5 个 callsite + 测试
   - 优先级：低。纯架构清洁度，无 runtime 影响

### 下次会话开场建议

不强求接 follow-up。timeline 迁移主体已完成，可以：
- **(A)** dogfood 几天（news_desk + clip 实际跑一跑，看新路径有没有 bug）
- **(B)** 推动这 3 个 follow-up 中的某一个（建议按优先级 1→3）
- **(C)** 切回别的工作（backlog 里 P1 还有 PPT2Video / 字幕工作台 / 用户数据绿色化 / yt-dlp JS runtime）

### 起点 HEAD

`4dd932b` — "composition: PR 5 — clip → timeline + delete legacy"，已 push origin/main。217 测试全绿；11 goldens byte-equal。

---

## ▶ 老主题（已被 timeline 设计取代，仅留作上下文）

下面这些是 2026-05-17 上半段的待办，**已经在 timeline 设计中被消解或合并**——不需要单独再做：
- "主线 2"（composition 边界 / 注册表化）：被 timeline 设计完整覆盖
- "主线 3"（共享组件归属）：消失（timeline 让 primitive 归属问题消解）
- "主线 1"（clip 组件化）：等 timeline v0 上线后自然受益（clip 也走 ComponentInstance 协议）

### 主线 1 — 验证 news_desk 抽象组件逻辑在 clip 模块的可用度

news_desk 这轮把"组件"沉淀成了一套清晰抽象：
- `ComponentSpec` registry（multi_instance / default_z / build_property_panel / to_overlays / import_sources）
- `ProjectContext` 传递（project / duration / instance_dir / material_model / seek_to）
- 组件自注册，workbench 迭代组件、收 render fragment、按 list 顺序定 z

**问题**：clip 创作还是老式 `CompositionStyle` 直接持 hook/outro/subtitle/watermark 字段——没走 ComponentSpec。该不该把 clip 也改造成组件化？

调研要点：
- clip 的核心语义是"长视频 → N 段短视频"，跟 news_desk 的"一对一带 overlay"不同。组件抽象能否承载"多输出"形态？
- clip 现有元素（hook / outro / subtitle 主副 / watermark / hotclip 候选列表）拆成组件后是什么形状？
  - hook_outro 应该是一个组件（一对开/收文案）还是两个（hook 组件 + outro 组件）？
  - hotclips 候选列表是组件吗？还是更高一层的"切片任务集合"？
- ProjectContext 在 clip 场景下需要哪些字段？多输出场景下"instance_dir"语义如何变？
- 哪些 news_desk 组件可以直接复用到 clip？（subtitle / text_watermark / image_watermark 几乎肯定可以）

成果形态：要么 **clip 改造方案 + 第一步落地**，要么 **结论"组件抽象不适配 clip 多输出语义" + 给出替代方案**。两者都比"先放着"有价值——是个二选一的架构判定。

### 主线 2 — 进一步界定 composition 引擎的功能

`core/composition/` 现在包含：
- `style.py` —— CompositionStyle + 各种 overlay 样式 dataclass（ChapterHeroCardStyle / LowerThirdStyle / TopicStripStyle / DateStampStyle / etc.）
- `overlays.py` —— overlay 数据 dataclass（ChapterHeroCardOverlay / TopicStripOverlay / etc.）
- `render.py` —— ffmpeg 编排
- `preview.py` —— WebView 适配
- `news_desk_overlays.py` —— news_desk 特定 overlay 的 libass 渲染逻辑（**已知 wart：core 认识 news_desk**）
- `presets.py` —— clip preset 全套 + hook_outro preset
- `layout.py` / `text_layout.py` / `fonts.py` 等

**问题**：哪些算"通用组合引擎"，哪些是某个创作类型的私有渲染？现在边界混乱。

调研要点：
- `news_desk_overlays.py` 整文件该不该挪到 `creations/news_desk/` 下？
- `ChapterHeroCardStyle` / `ChapterHeroCardOverlay` 是 news_desk 专属，挂在 `core/composition/style.py` / `overlays.py` 里合理吗？
- 把 news_desk 的 overlay 抽出去之后，`core/composition` 还剩什么？是否变成纯"字幕烧录 + 水印 + 输出几何 + 渲染编排"的窄引擎？
- 反向：是否要给 composition 一个"overlay registry"机制，让各创作插件**注册自己的 overlay 渲染器**到 composition，而不是把代码挪走？
- clip 的 hook_outro 也是同样问题——hook_outro 是 clip 专属还是通用组合元素？

### 主线 3 — 引擎组件归属问题

跟主线 2 重叠但更广。组件层面要回答：
- subtitle / text_watermark / image_watermark 三种组件几乎肯定**多创作类型共享**——它们的代码归属在哪？现在挂在 `creations/news_desk/components/` 下，clip 想用得 import 跨创作？
- 答案候选：
  - **A 共享组件库**：`creations/_shared_components/` 或 `core/components/`，每个创作 opt-in 注册它需要的组件
  - **B 各创作复制粘贴**：组件代码在 `creations/<x>/components/` 下各自实现，接受小重复
  - **C 抽到 core/composition 当一等元素**：composition 引擎直接管这些"通用 overlay 类型"，创作只调用
- 各方案利弊？跟 ADR-0004 的"plugin self-contained"原则冲突吗？

### 推荐流程

1. **先调研，再动代码**——这三条主线本质都是架构判定题，不是 bug 修复。先 grep 出 clip 当前组件用法 / composition 跨创作引用 / news_desk overlay 边界，列出现状。
2. **跟用户对齐方向再落地**——三条主线任何一条都可能 200+ 行改动，先讨论再写代码。
3. **可能的产出**：新 ADR-0006「组件抽象的归属与共享」或「composition 引擎边界」。本次会话沉淀的 [[feedback_material_via_model_only]] 和 [[project_creation_config_owner]] 模式可以作为新 ADR 的参考案例。

### 起点状态

- HEAD: `0c1b328`（已 push origin/main）
- 147 测试全绿
- news_desk 是组件化的参考实现，clip 是非组件化的对照组
- 已知 wart：`core/composition/news_desk_overlays.py` + `style.py` 里的 Chapter/LowerThird/TopicStrip 类——本次会话没动，作为下次的入口

---

## 本次会话主题：legacy 大清扫 + news_desk 架构收口（2026-05-17）

会话起点 HEAD：`7d2e603`
会话结尾 HEAD：`31a4d2d`（已 push origin/main）

47 个 commit，三大块：

1. **legacy / dead code 清扫**（A1~A6 审计 + 模块整体退役）
2. **news_desk 架构两步收口**：素材访问全走 Model API；config.json 单一内存所有者
3. **news_desk preset 系统重生** + chapter hero card 视觉重做

---

## 1. legacy 大清扫（净删约 3110 行）

按 [[feedback_pre_alpha_no_legacy]] 规则系统性扫，6 个候选 + 顺手收掉的模块：

| Commit | 内容 | 净行变化 |
|---|---|---|
| `506088d` (A1) | 删 `core/burn_subs.py` 整文件——零调用者死代码 | -353 |
| `8b36414` (A2) | 切 basic_info / context 合并视图——context.json 成为下游唯一权威；删 `combined_dict` / `combined_prompt_block`；改下游 4 个调用点 | -66 |
| `8997878` | 删整个 `creations/bilingual_video/` 模块（news_desk 完全覆盖其能力）+ biliburn preset API + i18n keys | -1680 |
| `ed0acc1` (A4) | news_desk subtitle 删 ADR-0003 过渡 fallback（`_ensure_id` / `_is_local_snapshot` / legacy_ref 状态） | -44 |
| `3597a40` (A5) | clip publish 删 filename fallback + 修 3 处误标 "legacy" 的注释 | +8 |
| `6a32096` (A6) | 删 `tools/subtitle/srt_tools.py` 整文件 + srt_ops 瘦身 8 个函数 + 菜单条 + i18n | -973 |

合计：**净删 ~3110 行，127→147 测试覆盖**。

---

## 2. news_desk 架构两步收口

### 2.1 素材数据访问全走 NewsVideoModel（`99c64db`）

发现：news_desk 多处 `from materials.news_video import paths as _nv_paths` 直接戳素材插件的内部路径助手——9 处 callsite 跨 4 文件，违反 ADR-0004 三层架构。

**改动：**
- `NewsVideoModel` 新加 `list_analyses()` + `read_analysis(filename)`——素材插件对外的唯一数据接口
- `ProjectContext.material_instance_id` → `material_model`（组件直接拿 model，不再持裸 instance_id）
- `NewsDeskApp.__init__` 构造 `self.material_model = NewsVideoModel(project, instance_id)`，所有访问经此对象
- 9 callsites 全改 `model.X` 调用方式
- 删 `_nv_paths` import 4 处
- 架构测试加 3 条：组件不准 import 或调 `_nv_paths`，ProjectContext 必须有 `material_model`

→ 记忆：[[feedback_material_via_model_only]]

### 2.2 NewsDeskInstanceConfig 单一内存所有者（`a84b65b`）

发现：reopen instance 仍弹 picker 的 bug 根因——**两个 writer 抢一个 config.json**：
- `material_binding.write_bound_material` 走 read-merge-write
- `_save_instance_config` 走 fresh-dict-overwrite

后者每次保存抹掉前者写的 `bound_material` 字段。

**改动：**
- 新 `creations/news_desk/config.py`：`NewsDeskInstanceConfig` dataclass 是 config.json 的**唯一**内存表示。`load(path)` / `save(path)` 是**唯一** IO 路径
- `material_binding.py` 退化为纯 picker UI（删 `_read_config` / `_write_config` / `read_bound_material` / `write_bound_material` / `get_or_bind`）
- `NewsDeskApp.__init__` 持 `self.config: NewsDeskInstanceConfig`，所有读写经此对象
- `self._components` → `self.config.components`（29 处 rename）
- `self._current_preset_name` → `self.config.preset_name`（5 处 rename）
- 12 个新测试覆盖 load/save 往返 + 关键回归测试（保存→重读→修改→再保存→再读，binding 保持）
- 架构测试锁死：`material_binding` 不准泄露任何 config-IO API

→ 记忆：[[project_creation_config_owner]]

---

## 3. preset 系统重生

老 preset 用 `CompositionStyle` 字典，渲染时 subtitle/watermark 字段被强制清零，切预设视觉无变化——"基本不能用"。

**改动**（`57a5e7f` + `0248471` + `6403795`）：
- 新 `creations/news_desk/presets.py`：`NewsDeskPreset` = `name + description + components[]`，跟 instance 同 schema
- 3 个内置故意做出差异：「新闻发布会」(5 组件) / 「演讲」(3 组件) / 「极简」(1 组件)
- `fresh_components_for(preset)` 应用时 deep-copy + 新 subtitle id + 清 srt_path
- 菜单三件套全对称（submenu-pick 而非 typed-input）：
  - 应用预设 ▶ {builtin + user}
  - 保存当前布局 ▶ 覆盖：{user} | 新建预设...
  - 删除用户预设 ▶ {user}
- 删 `core/composition/presets.py` 里 news_desk 整套 API（~110 行）
- 14 个新测试覆盖内置形状差异 / 用户 preset roundtrip / 内置名保护 / corrupt store 容错 / `fresh_components_for` id 不冲突

---

## 4. chapter hero card 视觉重做

老的「居中黑底大对话框」遮主持人脸 + 字密 + 无识别度，"一言难尽"。

**两步演进：**

`6702ec6` — Mode C（左侧 sidebar）：
- 左侧 30% 宽 × 内容自适应高度的纵向面板，垂直居中
- 半透明 broadcast navy（`#0F1B2C` @ 55%）
- 左缘红色 accent 竖条（`#DC2626`）
- 标题 / 细分隔线 / 正文 三层堆叠
- 滑入 60px + fade 动画
- 不挡主持人脸，不抢底部字幕位

`31a4d2d` — 进一步极简（Option A）：
- `show_body: bool = False`，默认只渲染标题
- title_fontsize 40→56，title_max_lines 2→3
- body 字段保留，flip flag 即可恢复

`0d19ede` — 修标题溢出：wrap budget 从"猜字数"换成"按像素拟合"（`region * 0.92 / fontsize`），preview+render 两端同步

---

## 5. 顺手修的 bug

| Commit | bug | 根因 |
|---|---|---|
| `60e99c7` | chapter "标题与章节" 导入扫描提示"未找到"，但实际能导入 | 扫描路径用了 ADR-0005 早已废除的 `ctx.project.subtitles_dir` 属性，`getattr` fallback 静默返空 |
| `df4803a` | 修 `99c64db` 引入的回归：导入确认后 chapters 仍空 | 缩进 bug——chs/titles 处理块落到了 `if not isinstance(env, dict): continue` 下面（语法 OK 但永远到不了） |
| `35c7180` | reopen instance 弹 picker | 两 writer 抢 config.json（已根治，见 2.2） |
| `3b6e816` | chapter 导入静默成功/失败 | 加 ImportResult 数据类 + dialog 双状态（pick / result）+ 每文件预览 summary |

---

## 新增 / 强化的架构契约

| 契约 | 锁定位置 |
|---|---|
| 创作插件不准 import 素材插件的 paths 模块 | `tests/test_arch_news_desk.py::test_components_dont_import_nv_paths` |
| 创作工作台不准 `_nv_paths.*` 调用 | `tests/test_arch_news_desk.py::test_news_desk_tool_does_not_call_nv_paths` |
| `ProjectContext` 必须有 `material_model` | `tests/test_arch_news_desk.py::test_project_context_has_material_model` |
| `material_binding` 模块只暴露 `show_material_picker` | `tests/test_arch_news_desk.py::test_material_binding_module_is_picker_only` |
| `NewsDeskApp.__init__` 必须经 `NewsDeskInstanceConfig.load` | `tests/test_arch_news_desk.py::test_news_desk_app_init_loads_instance_config` |
| save→reload→mutate→save 必须保持 binding | `tests/creations/test_news_desk_config.py::test_save_then_load_preserves_binding` |

---

## 下一手候选

1. **真实使用攒反馈**——hero card 简化 + preset 重做之后，需要 dogfood 看新形态是否够用
2. **chapter 导入 partial-merge**（替代当前全覆盖）——backlog 里早已欠的
3. **subtitle Phase 2/3**（cue 内联编辑 / 增删 / 重新导入）
4. **多发言人 → lower-third 名牌组件**（新增 component 类型）
5. **chapter 其它视觉模式**（top_strip + start_card 之外）
6. **图片水印改快照模式**（ADR-0003 收尾的最后一个组件）
7. **第二种创作类型登场**——用 ADR-0004/0005 + 本次 InstanceConfig + material-via-model 这套契约去做，看哪里别扭

---

## 仍生效的开发约定

- prompt 改动必须 git commit（不能只改 src/core/prompts.py 不刷盘 prompts/*.md，反过来也是）
- 改 UI 布局/模块结构前 grep `docs/`（[[feedback_check_design_docs]]）
- UI 文案先 grep `src/i18n/*.json` 找用户实际看见的词（[[feedback_user_facing_naming]]）
- 新 `tk.Toplevel` 弹窗照 `src/ui/dialog_utils.py` docstring 模板写
- 创作**任何**新代码必须遵守 [[ADR-0003]]——render/export 只读 instance 状态，不回扫上游
- 新代码必须遵守 [[ADR-0004]]——core/ 零 Tk 零插件名；插件 self-register；UI 文件按归属规则放
- ADR-0005：`<project>/materials/<type>/<inst>/` + `creations/<type>/<inst>/` 对称布局；创作绑素材通过 `bound_material` 字段
- **本次新加**：创作插件访问素材数据**必须**经 Material Model 类，不准戳 paths 模块（[[feedback_material_via_model_only]]）
- **本次新加**：每个创作的 config.json **必须**有单一内存所有者（Instance Config dataclass），所有读写经此对象（[[project_creation_config_owner]]）
- pre-alpha 阶段，命名/迁移不要套"用户习惯/保守方案"（[[feedback_pre_alpha_no_legacy]]）
