# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## ▶ 下次会话主题：ComponentSpec 搬 core 欠债清理 + 项目工作台 UX 优化

根据 backlog 与已完成的测试加固，下一步我们将：
1. **重构欠债清理**: 将 `ComponentSpec` / `ImportSource` 从 `creations/news_desk/components` 搬移到 `core/composition/component_spec.py`，使 creations 和 news_desk 都从 core 统一导入，解除 creations 之间的循环依赖。
2. **项目工作台 UX + 健壮性深度优化 (🔴 P1)**: 优化 Workbench 卡片信息层级，统一 resolver 错误恢复路径，补充 i18n validator 错误提示。

### 起点 HEAD
`PositionedRect` coordinates abstraction + 350 tests passing green.

---

## 已完成（2026-05-24）

### 引擎契约凝固与各模块测试加固 🚀
- **Element 契约校验**: 在 `timeline.py` 为 `Element` 增加了 `__post_init__` 校验，在运行时彻底防范样式字段（style）嵌套泄露至 `data` 的 bug。
- **PositionedRect 坐标解耦**: 新增 `PositionedRect` dataclass 统一 drawtext/drawbox 滤镜高度坐标表达式 (`y_expr`)，安全删除了遗留的 `_block_top_y` 过程式 helper。
- **Layout 矩阵矩阵测试**: 新增 `test_layout_metrics_matrix` 锁死 YaHei / Arial 多字号下的 `font_line_height_px` 与 `measure_max_line_width_px` 计算公式。
- **组件与分析 Envelope 测试**: 新增 `test_components_shape.py` 对 clip/news_desk 所有注册组件的 `default_instance` 进行契约测试，并对 `chapters_io` normalizer Invariants（首章节合成、 degenerate 剔除、duplicate 覆盖）与 `analysis.json` 进行了 Envelope 序列化往返测试。
- **全量测试**: 测试用例从 337 个扩充至 **350 个全绿通过**（耗时 1.03s）。

---


---

## 已完成（2026-05-23 ~ 2026-05-24）

### 第二轮 dogfood patch（5 commits → push 至 `e886382`）

| Commit | 主题 |
|---|---|
| `6a4e66e` | 修 subtitle wrap budget 3 个引擎 bug（取错 key / 4.7 魔数 / 8 字下限） |
| `3868192` | wrap 端自动检测 CJK，解耦 is_chinese style flag（用户没勾选导致溢出的最后一公里） |
| `841b250` | hub auto-refresh 在 close 时取消 after-id（修 Tcl `invalid command name`） |
| `425473a` | chapter_editor 字幕预览字号 14→48 默认，max 60 |
| `e886382` | clip preset 从 CompositionStyle 切到 components-based（删 `core/composition/presets.py` + 3 处 `template_from_style` + legacy migration；4 builtins 重建） |

### 第二轮 dogfood 的 5 个引擎/UX bug

- subtitle wrap 取错 key（`fontsize` vs `fontsize_pct`）
- compute_subtitle_max_chars 残留 `ass_render_scale=4.7` 魔数
- max_chars 的 `max(8, ...)` 硬下限阻挡新路径正确算出 6
- `is_chinese` 作为 wrap 预算输入是 UX 陷阱（不勾就溢出）
- root.after 在 close 未取消

### 重构欠债剩余（继续挂着）

- **ComponentSpec 搬 `core/composition/component_spec.py`**：当前从 `creations/news_desk/components` import；纯文件移动 + import 修。独立 PR。

---

## 第一轮 dogfood 归档（2026-05-19，8 commits → `b0123be`）

| Commit | 主题 |
|---|---|
| `5de49e5` | short-edge pct 归一化（首版） + clip dogfood fixes |
| `07e0ffa` | 显式 ASS PlayRes + clip-relative cue offset in preview |
| `9dce838` | libass 指 `C:/Windows/Fonts` 找系统字体 |
| `c8ebbc0` | 字号 pct 分母从 short_edge 改回 target_h |
| `eed2c10` | 行间距 1.15 → 1.4（CJK win-metrics，临时） |
| `0a9b03e` | 行间距改 PIL 测的 ascender+descender，无魔数 |
| `86469f2` | hook/outro 统一 drawbox 背景 |
| `b0123be` | drawbox 用 `iw/ih`、drawtext 用 `w/h` |

第一轮 12 bug 三类归属：纯 clip 责任 2 / 引擎封装契约缺失 6 / 引擎自身错 4。

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
- **per-candidate 数据走模板展开，不走 ctx 隐藏通道**（5.5 教训）
- **所有视觉尺寸量归一化为 `pct of target_h`**（dogfood 教训）
- **drawbox/drawtext 的 ffmpeg 坐标常量约定不同**（dogfood 教训）
- **wrap 预算别从 user-set `is_chinese` flag 推断；从内容自动判**（第二轮 dogfood 教训）
