# clip 重构 Step 5 — 组件化迁移设计

> 状态：草稿，待对齐
> 关联：[[project_clip_refactor_debt]] · ADR-0003 · ADR-0006
> 前置：Step 1-4 已 land（`fada901`），clip_tool.py 1135 行，5 子模块

## 1. 目标

把 clip 现在用 `CompositionStyle` 单 dataclass 驱动的 hook / outro / subtitle / watermark，重构成跟 news_desk 同构的 `ComponentSpec` 注册模型。让 clip 共享 timeline IR + component 抽象，最终 `build_clip_timeline()` 退役、走 `compile_timeline(adapters, clip_range, ctx)` 单路。

## 2. 关键判定（先回答这些再动代码）

### 2.1 1-to-many vs 1-to-1：component 抽象能承载吗？

**能。** news_desk 是"一个项目 → 一条 timeline"，clip 是"一个项目 → N 个 candidate，每个 candidate 一条 timeline"。整套模型就是：用户编辑一份**模板**（component instance dict 列表），render 时给每个 candidate 实例化一份**具体**的 instance 列表（填上这个 candidate 的 hook 文案 / SRT 路径等），喂给同一个 `compile_timeline()`。

```python
for cand_idx in selected_candidates:
    start, end = effective_start_end(cand_idx)
    clip_range = ClipRange(start, end)
    # 模板 + 这个 candidate 的数据 → 具体 instance dicts
    concrete = expand_template_for_candidate(
        config.components,
        hook_text=effective_hook(cand_idx),
        outro_text=effective_outro(cand_idx),
        source_srt=resolve_source_srt(),
    )
    timeline = compile_timeline(
        [ComponentDictAdapter(c) for c in concrete],
        clip_range,
        ctx,   # vanilla CompileContext
    )
    render_one(cand_idx, timeline)
```

### 2.2 per-candidate 数据（hook_text / outro_text / title / SRT 路径）怎么传？

**填到具体 instance dict 里，不进 ctx。**

`spec.compile(instance, clip_range, ctx)` 永远从 `instance` 自包含读完所有数据，ctx 保持 vanilla `CompileContext` 不动。"模板填充器"（`expand_template_for_candidate`）是个普通函数，住在 clip 层，负责把项目级模板（user-edited components）+ 这个 candidate 的特殊数据，深拷贝 + 字段填充出一份具体 instance dicts。

跟 news_desk 的 chapter（内容来自分析 JSON，spec 只配样式）思路一致：spec 配"长啥样"，per-candidate 数据由填充器写进 instance。区别只是 news_desk 是"1 个项目 1 次填充"，clip 是"N 个 candidate N 次填充"。

**关键好处**：
- `spec.compile` 是纯 `(instance, clip_range, ctx) → Elements`，零隐藏通道，跟 news_desk 完全同构
- 引擎层 `CompileContext` 不需要扩展，不需要 clip 子类
- 5.1 / 5.2 实际上已经是这套——`subtitle_adapters_from_style()` 就是填充器的雏形（虽然名字叫 "seeder"）

### 2.2.1 已落地：5.1 / 5.2 模式

`subtitle_adapters_from_style(style, source_srt, source_srt_secondary)` 和 `watermark_adapters_from_style(style)` 就是按这套模式工作的小填充器。5.5 替换 UI 后，这些会合并成统一的 `expand_template_for_candidate(template, ...)`。

### 2.3 hook + outro 是 1 个 component 还是 2 个？

**2 个独立 spec**：`hook_text_card` / `outro_text_card`。

理由：
- ADR-0006 已经把 `hook_text` / `outro_text` 定为 2 个独立 primitive kind
- one ComponentSpec = one render layer = one list-row in UI 这套语义干净
- 用户未来可以"只用 hook 不用 outro"，不会被强绑
- 共享样式 (font/size/color/stroke/bg) 走 helper 函数复用代码，不在 spec 层耦合
- default_z 接近（hook 90 / outro 90），用户看 component list 时两条连在一起

### 2.4 hotclips 候选列表算 component 吗？

**不算。** hotclips 是上游 AI 输出的素材数据（pre-component），跟 news_desk 的 analysis.json 同位。它是 `ctx.material_model` / `HotclipsRepo` 提供的，不是 user-editable 的项目级模板。

每个 candidate 在 render 时通过 ctx 暴露给 spec.compile()——hotclips 列表本身不参与 component 化。

### 2.5 subtitle 复用 news_desk 那一份吗？

**不复用，clip 自己写 `ClipSubtitleSpec`。**

理由：
- clip 需要双轨 (sub1 + sub2)，margin_v 必须根据两轨共存自动算（`track_margins(sub)`）
- clip 的 srt 来源是 `material_model.get_srt_path(lang)`（动态、外部）；news_desk subtitle 设计是"用户导入 srt 进 instance_dir"的快照模型，两者数据流不一样
- 共享是在 **primitive 层**（`subtitle_cue` Element + render-side libass）就够了，不强求 spec 复用

用户体验：用户在 component list 里看到「主语言字幕」「副语言字幕」两条，每条独立配字号/颜色/位置。

### 2.6 text_watermark / image_watermark 复用？

**复用。但搬到共享层。**

news_desk 的 text_watermark / image_watermark spec 跟 news_desk 业务零耦合（schema 只有 text/fontsize/color/position/margin 这些纯样式字段）。

**做法**：新建 `core/composition/components/`（共享 component 库），把这 2 个 spec 物理搬过去，news_desk 改 import。clip 也从同一处 import 注册。

风险/成本：news_desk 那边要改 4 处 import + 1 处 ImportSource handler（event_date 那个目前依赖 `ctx.material_model.read_context()`，这是 news_video 专属 API——这个 import_sources 项 clip 不需要，留 news_desk 自己 wrap）。

**替代方案**：第一版先不搬，clip 写自己的 2 份小重复（每份 ~80 行）。设计纯净度差一点，但 Step 5 内部不引入跨 tier 改动。建议先用替代方案，搬运放 Step 6 或独立后续。

### 2.7 ComponentSpec dataclass 复用？

**短期复用，长期搬 core。**

`ComponentSpec` / `ComponentDictAdapter` / `register` 现在住在 `creations/news_desk/components/__init__.py`，跟 news_desk 业务零耦合。

第一版 clip 直接 `from creations.news_desk.components import ComponentSpec, ComponentDictAdapter, register`——破坏 tier 边界但实用。Step 5 完成后再做"抽到 `core/composition/component_spec.py`"的 follow-up。这个搬运纯文件移动 + import 路径修，独立 PR，零行为差。

## 3. UX：StylePanel 怎么改？

**核心矛盾**：clip 用户的心智是"配一套样式，应用到所有 candidate"，跟 news_desk 的"项目级编辑"语义一致——所以 clip 也用 news_desk 的 component-list UI 完全合理。

### Tab 1 新结构

跟 news_desk 完全同构——左列竖分（上预览 / 下组件列表），右列属性面板。

```
┌──────────────────────────────────────────────────────────┐
│ [顶部工具区] 预设：[combo] [应用] [另存] [覆盖]            │
├──────────────────────────────────────────────────────────┤
│  [预览]                          │                       │
│   WebView                        │  [属性面板]            │
│   + 全局裁剪覆盖层                │  (选中组件后动态生成)  │
│   + [应用裁剪到所有 clip]         │                       │
│ ─────────────────────────────    │                       │
│  [组件列表]                       │                       │
│   ├ 主语言字幕    ☑              │                       │
│   ├ 副语言字幕    ☐              │                       │
│   ├ Hook 卡片     ☑              │                       │
│   ├ Outro 卡片    ☑              │                       │
│   ├ 文字水印      ☑              │                       │
│   └ [+ 添加] 菜单                 │                       │
└──────────────────────────────────────────────────────────┘
```

- 左上 = 预览（WebView，全局裁剪样板作为覆盖层）
- 左下 = 组件列表（Treeview）+ [+ 添加] 菜单
- 右侧 = 选中组件的 property panel（`spec.build_property_panel`）
- 顶部独立工具条 = 预设管理（clip 专属，news_desk 没有这一条）
- 全删 StylePanel 现有 800 行 form
- 全局裁剪样板贴预览栏（staging → 按钮派发到所有 clip），跟刚改完的语义匹配

### Tab 2 不动

Tab 2 是 per-candidate 编辑（hook/outro 文案、时间窗、裁剪 override），跟 component 模型正交。保持现状。

## 4. 预设兼容怎么办？

**痛**：clip 现有预设结构是 `CompositionStyle dict`。component 化后预设变成 `{components: [...]}`。

**方案**：pre-alpha 阶段 → 不做迁移 shim，直接换 schema。预设清掉重新存（用户量为 0）。

记忆里 [[feedback_pre_alpha_no_legacy]] 已经允许这种判断。Step 5 同 PR 里清掉 `creations/clip/presets.py`（或重写成 component dict 装载）。

## 5. 迁移分步（推荐顺序）

每步独立可 commit，每步跑 270+ 测试 + goldens。

### Step 5.0 — 脚手架（~半天）
- 新建 `creations/clip/components/__init__.py`，从 news_desk 借 `ComponentSpec` / `register` / `REGISTRY` / `ComponentDictAdapter` / `ProjectContext`
- 加 `CompileContext.clip_overrides` 字段
- `ClipInstanceConfig` 加 `components: list[dict] = field(default_factory=list)`
- **不改任何渲染路径**，build_clip_timeline 仍然主导

### Step 5.1 — subtitle 迁（~1 天）
- 写 `creations/clip/components/subtitle.py`，`ClipSubtitleSpec` 双轨能力
- StylePanel 字幕区改成 component list 项（先只支持 subtitle 一种 kind）
- build_clip_timeline 字幕部分改成调 spec.compile()
- 字幕 goldens 全绿

### Step 5.2 — watermark 迁（~半天）
- 写 `text_watermark.py` / `image_watermark.py`（复用方案先选"自己写一份"，不动 news_desk）
- StylePanel 水印区改成 component list
- build_clip_timeline 水印部分改成调 spec.compile()

### Step 5.3 — hook + outro 迁（~1 天）
- 写 `hook_text_card.py` / `outro_text_card.py`，2 个独立 spec
- ctx 注入 per-candidate text 走通
- StylePanel hook/outro 区改成 2 个 component list 项

### Step 5.4 — build_clip_timeline 退役（~半天）
- render 入口换成 `compile_timeline(adapters, clip_range, ctx)`
- 删 `creations/clip/timeline_builder.py`
- 测试 + goldens 全绿

### Step 5.5 — StylePanel UI 收尾（~1 天）
- 砍掉旧 form（800 行 → ~100 行 + property pane）
- [+ 添加] 菜单
- 预设 schema 切到 components dict
- 删 `CompositionStyle` 在 clip 的所有 callsite（这就是原 task.md 的 Step 6）

**总预算**：4-5 天。可压可拆。

## 6. 验收（每步）

- 270+ 测试全绿
- 9 goldens byte-equal
- `tests/test_arch_clip.py` 加对应 guard（如 "subtitle 必须经 component spec 出 Element"）
- preview ≡ render 不变量（ADR-0006 #6）

## 7. 不在范围内（推后）

- ComponentSpec / Adapter 物理搬到 `core/composition/component_spec.py`
- text/image_watermark spec 共享层
- bilingual_video / 其他形态的 component 化
- 拆 `WatermarkStyle` / `HookOutroStyle` 成窄 primitive style（原 PR 5 deferred 第 3 项）

## 8. 待定（请用户拍板）

1. **Step 5.5 的 UI 重做要放同一 PR 还是分阶段？** 建议分阶段：Step 5.1-5.4 期间 StylePanel 保留双轨（旧 form + component list 并存），Step 5.5 才砍旧的。降低中途破坏面。
2. **text/image_watermark 复用方案**：先重复写还是直接搬 core？建议先重复（保 Step 5 边界），搬运独立 follow-up。
3. **预设清盘要不要给用户提示**？pre-alpha 阶段倾向不提示直接换。
