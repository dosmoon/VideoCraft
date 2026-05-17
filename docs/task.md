# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

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
