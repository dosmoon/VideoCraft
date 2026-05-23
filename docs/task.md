# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## ▶ 下次会话主题：引擎 + 各模块单元测试补全

clip 第二轮 dogfood 走完（2026-05-23/24）。功能"基本能用，可用"——产品形态收敛，回到把测试补厚的工作。

### 起点 HEAD

`e886382` "clip: components-based preset store"，已 push origin/main。
**337 测试全绿；7 个 goldens。**

### 这轮要做什么

1. **复盘 12 个 dogfood bug，每个回填一个 reproduction 测试**
   - 已经开了头（subtitle wrap 那条 + CJK 自动检测那条，共 2 个）。
   - 还差 10 条，按 [[project_composition_core]] "契约总览" 清单走。

2. **引擎契约用测试钉死**（测试即文档）
   - `Element.__post_init__` 校验 kind/style/data 形状
   - pct 字段分母语义：`fontsize_pct / stroke_pct / box_padding_pct → target_h`，`margin_x_pct → target_w`，`margin_y_pct → target_h`
   - `PositionedRect.to_drawtext()` / `to_drawbox()` wrapper 封 `iw/ih` vs `w/h` 常量差
   - cue 时间基准：timeline IR clip-relative；preview JS 需要 `-clipStart` 后比

3. **各模块单元测试补全**（不仅是引擎）
   - `creations/clip/composer.py` `expand_for_candidate` 模板展开 corner case
   - `creations/clip/presets.py` 已补 14 测，但缺端到端 apply 后 cfg.components 形状 assert
   - `creations/news_desk/` 各 component 的 default_instance + compile 形状
   - `materials/news_video/` chapters_io / context.json envelope round-trip
   - `core/composition/layout.font_size_px` / `font_line_height_px` 多字体多 size 矩阵

4. **preview ≡ render 不变量**：把"应该有的不变量"用测试钉死。preview 和 render 在同一参数下产生的可对比量必须 byte-equal 或 px-equal。

### 入手顺序建议

1. 12 个 bug 各回填一个 reproduction（最高 ROI）
2. Element + `PositionedRect` 契约校验类
3. layout 计算函数的矩阵测试
4. 各 creation 模块往下挖

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
