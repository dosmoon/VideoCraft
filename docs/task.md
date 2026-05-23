# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## ▶ 下次会话主题：composition 引擎自动化测试覆盖

clip 第一轮 dogfood 跑完（2026-05-19，8 commit 已 push 至 `b0123be`）。引擎层暴露了一连串契约模糊 + 魔数校准问题，已逐个修掉，但**留下来真正该补的是引擎自身的测试薄弱**——所以下一轮专门做这件事。

### 2026-05-23 dogfood 第二轮 patch（已修但未 commit）

用户报"字幕两边超出导出 mp4"。复合 3 个引擎 bug：

1. `render.wrap_subtitle_elements` 取 `style["fontsize"]`（默认 24），但 component schema 写 `fontsize_pct` → 字号假命中默认。
2. `style.compute_subtitle_max_chars` 仍带 `ass_render_scale = 4.7` 魔数（commit `07e0ffa` 已显式 PlayRes 后该魔数失效）。
3. `compute_subtitle_max_chars` 末尾 `max(8, …)` 硬下限——old 4.7 路径下保护性的下限，新路径下反而把真正想要 6 chars/line 的 case 抬到 8，仍溢出。

修法：`render.py` 读 `fontsize_pct` 并按 target_h 转 px；`style.py` 删 4.7，下限改 2。回归测试见 `tests/creations/test_clip_subtitle.py::test_wrap_subtitle_elements_keeps_cues_within_frame_width`（318 → 333 测）。这条正好就是 engine_test_initiative 第 1 项"12 bug 各回填一个测试"开了第一个口。

### 三个目标（同等重要）

1. **持续正确性**：当前 332 测试主要覆盖 timeline IR / wrap 单源 / golden 字符串。引擎核心的"pct → px 换算 / drawbox vs drawtext 坐标常量 / 字体度量驱动行高 / cue 时间基准 / Element.style/data 契约"几乎没有单元测试。dogfood 暴露的每一类 bug 都该补对应的 test，回归屏障建起来。

2. **测试即文档**：写测试的过程强制 **把现在散落在注释/约定里的引擎契约凝固成可执行的断言**。包括：
   - Element.style = 视觉，Element.data = 内容（约束 hook_outro 不要再把 style 塞 data 里）
   - pct 字段的分母语义（fontsize_pct / stroke_pct / box_padding_pct → target_h；block_margin_pct → target_h；margin_x/y_pct → target_w/target_h）
   - drawbox 的 `iw/ih` vs drawtext 的 `w/h` 坐标常量（封一层 wrapper 让 caller 不用记）
   - cue 时间基准：timeline IR 是 clip-relative，preview JS 需要 -clipStart 后再比较

3. **测试即设计控制**：把"应该有的不变量"用测试钉死（preview 和 render 在同一参数下产生的可对比量必须 byte-equal 或 px-equal），任何回退被自动捕获。

### 入手顺序建议

1. 把 dogfood 这轮发现的 12 个 bug 各回填一个 reproduction 测试（best regression coverage）
2. 给 Element 加 `__post_init__` 契约校验 + 对应单元测试
3. 抽出 `PositionedRect.to_drawtext()` / `to_drawbox()` 两个方法封装坐标常量差异 + 测试
4. 给 `core/composition/layout.font_size_px` / `font_line_height_px` 写明确的单元测试（多字体多 size 覆盖）

### 引擎契约扫雷清单（dogfood 出的）

详见 [[project_composition_core]] 更新后的"契约总览"段落。

### 起点 HEAD

`b0123be` "composition: drawbox uses iw/ih (not w/h) for video dims"，已 push origin/main。
**332 测试全绿；7 个 goldens（含 hook/outro/subtitle/watermark/news_desk_ass 4 类）**。

---

## 已完成（本轮会话，2026-05-19）

### clip dogfood 第一轮 → 8 commit pushed

| Commit | 主题 | 类型 |
|---|---|---|
| `5de49e5` | short-edge pct 归一化（首版） + clip dogfood fixes（_current_style / subtitle "language" / hook bg / dual sub stack） | engine + clip |
| `07e0ffa` | 显式 ASS PlayRes + clip-relative cue offset in preview | engine bug |
| `9dce838` | libass 指 `C:/Windows/Fonts` 找系统字体 | engine 漏配 |
| `c8ebbc0` | 字号 pct 分母从 short_edge 改回 target_h（垂直量） | engine 设计错 |
| `eed2c10` | 行间距 1.15 → 1.4 通过 CJK win-metrics（中间步） | 临时凑合 |
| `0a9b03e` | 行间距改用 PIL 测的字体 ascender+descender，无魔数 | engine 治本 |
| `86469f2` | hook/outro 统一 drawbox 背景（PIL 测最宽行），不再各画各 box | engine 封装补 |
| `b0123be` | drawbox 用 `iw/ih`、drawtext 用 `w/h`（filter 常量约定不同） | engine API 使用错 |

### dogfood 出的 12 个 bug 三类归属

- **纯 clip 责任（2）**：`_current_style` 遗留、subtitle `track:primary/secondary` 过度设计
- **引擎封装/契约缺失（6）**：Element 约定未强校验、cue 时间基准未文档化、stacking 共享未指定、drawtext 多行能力暴露不对称、bg 抽象缺失、字体解析双轨
- **引擎自身有错（4）**：`ASS_RENDER_SCALE=4.7` 魔数、PlayResY 默认假设、字号分母选错、行高魔数

### Step 5 重构欠债（继续挂着）

- ComponentSpec / ComponentDictAdapter 物理搬到 `core/composition/component_spec.py`
- ~~`template_from_style` 三处 legacy migration~~ — **已删除（2026-05-23）**
- ~~预设 schema 改成 components-based~~ — **已完成（2026-05-23）**：`creations/clip/presets.py`，apply 替换 config.components；老 `core/composition/presets.py` 已删；4 个 builtins 重新基于 components

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
- **所有视觉尺寸量归一化为 `pct of target_h`**（dogfood 教训：fontsize_pct / stroke_pct / box_padding_pct，详见 [[project_composition_core]]）
- **drawbox/drawtext 的 ffmpeg 坐标常量约定不同**（dogfood 教训：drawbox 用 `iw/ih`、drawtext 用 `w/h`；未来用 wrapper 封掉）
