# Composition Timeline v0 — 设计草稿

> **状态（2026-05-17）：已转 ADR-0006 立项**。本稿作为详细参考保留——决策权威在 [`docs/adr/0006-composition-timeline-ir.md`](../adr/0006-composition-timeline-ir.md)；本稿提供 ADR 引用的"详见"细节（Axis 7.3 通道映射对照表 / 7.4 测试矩阵 / 7.5 文件迁移对照表 等）。
>
> ---
>
> 原始起源：设计中（2026-05-17 会话产出，待 Axis 7 迁移计划补完后转 ADR-0006）。
> 起因：composition 引擎当前有 5 种"画什么"输入通道散落（overlays / extra_subtitles / extra_watermarks / hook_text+outro_text / style 单例），导致 render.py 必须为各通道写特化路径、preview.py 必须为每种通道开 JS 桥方法，且新加 typed overlay 时只能靠 isinstance 调度。根因是引擎缺少统一的"场景/时间轴"IR。这份文档定义 v0 timeline IR。

---

## 设计哲学（P1~P3，定义系统形态）

**P1. Timeline 是 IR，不是 UI**
- 用户**永远看不到** track/element 视图（不做时间轴编辑器）
- 编辑入口是任务化 UI（news_desk 组件面板、clip 样式 tab、未来 PPT 流式拖块……）

**P2. Timeline 是编译产物，不是真相源**
- 真相源 = 各 component 的 instance config.json
- 每次 preview/render 由 composition 引擎"编译" component config → timeline
- AI 写的是 **component config**（component schema），不直接写 timeline
- timeline 可以频繁重生、schema 自由演化，无需考虑"用户存了 timeline 文件"的兼容性

**P3. 引擎核心优势 = AI 生成 component config + 高密度任务化 UI**
- 不是"timeline 编辑器"
- 是"让 AI 把 raw 素材 → 高质量 component config，用户在任务 UI 上微调"

## 心智模型类比

| C 生态 | composition 生态 |
|---|---|
| C 语言规范 | Primitive catalog |
| C 标准库 | 引擎随包提供的 primitives |
| 编译器前端（语法/类型检查） | compile step 的 schema 校验 |
| 编译器后端（codegen） | libass renderer + ffmpeg + preview JS |
| 汇编 / ffmpeg filter 链 + ASS 文件 | render 实际输出 |
| 应用代码（.c 文件） | 编译后的 CompositionTimeline |
| VSCode / Vim / Emacs | news_desk / clip / 未来创作类型 |

**编辑器（创作 UI）和编译器（引擎）唯一接口 = C 源码（timeline IR）**。

推论：
- creation 之间可以长得截然不同（news_desk 像 Visual Studio，clip 像 Vim），引擎统一
- AI 在 creation 层（user-level abstraction），不在引擎层（"让 AI 写汇编"是错误抽象）
- 加 primitive = 引擎级动作（C 加新关键字），加 creation = 写新编辑器（轻量）

---

## Axis 1 — 范围（Locked）

**范围内**：所有视觉元素都是 timeline element
- overlay（typed kinds）
- subtitle cue（**N 个 element**，每条 cue 一个）
- watermark（text/image）
- hook/outro 文本

**范围外**：音频混音、多源视频拼接、转场（VideoCraft 不做这些）

**subtitle = N elements 的决定**：
- 跟 P2 一致——一切都是 timed element
- 跟 chapter component（emit N 条 overlay）形态一致——单一模式胜过两种模式
- 把"batch by kind"推成 renderer 核心能力（不是 workaround）
- 未来 cue 级 AI 操作（regroup / 单 cue 替换 / 高亮某条 cue）直接作用在 timeline 一等公民上
- 成本：element 数从十几→几百几千，但 timeline 是 transient IR（P2），无压力

---

## Axis 2 — 时间模型（Locked）

**2.1 时间空间：clip-relative**
- timeline element 的 `start_sec/end_sec` 是输出视频时间（clip 0 点起算）
- 源时间 → clip 时间的换算在**编译期**一次性做掉
- 渲染器拿到的是 self-contained 数据，不查 in_sec/out_sec
- 范围外的 element 在编译期被过滤

**2.2 "常驻"元素**：`start_sec=0, end_sec=duration` 走普通 element 路径，**不引入 `always_on` 字段**

**2.3 hook/outro**：编译时变成普通 element
- hook → `Element(kind="hook_text", start_sec=0, end_sec=hook_duration, data={"text": "..."})`
- outro → `Element(kind="outro_text", start_sec=duration-outro_duration, end_sec=duration, data={...})`
- 引擎不认识"hook/outro 这种特殊概念"，只看"在某个时间点出现的文本 element"

---

## Axis 3 — 轨道模型（Locked）

**3.1 Track 是 generic**（不限制 element kind）
- chapter track 可以混 `topic_strip` + `chapter_hero_card`
- `component_kind` 字段是**标签**不是**约束**（audit/debug 用）

**3.2 Z-order = track z_base + element z_offset**
- `z_base`：track 在侧栏列表里的位置决定
- `z_offset`：element 自己声明（一般默认 0）

**3.3 Track-level enabled 级联到全部 element**
- track.enabled = False → 整 track 不参与渲染（编译期过滤）

**3.4 Track 排序**
- 编译时按 sidebar 顺序生成 track 列表（track[0] = 侧栏最上面那个）
- z_base 按 index 线性分配（如 `z_base = (index + 1) * 10`，留空隙给 z_offset）

**Track : Component instance = 1 : 1（硬约束）**
- 1 个 component instance → 1 条 track
- chapter（singleton）→ 1 track；2 个 text_watermark → 2 tracks
- 用户在 UI 关掉 component → 整 track 消失，所有 element 一起消失

---

## Axis 4 + 5 — Element schema & Style 模型（Locked）

**Element 是 generic dataclass，data/style 是 dict**（不是 per-kind 子类）

```python
@dataclass
class Element:
    kind: str                          # 注册表分发 key，必须 ∈ primitive catalog
    start_sec: float                   # clip-relative
    end_sec: float
    z_offset: int = 0
    style: dict = field(default_factory=dict)   # 编译时已 inline
    data: dict = field(default_factory=dict)    # kind 特定字段
```

不走"每个 kind 一个 Element 子类"路线。理由：P2 锁定 timeline 是 transient IR，类型安全边际收益低；AI 写的是 component config（dict），编译产出 dict 自然；renderer 通过注册表按 `kind` 分发，类型分发不靠 isinstance；加新 element kind 不需要改 Python 类层次。

**Schema 真相源 = `<Kind>Spec` dataclass**（活在 `primitives/<kind>.py`）。dataclass 是 schema 定义；dict 是搬运形式。等同 JSON Schema + JSON 的关系。

**Style library 只活在 component config 层**：
- Component config 里的 `overlay_styles` library 保留
- 编译时 component 把 `style_ref` 查表 → deep-copy 进 element.style
- Timeline 里没有 style library，只有 element 自带 style dict

---

## Primitive Catalog（引擎 vocabulary）

每个 primitive 由 **4 件套** 联合构成（缺一不可）：

| 件 | 内容 | 形态 |
|---|---|---|
| Schema | data 字段定义 | `<Kind>Spec` dataclass |
| Style Schema | 视觉样式字段 | `<Kind>Style` dataclass（可选） |
| Renderer | → libass/ffmpeg 烧录 | `register_overlay_renderer(kind, fn)` |
| Preview JS | → WebView 画 | `composition_preview.html` 里的分支 |

**初版 catalog（7 个）**：
- `subtitle_cue` — 单条字幕
- `text_watermark` — 文字水印
- `image_watermark` — 图像水印
- `hook_text` — clip 开头文本卡
- `outro_text` — clip 结尾文本卡
- `topic_strip` — 顶部话题条
- `chapter_hero_card` — 侧边章节卡

**加 primitive 是引擎级动作**：4 件套同步上线 + 可能一条 ADR 说明。不是 component 想加就加。

**物理布局**：
```
src/core/composition/
    primitives/
        __init__.py          — 注册中心
        subtitle_cue.py      — Spec + Style + render impl
        text_watermark.py
        image_watermark.py
        hook_text.py
        outro_text.py
        topic_strip.py
        chapter_hero_card.py
    timeline.py              — CompositionTimeline / Track / Element 通用 dataclass
    compile.py               — compile_timeline()
    render.py                — 主渲染循环
    preview.py               — preview 桥
    libass_helpers.py        — 共享 helper
```

---

## Axis 6 — Producer / Consumer API（Locked）

### Producer：Component 契约

```python
class ComponentInstance:        # Protocol / 接口
    kind: str                    # 创作层定义（"chapter"/"subtitle"/...）
    id: str
    config: dict
    
    def is_enabled(self) -> bool: ...
    def compile(self, clip_range: ClipRange, ctx: CompileContext) -> list[Element]: ...
```

`compile()` 契约：
- **纯函数**——无副作用、不写文件、不弹 UI、不动 self.config
- 自己负责读上游素材（通过 ctx.material_model / ctx.instance_dir / ...）
- 返回的 element：kind 必须 ∈ primitive catalog；时间必须 clip-relative；data 必须符合 `<Kind>Spec` schema
- 允许返回空列表

引擎不关心 component 怎么写、UI 长什么样、AI 怎么填——只问"给我 element 列表"。

### 引擎编译器（核心 200 行内）

```python
# core/composition/compile.py
def compile_timeline(
    components: list[ComponentInstance],
    clip_range: ClipRange,
    ctx: CompileContext,
) -> CompositionTimeline:
    tracks = []
    for i, ci in enumerate(components):
        if not ci.is_enabled():
            continue
        elements = ci.compile(clip_range, ctx)
        elements = _validate_and_clip(elements, clip_range)
        tracks.append(Track(
            id=ci.id,
            component_kind=ci.kind,
            z_base=(i + 1) * 10,
            enabled=True,
            elements=elements,
        ))
    return CompositionTimeline(
        duration_sec=clip_range.duration_sec,
        tracks=tracks,
    )
```

引擎只做 3 件事：跳过 disabled / schema validate / 范围过滤。

### Consumer 1：Preview

5 个 JS 桥消亡，统一成 1 个：

```python
class CompositionPreview:
    def set_timeline(self, timeline: CompositionTimeline) -> None: ...
    def set_source(self, src_path: str, in_sec, out_sec) -> None: ...
    def seek(self, sec: float) -> None: ...
```

JS 端只有一个 `setTimeline` 入口；按 frame tick 时遍历 timeline 找当前活跃 element，按 kind 调对应渲染分支。

### Consumer 2：Render

```python
@dataclass
class CompositionRequest:
    src_path: str
    in_sec: float
    out_sec: float
    timeline: CompositionTimeline    # 唯一"画什么"输入
    output: OutputGeometry
    crop_rect: dict | None = None
```

字段从原来 ~12 个砍到 5 个。

Render 主循环 4 步：采集活跃 element → 按 z 排序 → 按 kind 分组 → 注册表调度。**没有 isinstance，没有特殊路径**，subtitle/watermark/overlay/hook/outro 全是同一种东西。

---

## 关键不变量

- Timeline **永不持久化**（无 schema 版本兼容包袱）
- Timeline **永不被人类编辑**（无 round-trip 稳定性要求）
- 改 schema = 改编译器和 renderer（同步改），不动 component config
- Component config 是真相源，schema 演化要谨慎（用户数据在里面）

## 关键收益

- `CompositionRequest` 字段大杂烩 → 干净 5 字段
- preview.py 5 个 JS 桥 → 1 个
- render.py 主循环分支大杂烩 → 4 步规整
- component ↔ 引擎唯一接口 = `compile()` 单方法
- 加新 primitive 不动 render 主循环，只动 `primitives/<kind>.py` + preview JS 分支
- 加新 creation 类型不动引擎，符合 ComponentInstance 协议即可

---

## Axis 7.1 — 编译入口（Locked, 2026-05-17）

**Creation app 自己组装 components 列表，调引擎纯函数 `compile_timeline()`，把 timeline 喂给 preview/render。引擎不知道 caller 是谁。**

```python
# core/composition/compile.py
def compile_timeline(
    components: list[ComponentInstance],
    clip_range: ClipRange,
    ctx: CompileContext,
) -> CompositionTimeline: ...
```

### 理由

1. **匹配 C 编译器心智模型**——`gcc` 是函数不是 session；IDE 自己管状态，调编译时把源码递过去。设计哲学 P1/P2/P3 都是这个味道。
2. **clip vs news_desk 编排形状本来就不同**——clip 一次 N 个 hotclip = N 次 compile + N 个 render request；news_desk 一次 1 个。引擎里搞 Session 包不住这种差异，A 方案下"N 次 compile"就是普通 for 循环。
3. **零新抽象**——只新增一个纯函数 + 改 `CompositionRequest`/`CompositionPreview` 入参。不预设 2 个用户都不存在的 Session/Host/Facade 中间层。
4. **现状已是 A**——`_build_render_inputs()` 就长在 NewsDeskApp 上，迁移只是把"返回 4 元组"换成"返回 1 个 timeline"。

### Context 分层（同时锁）

`compile()` 是纯函数 → 不该认识 UI 回调（如 `seek_to`）。所以 ctx 分两层：

```python
# core/composition/compile.py — 引擎层
@dataclass
class CompileContext:
    project: object
    material_model: object
    instance_dir: str
    duration: float
    # 没有 UI 回调

# creations/news_desk/components/__init__.py — 创作层
@dataclass
class ProjectContext(CompileContext):
    seek_to: Callable = None    # UI 回调
```

- 引擎调 `component.compile(clip_range, ctx: CompileContext)`
- 工作台调 `component.build_property_panel(parent, ctx: ProjectContext)`

宽版 is-a 窄版，创作 app 平时持宽版对象，调 compile 时直接传过去（鸭子类型零转换）。每种创作 app 自己继承 `CompileContext` 加自家 UI 回调（PPT 可能加 `on_slide_drop`，字幕可能加 `on_cue_split`），引擎眼里永远只有 4 个纯数据字段。

### 落点（待 Axis 7.2 切 PR）

| Layer | 新增 | 改 | 删 |
|---|---|---|---|
| `core/composition/compile.py`（新） | `compile_timeline`, `ClipRange`, `CompileContext` | — | — |
| `core/composition/timeline.py`（新） | `CompositionTimeline`, `Track`, `Element` | — | — |
| `core/composition/render.py` | — | `CompositionRequest` 砍到 5 字段（带 `timeline`） | overlays/extra_subs/extra_wms/hook_text/outro_text 字段 |
| `core/composition/preview.py` | `set_timeline()` | — | 5 个老 `set_X` |
| `creations/news_desk/news_desk_tool.py` | `_rebuild_timeline()` | 2 个 render 入口 + `_push_preview` 走新 API | `_build_render_inputs`, `_rebase_overlays` |
| `creations/clip/clip_tool.py` | 同上 | 同上 | 同上 |

---

## Axis 7.2 — PR 切片（Locked, 2026-05-17）

**总策略**：strangler——新数据流跟老的并行盖好，按 creation 逐个切过去，最后一刀切掉老的。每个 PR 走完测试都绿，老路径在被替换前都还能跑。147 测试是安全网。

### 5 个 PR

| PR | 主题 | 风险 | 关键测试守护 |
|---|---|---|---|
| 1 | Timeline IR 脚手架（纯 additive） | 极低 | dataclass roundtrip + registry 单测 |
| 2 | Primitive 物理拆 + 渲染器注册化 | **中**（491 行 libass 搬家） | 现有 render 测试不动须全绿 |
| 3 | `compile_timeline()` 真实现 + Component.compile() | 低 | 4 component compile 单测 + timeline 编排 |
| 4 | News_desk 切到 timeline（render + preview） | **高** | news_desk render golden test（pixel-parity） |
| 5 | Clip 切到 timeline + 老路径删干净 | 中 | clip render golden test + 架构 grep guard |

### PR 1 — Timeline IR 脚手架

新增 `timeline.py` / `compile.py` / `primitives/__init__.py`。不动现有路径。

### PR 2 — Primitive 物理拆

7 个 primitive 各自落 `primitives/<kind>.py`（Spec + Style + libass renderer）。`news_desk_overlays.py` 整文件解散；`style.py` / `overlays.py` 里 typed overlay 迁移。`render.py` 内部由 isinstance 改 registry 分发，**外部 API 不变**。

### PR 3 — compile + Component.compile()

`ComponentInstance` Protocol 定义；news_desk 4 component 各自加 `compile()` 方法（从现有 `to_overlays()` 翻成 Element 列表）；`compile_timeline()` 完整实现。render/preview 暂不消费，只测试。

### PR 4 — News_desk 切 timeline

`CompositionRequest` 加 `timeline` 字段（可空，双路径）；`CompositionPreview.set_timeline()` 新增；news_desk 切过去，删 `_build_render_inputs` + `_rebase_overlays`。clip 仍走老路径。

### PR 5 — Clip 切 timeline + 删老路径

clip 切过去；`CompositionRequest` 删 5 个老字段；`CompositionPreview` 删 5 个老桥；架构测试加 grep guard。

### 节奏

- PR 1+2 一周内
- PR 3 独立做，跟 PR 4 之间留沉淀
- PR 4 留 buffer，准备 1 次 hotfix
- PR 5 等 PR 4 dogfood 3~5 天再开

### 不在迁移期里做

- 不动 preset 系统（刚重生）
- 不开 AI 写 component config（timeline 落地后再说）
- 不做 clip 组件化（timeline 落地后自然演化）
- 不做 element.data schema 演化（先按现有形状搬）

---

## Axis 7.3 — 5 通道 → timeline 映射（Locked, 2026-05-17）

PR 3/4/5 落地代码时照抄的对照表。

### 通道映射总表

| 老通道 | 新 Element kind | 1→N | 老字段去向 |
|---|---|---|---|
| `overlays`（typed） | 按 typed kind | 1→1 | 字段删除 |
| `extra_subtitles` | `subtitle_cue` | **1→N**（每 cue 1 element，SRT 编译期读） | 字段删除 |
| `extra_watermarks` | `text/image_watermark` | 1→1（全片常驻） | 字段删除 |
| `hook_text` / `outro_text` | `hook_text` / `outro_text` | 1→0 或 1→1 | 字段删除 |
| `style.subtitle.sub1/sub2` | `subtitle_cue` | 1→N | 搬 component config |
| `style.watermark` | `text/image_watermark` | 1→1 | 搬 component config |
| `style.hook_outro` | （编译期消化） | — | 搬 clip component config |
| `style.<overlay>_style library` | （编译期 inline 进 element.style） | — | 搬 `primitives/<kind>.py` + component config |

### Element 生成模板

**Typed overlay → Element**：原 dataclass 字段拆两类——视觉怎么画进 `style`，画什么内容进 `data`。z_order 字段消失（track 接管）。

```python
Element(kind="chapter_hero_card", start_sec=12.3, end_sec=20.0,
        style=asdict(overlay.style),
        data={"title": "...", "body": "..."})
```

**Subtitle → N Element**：1 SRT 文件 → 数百 Element。在 `component.compile()` 里读 SRT 展开，引擎 render 阶段不再读 .srt。

```python
Element(kind="subtitle_cue", start_sec=cue.start, end_sec=cue.end,
        style={"line": "primary", "position": "bottom", "fontsize": ..., ...},
        data={"text": cue.text})
```

**Watermark → Element**：常驻 = `start=0, end=duration`，不引入 `always_on` 字段（Axis 2.2）。

```python
Element(kind="text_watermark", start_sec=0.0, end_sec=duration,
        style={"text_fontsize": ..., "position": ..., ...},
        data={"text": "@channel"})
```

**Hook/outro → Element**：引擎不认识 hook/outro 概念，只看到"某时某地的文字 element"。`CompositionStyle.hook_outro` 在 timeline 层蒸发，只活在 clip component config 里。

```python
Element(kind="hook_text", start_sec=0.0, end_sec=hook_duration,
        style={...}, data={"text": hook_text})
Element(kind="outro_text", start_sec=duration-outro_duration, end_sec=duration,
        style={...}, data={"text": outro_text})
```

### 三个意外收益

1. **subtitle / watermark 两份 creation 代码合并**——clip 跟 news_desk 走同一个 primitive
2. **SRT IO 从 render 期移到 compile 期**——render 不再 touch 文件系统
3. **`CompositionStyle` 上帝对象彻底解体**——每个 primitive 的 style 跟自己代码住，clip/news_desk 的 component config 自己持

### 三个翻车点

1. **subtitle cue 必须在 `component.compile()` 里展开**——不在 `compile_timeline()` engine 主循环里展开，保持引擎不 touch SRT
2. **clip hook/outro 短 clip + 长窗口**（hook+outro > duration）必须在 compile 里夹到 [0, duration] + warn
3. **z_order 字段全删**——现有代码每个 spec 上都有，迁移时统一删，由 track 在 `compile_timeline()` 按 component 列表 index 分配 `z_base = (i+1) * 10`，element 默认 `z_offset=0`

---

## Axis 7.4 — 测试改造策略（Locked, 2026-05-17）

**关键现实**：现有 147 测试**零覆盖 `core/composition/`**。全在 materials + news_desk config/presets + 架构 grep。clip 2000 行 0 测试。timeline 迁移正好是第一次给引擎加测试。

### 四象限

| 象限 | 性价比 | 角色 |
|---|---|---|
| A. 纯数据测试 | 高 | 每 PR 同步加，主力 |
| B. 行为保持（**ASS-text 等价**） | 高 | PR 2/4/5 安全网 |
| C. 架构 grep guard | 极高 | 锁死设计约束 |
| D. pixel-exact golden | 低 | **不做** |

### 关键决策：放弃 pixel-golden，换 ASS-dialogue 文本等价

**为什么不要 pixel-golden**：libass/字体版本一变 byte 漂移；跨平台跑路径不同；真出 bug 时 ASS-text diff 同样能定位且**告诉你哪行错了**。

**ASS-text 方案**：`render.py` 抽"生成 ASS 文件内容"纯函数（不调 ffmpeg），fixture input → golden 文件 byte-equal。libass 确定性 → ASS 等价 ≈ 视频等价。

**PR 2 隐性前置**：先抽 ASS 生成纯函数（小 commit），再搬 primitive（大 commit），同 PR 两步。

### 测试新增分配

| PR | A 纯数据 | B ASS-text | C 架构 | 累计 |
|---|---|---|---|---|
| 起点 | — | — | — | 147 |
| PR 2 准入（main 上先跑） | — | **+8 golden 文件** | — | 147 |
| PR 1 | +12 | — | +2 | 161 |
| PR 2 | +14 | +8 | +5 | 188 |
| PR 3 | +20 | — | — | 208 |
| PR 4 | +6 | +3 | +2 | 219 |
| PR 5 | +8 | — | +3 | 230 |

**净增 ~70 测试 + 11 ASS golden 文件**。composition 引擎从 0 到 ~70 测试。

### 三条落地纪律

1. **golden 不准手编**——必须从未改动 main HEAD 跑出来落盘，再开始改代码
2. **PR 拒收 `@pytest.skip` / `xfail`** 进 timeline 相关代码（[[feedback_pre_alpha_no_legacy]]）
3. **老 147 测试全保留**——跟 timeline 正交；PR 4/5 改 tool 时按需更新 grep 字符串断言

### 不做清单

- 测 `_build_render_inputs` 直接行为（PR 4 删的代码）
- 测老 5 通道端到端 ffmpeg 输出（PR 5 后路径不存在）
- 跨 PR 共享 fixture 装大型 mock framework（每 PR 自带 fixture，互不依赖）

---

## Axis 7.5 — 文件物理迁移（Locked, 2026-05-17）

### 目标目录

```
src/core/composition/
    __init__.py                — 重写 re-exports
    timeline.py                — NEW: Element / Track / CompositionTimeline
    compile.py                 — NEW: compile_timeline / ClipRange / CompileContext / Protocol
    render.py                  — 瘦身: CompositionRequest(5 字段) + render + dispatch (~350 行)
    preview.py                 — 瘦身: CompositionPreview.set_timeline() (~150 行)
    libass_helpers.py          — NEW: 共享 libass 工具 + BaseTextStyle
    layout.py / text_layout.py / fonts.py / presets.py  — 不变
    primitives/
        __init__.py            — registry: register_overlay_renderer / dispatch
        subtitle_cue.py
        text_watermark.py / image_watermark.py     — 两 primitive 各窄 Style（无 type discriminator）
        hook_text.py / outro_text.py               — 两 primitive 各窄 Style
        topic_strip.py / chapter_hero_card.py
```

### 删除清单

- **`style.py` 整文件**（365 行）——`CompositionStyle` 解体，子 style 各归 primitive
- **`overlays.py` 整文件**（130 行）——typed overlay 归 primitive，`Element` 是新 generic
- **`news_desk_overlays.py` 整文件**（491 行）——核心痛点终结，libass 主体归 primitive，helper 归 `libass_helpers.py`
- **`render.py` 大半**：`ExtraSubtitleSpec` / `ExtraWatermarkSpec` / per-kind renderer / `_load_cues` 等 → 各归 primitive

### `style.py` → 7 处去向

| 符号 | 去向 |
|---|---|
| `SubtitleLineStyle` / `SubtitleStyle` / `compute_subtitle_max_chars` / `effective_max_chars` | `primitives/subtitle_cue.py` |
| `WatermarkStyle`（带 `type` discriminator） | **拆** → `primitives/text_watermark.py` + `image_watermark.py` 各持窄 Style；render.py 4 处 `wm.type` 分支 + preview.html JS 分支全消 |
| `HookOutroStyle`（hook+outro 共享 + 各自字段） | **拆** → `primitives/hook_text.py` + `outro_text.py`；共享字段经 `libass_helpers.BaseTextStyle` 继承 |
| `OutputGeometry` | `render.py`（engine-level） |
| `TopicStripStyle` / `ChapterHeroCardStyle` | 各自 primitive |
| `CompositionStyle` / `resolve_overlay_style` / `default_overlay_styles` | **删除** |

### `news_desk_overlays.py` → 完全解体

| 符号 | 去向 |
|---|---|
| `_ass_alpha` / `_ass_time` / `_ass_escape_text` / `_est_text_width_px` / `_rect_dialogue` / `_text_dialogue` | `libass_helpers.py` |
| `_wrap_text_cjk_n` | `text_layout.py` |
| `_build_topic_strip_dialogues` | `primitives/topic_strip.py` 渲染主体 |
| `_build_chapter_hero_card_dialogues` | `primitives/chapter_hero_card.py` 渲染主体 |
| `build_news_desk_ass` | 拆——orchestration 留 render.py，per-kind 自注册 |
| `_renderer_news_desk_ass` / `register()` | **删除** |

### `render.py` 979 → ~350 行

per-kind 渲染器全迁出（`_renderer_subtitle_libass` / `_image/text_watermark` / `_hook/outro_text` / `_build_subtitle_force_style` / `_track_margins` 等）；`prepare_subtitle_cues` + `_load_cues` 迁到 `primitives/subtitle_cue.py`（SRT IO 编译期化）；`_named_overlay_jobs` 重写为 timeline walker；libass 通用 helper（`_ass_bgr_with_alpha` / `_escape_drawtext` / `_hex_to_drawtext_rgba`）归 `libass_helpers.py`。

### 各 PR 物理变化

| PR | 新增文件 | 修改 | 删除 |
|---|---|---|---|
| PR 1 | timeline.py / compile.py / primitives/__init__.py | — | — |
| PR 2 | libass_helpers.py + 7 primitive | render.py / __init__.py | **style.py / overlays.py / news_desk_overlays.py** |
| PR 3 | — | compile.py / news_desk components | — |
| PR 4 | — | render.py（双路径）/ preview.py / news_desk_tool.py | — |
| PR 5 | — | clip_tool.py / render.py（删老路径）/ preview.py（删 5 桥） | — |

**PR 2 是物理变化最大的一环**——一次删 3 文件 + 加 8 文件 + 改 render.py。ASS-text golden 是它能 land 的唯一证据。

### Primitive 统一骨架

```python
# primitives/<kind>.py
KIND = "<kind>"

@dataclass
class <Kind>Spec:  ...     # data 字段（画什么）

@dataclass
class <Kind>Style: ...     # style 字段（怎么画）

def _render(job, prev_label, ctx): ...   # registry 调

register_overlay_renderer(KIND, _render)
```

每文件 150~250 行（subtitle_cue 最大；text_watermark 最小）。

### WatermarkStyle / HookOutroStyle 拆分决定（已锁）

两个 dataclass 都来自 clip 时代"用户挑 type"心智模型。news_desk 在 component 层拆了但**引擎数据层没拆**——继续往老 `WatermarkStyle(type=...)` 喂。timeline 时代两 primitive 各持窄 Spec/Style，`type` discriminator 消失，render 4 分支 + preview JS 分支同步消失。共享字段（font/color）经 `libass_helpers.BaseTextStyle` 继承复用。

---

## Axis 7.6 — ADR-0006 起草（草稿，本会话末归档）

设计 lock 完成。下次会话或本会话末把以下骨架填进 `docs/adr/0006-composition-timeline-ir.md`，正式立 ADR 后本设计稿降级为"参考实现细节"。

### 骨架

```
# ADR-0006: Composition Engine Timeline IR

- 状态: Active
- 决定日期: 2026-05-1X
- 取代: 隐式"5 通道直喂 render"协议（无 ADR 记录，活在 CompositionRequest 字段里）

## 决定

Composition 引擎引入统一 timeline IR：所有"画什么"输入收编为
CompositionTimeline = list[Track], Track = list[Element]。
Element 按 kind 字符串走 primitive registry。Component 与引擎间唯一接口 =
compile(clip_range, ctx) → list[Element]。Timeline transient（不持久化、不给人编辑），
真相源是各 component 的 instance config。

## 为什么

### 触发痛点
- CompositionRequest 12 字段大杂烩（5 个"画什么"通道散落）
- render.py 主循环必须 isinstance 分发，加 typed overlay 改一次主循环
- preview.py 5 个 JS 桥，每个通道一座
- news_desk_overlays.py 491 行让 core 认识 news_desk（违反 ADR-0004）
- subtitle 是文件 path、watermark 是 spec、hook/outro 是字符串字段——同等"画什么"却三种形态

### 为什么 timeline IR 而非加 typed channel
- 5 通道 → 6 通道 → N 通道是无止境的私有协议增殖
- 统一 IR 把"画什么"的语义抽象到引擎的核心 vocabulary
- AI 生成是设计哲学 P3 的核心承诺——AI 写 component config 比 AI 写 timeline 自然得多
  （编辑器写源码 vs AI 写汇编）

### 为什么不持久化 timeline
- 真相源是 component config（用户数据）；timeline 是它的编译产物
- 编译产物频繁重生 → schema 演化无包袱
- 用户从来看不见 timeline → 无 round-trip 稳定性要求

## 关键不变量

- Timeline 永不持久化、永不被人类编辑
- Component.compile() 是纯函数（无副作用、不写文件、不弹 UI）
- Element.kind ∈ primitive catalog；编译期 schema validate
- 加 primitive = 引擎级动作（Spec + Style + libass renderer + preview JS 四件套）
- 加 creation = 写新"编辑器"（实现 ComponentInstance 协议即可）

## 设计哲学（核心三条）

P1. Timeline 是 IR，不是 UI（编辑入口是任务化 UI，不是时间轴编辑器）
P2. Timeline 是编译产物，不是真相源
P3. 引擎核心优势 = AI 生成 component config + 高密度任务化 UI

心智类比：C 编译器（引擎）/ 源码（component config）/ 汇编（render 输出）/
IDE 各异（news_desk / clip / 未来创作类型）。

## 不在范围

- 不做时间轴 UI（P1 直接排除）
- 不做 timeline 持久化 / 用户可编辑 timeline（P2 直接排除）
- 不做引擎层 AI 写 timeline（P3 直接排除——AI 写 component config）
- 不引入音频混音、转场、多源拼接（VideoCraft 不做）

## 迁移

5 PR strangler；详见 docs/design/composition-timeline-v0.md。

## 参考

- 完整设计：docs/design/composition-timeline-v0.md
- 关联 ADR：[ADR-0003] [ADR-0004] [ADR-0005]
- 关联记忆：[[project_composition_core]] [[project_composition_timeline_v0]]
```

### 起草纪律

1. **写 ADR 前 PR 1 必须 land**——ADR 引的代码符号（`CompositionTimeline` / `compile_timeline` / `CompileContext`）至少在仓里存在，避免 ADR-vs-code 漂移
2. **决定日期 = ADR commit 日期**（不是设计 lock 日期）
3. **ADR 立完后** `docs/design/composition-timeline-v0.md` 顶部加 "Status: 已转 ADR-0006，本稿作为详细参考保留" 一行

## 起点状态

- HEAD: `eaa83fc`（"composition: scrub dead overlay kinds"，已 push origin/main）
- 147 测试全绿
- 2 个剩余 typed overlay（`TopicStripOverlay` + `ChapterHeroCardOverlay`）在 v0 设计里都成为 primitive，迁移期不删
- libass dialogue builders（`_build_topic_strip_dialogues` / `_build_chapter_hero_card_dialogues`）迁移到对应 primitive 文件
