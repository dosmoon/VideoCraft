# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## ▶ 下次会话主题：clip Step 5 dogfood + 修问题

clip 组件化重构（Step 5）**全 5 步已完成并 push**（`f464d71`..`15a3f5b`）。
下次启动跑实际 clip 项目，发现问题就修。

### 一句话

`build_clip_timeline` 已退役 → `composer.compile_for_candidate(config.components, ...)`；
StylePanel 三栏改造完成（preview + 组件列表 + property panel）；
`_current_style` 已删，output 字段平铺到 `ClipInstanceConfig`。

### Dogfood 重点观察

1. **新建 clip 项目** → 加 subtitle/hook/outro/watermark → 改属性 → 预览实时反映 → 渲染产出对
2. **打开老 clip 项目**（config 里有 `style` 字段）→ 自动迁移成 components + output 字段 → 渲染跟迁移前一致
3. **预设**：save/apply/overwrite/delete 各按一遍 → output 字段能 roundtrip（subtitle/watermark/hook_outro 在预设里只是占位，不参与）
4. **dual 字幕**：加 2 个 subtitle component（一 primary 一 secondary） → margin_v 自动 stack
5. **crop 全局**：预览拖框 → 「应用到所有 clip」→ 每个 candidate crop 同步
6. **跨 tab 切换**：Tab 1 改完去 Tab 2 → 候选编辑器不显示陈旧状态

### 已知欠债（dogfood 后处理）

- ComponentSpec / ComponentDictAdapter 物理搬到 `core/composition/component_spec.py`（现在 clip 从 news_desk 包 import）
- `creations/clip/components/{subtitle,watermark,hook_outro}.py` 里 `template_from_style` 是 5.5.c 迁移用的死代码——确认所有老 config 迁移完成后可删
- 预设 schema 改成 components-based（现在只 roundtrip output 字段；component 模板不进预设）

### 起点 HEAD

`15a3f5b` "clip: retire _current_style + flatten output settings (Step 5.5.c)"，已 push origin/main。
**340 测试全绿；9 goldens byte-equal**。

---

## 已完成（本轮会话，2026-05-18）

### Step 5 全 5 步 + 5.5 三 sub-step（10 个 commit）

| Commit | Step | 主题 |
|---|---|---|
| `f464d71` | 5.0 | 脚手架：REGISTRY / ComponentSpec / ComponentDictAdapter / config.components |
| `6007d58` | 5.1 | subtitle 迁 ClipSubtitleSpec（render-first） |
| `2af7632` | 5.2 | watermark 迁（text + image 两个 spec） |
| `f30ab9d` | (cleanup) | 删 ClipProjectContext 子类（5.0 多余的脚手架，0 caller） |
| `70e9c99` | 5.3 | hook + outro 迁（per-candidate text 走模板填充器） |
| `38dde98` | 5.4 | `timeline_builder.py` 退役 → `composer.compile_for_candidate` |
| `df5d4a1` | 5.5.a | 5 个 spec 各加 `build_property_panel` |
| `24b90d1` | 5.5.b | StylePanel 三栏重写 + components 接管 render path |
| `15a3f5b` | 5.5.c | `_current_style` 退役 + output 字段扁平到 config |

### 5.5 重大设计转折

5.0 给 `ClipProjectContext` 加 `clip_overrides` 字段，5.1/5.2 用 seeder。
**用户后来质疑**："不就是 N 个 news_desk，用模板生成 N 个数据结构再渲染？"
→ 完全正确。`clip_overrides` 是过度设计，删了。`spec.compile` 现在严格 `(instance, range, ctx) → Elements`，per-candidate 数据通过 `composer.expand_for_candidate()` 一次性填进 instance dict——纯函数式模板展开。
→ **引擎层 `src/core/` 全程零修改**，news_desk 零修改，统一性保持。

### Crop bug 修复（Step 5 前）

- `03eba1f` — `_global_crop_rect` fallback 语义拍扁；Tab 1 staging 不入 config；loadedmetadata race 修

---

## 仍生效的开发约定

- prompt 改动必须 git commit
- 改 UI 布局/模块结构前 grep `docs/`（[[feedback_check_design_docs]]）
- UI 文案先 grep `src/i18n/*.json`（[[feedback_user_facing_naming]]）
- 新 `tk.Toplevel` 弹窗照 `src/ui/dialog_utils.py` docstring 模板写
- 创作**任何**新代码必须遵守 [[ADR-0003]] / [[ADR-0004]] / [[ADR-0005]]
- 创作插件访问素材数据**必须**经 Material Model（[[feedback_material_via_model_only]]）
- 每个创作的 config.json **必须**有单一内存所有者（[[project_creation_config_owner]]）
- pre-alpha 阶段，命名/迁移不要套"用户习惯/保守方案"（[[feedback_pre_alpha_no_legacy]]）
- **per-candidate 数据走模板展开，不走 ctx 隐藏通道**（5.5 教训：spec.compile 永远 `(instance, range, ctx) → Elements`，clip-specific orchestration 在 composer 层）
