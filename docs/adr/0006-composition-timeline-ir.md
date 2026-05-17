# ADR-0006: Composition Engine Timeline IR

- **状态**: Active
- **决定日期**: 2026-05-17
- **取代**: 隐式"5 通道直喂 render"协议（无 ADR 记录，活在 `CompositionRequest` 字段里）

## 决定

Composition 引擎引入统一 **timeline IR**：所有"画什么"输入收编为
`CompositionTimeline = list[Track]`，`Track = list[Element]`。`Element` 按 `kind`
字符串走 primitive registry 分发——render 主循环无 `isinstance`，无 per-channel 分支。
Component 与引擎间唯一接口 = `compile(clip_range, ctx) → list[Element]`。
Timeline 是 **transient IR**——不持久化、不被人类编辑、不进 git；真相源是各
component 的 instance `config.json`，每次 preview/render 现编译。

## 为什么

### 触发痛点

`core/composition/` 演化到本 ADR 之前已经有 5 种"画什么"输入通道并存在
`CompositionRequest` 上：

- `overlays` — typed overlay 列表（news_desk: chapter_hero_card / topic_strip）
- `extra_subtitles` — news_desk 多轨字幕，引擎按 SRT 路径读
- `extra_watermarks` — news_desk 多水印
- `hook_text` / `outro_text` — clip 专属字符串字段
- `style` 单例（`CompositionStyle`）— clip 时代上帝对象，里面藏着 sub1/sub2、watermark、hook_outro 配置 + 跨 creation 共享的 overlay style library

这种增殖产生几个具体毒：

1. `render.py` 主循环用 `isinstance` 对 typed overlay 分发，**新加一种 overlay 就要改主循环**
2. `preview.py` 为每个通道开一个 JS 桥方法（`set_overlays / set_cues / set_cues_secondary / set_style / set_hook_outro`），**新加通道就要新加桥**
3. `core/composition/news_desk_overlays.py` 491 行——**core 认识 news_desk** 这个特定 creation，违反 ADR-0004 三层架构
4. 同等"画什么"语义被表达成完全不同形态：subtitle 是文件路径、watermark 是 spec 对象、hook/outro 是字符串、chapter card 是 typed dataclass——AI 想生成或用户想编辑必须每种学一遍
5. `CompositionStyle` 是上帝对象：clip 用它管 sub1/sub2，news_desk 又把它的 sub1/sub2 强行 disabled 走自己 N-track 路径；两个 creation 都被它绑住但都不舒服

### 为什么是 timeline IR 而不是"再加一个 typed channel"

每加一种"画什么"形态——比如未来的 lower_third 名牌、PPT 内嵌幻灯片、动态 ticker
——继续走"再加一个 `CompositionRequest` 字段 + 一座 preview JS 桥 + 一段
isinstance 分支"的路是无止境的私有协议增殖。把"画什么"的语义抽到引擎核心
vocabulary（`Element` + primitive registry），每加一种就是加一个 primitive 文件 +
注册一个 renderer，**不动主循环**。

### 为什么 timeline 不持久化

- 真相源是 component instance config（用户数据，schema 演化要谨慎）；timeline 是它的编译产物
- 编译产物可以频繁重生、schema 自由演化——**没有 round-trip 兼容包袱**
- 用户从来看不见 timeline，不会"存了一个 timeline 文件下次想打开" → 没有持久化形态需求
- AI 生成的是 component config（高层意图），不是 timeline（低层布局）——这是设计哲学 P3 的核心承诺

### 心智模型：C 编译器类比

| C 生态 | composition 生态 |
|---|---|
| C 语言规范 | Primitive catalog |
| C 标准库 | 引擎随包提供的 primitives |
| 编译器前端（语法/类型检查） | compile step 的 schema 校验 |
| 编译器后端（codegen） | libass renderer + ffmpeg + preview JS |
| 应用代码（.c 文件） | 编译后的 `CompositionTimeline` |
| VSCode / Vim / Emacs | news_desk / clip / 未来创作类型 |

Creation（编辑器）和引擎（编译器）唯一接口 = timeline IR（C 源码）。Creation 之间
可以长得截然不同（news_desk 像 Visual Studio，clip 像 Vim）；引擎统一。加 primitive =
引擎级动作（C 加新关键字）；加 creation = 写新编辑器（轻量）。

## 如何应用

### 关键不变量

- Timeline **永不持久化**（无 schema 版本兼容包袱）
- Timeline **永不被人类编辑**（无 round-trip 稳定性要求）
- `ComponentInstance.compile()` 是**纯函数**——无副作用、不写文件、不弹 UI、不动 `self.config`
- `Element.kind` 必须 ∈ primitive catalog；编译期 schema validate；不在 catalog 内的 kind 是编译错误
- 加 primitive = 引擎级动作（**4 件套**：`<Kind>Spec` + `<Kind>Style` + libass/ffmpeg renderer + preview JS 分支同步上线），不是 component 想加就加
- 加 creation = 写新"编辑器"（实现 `ComponentInstance` 协议即可），不动引擎

### 设计哲学（3 条核心）

- **P1. Timeline 是 IR，不是 UI** —— 用户永远看不到 track/element 视图（不做时间轴编辑器）；编辑入口是任务化 UI（news_desk 组件面板、clip 样式 tab、未来 PPT 拖块……）
- **P2. Timeline 是编译产物，不是真相源** —— 真相源 = component instance config；AI 写的是 component config，不直接写 timeline
- **P3. 引擎核心优势 = AI 生成 component config + 高密度任务化 UI** —— 不是"timeline 编辑器"，是"让 AI 把 raw 素材 → 高质量 component config，用户在任务 UI 上微调"

### 引擎 API

**编译器**（`core/composition/compile.py`）：

```python
@dataclass
class ClipRange:
    start_sec: float
    end_sec: float
    @property
    def duration_sec(self) -> float: ...

@dataclass
class CompileContext:
    """Engine-side, pure data — no UI callbacks. Creations may subclass."""
    project: object
    material_model: object
    instance_dir: str
    duration: float

class ComponentInstance(Protocol):
    kind: str
    id: str
    def is_enabled(self) -> bool: ...
    def compile(self, clip_range: ClipRange,
                ctx: CompileContext) -> list[Element]: ...

def compile_timeline(
    components: list[ComponentInstance],
    clip_range: ClipRange,
    ctx: CompileContext,
) -> CompositionTimeline: ...
```

**IR**（`core/composition/timeline.py`）：

```python
@dataclass
class Element:
    kind: str                          # primitive registry key
    start_sec: float                   # clip-relative
    end_sec: float
    z_offset: int = 0
    style: dict = field(default_factory=dict)   # inlined at compile time
    data: dict = field(default_factory=dict)    # kind-specific content

@dataclass
class Track:
    id: str
    component_kind: str                # label only, NOT dispatch
    z_base: int
    enabled: bool
    elements: list[Element] = field(default_factory=list)

@dataclass
class CompositionTimeline:
    duration_sec: float
    tracks: list[Track] = field(default_factory=list)
```

**Primitive registry**（`core/composition/primitives/__init__.py`）：

```python
def register_overlay_renderer(kind: str, fn: OverlayRenderer) -> None: ...
def get_overlay_renderer(kind: str) -> OverlayRenderer: ...
```

### Creation 端使用

Creation app 自己持 component 列表，在变化时调 `compile_timeline()` 编译为 timeline，
把 timeline 喂给 preview / render：

```python
# news_desk_tool.py (after PR 4)
def _rebuild_timeline(self) -> CompositionTimeline:
    return compile_timeline(
        self.config.components,
        ClipRange(0.0, self._duration),
        ctx=ProjectContext(
            project=self.project,
            material_model=self.material_model,
            instance_dir=self._instance_dir(),
            duration=self._duration,
            seek_to=self._preview_seek_to,    # UI hook — subclass field
        ),
    )

def _push_preview(self):
    self._preview.set_timeline(self._rebuild_timeline())

def _do_render(self):
    req = CompositionRequest(
        source_video=..., in_sec=..., out_sec=..., output=...,
        timeline=self._rebuild_timeline(),
    )
    render_composition(req)
```

注意 `ProjectContext` 继承 `CompileContext` 加自己的 UI 回调字段——引擎签名只看
`CompileContext` 的 4 个纯数据字段。

### 7 个初版 Primitive

`subtitle_cue` / `text_watermark` / `image_watermark` / `hook_text` / `outro_text` /
`topic_strip` / `chapter_hero_card`。每个 primitive 物理上是 `primitives/<kind>.py`
单文件，含 4 件套（Spec + Style + render impl + 注册）。

### 5 通道 → timeline 的具体映射

详见 `docs/design/composition-timeline-v0.md` Axis 7.3。要点：

- `extra_subtitles` 等 SRT 通道：**SRT 在 compile 期读**，每条 cue 编译为一个 `subtitle_cue` element；引擎 render 阶段不再 touch 文件系统
- `style.watermark` 的 `type` discriminator 字段消失——`text_watermark` 和 `image_watermark` 是两个独立 primitive，各自窄 Spec/Style
- `style.hook_outro` 字段消失——hook/outro 是 clip 的 component config，compile 时 emit 两个 element
- `CompositionStyle` 上帝对象整体解体，各字段归 primitive 或 component config

## 不在本 ADR 范围

- **时间轴 UI**——P1 直接排除；用户永远看不到 track/element 视图
- **Timeline 持久化 / 用户可编辑 timeline**——P2 直接排除
- **引擎层 AI 直接写 timeline**——P3 直接排除；AI 写的是 component config
- **音频混音、转场、多源视频拼接**——VideoCraft 不做这些
- **clip 创作的组件化**（旧 task.md 主线 1）——timeline 落地后是自然演化，不绑迁移
- **preset 系统改动**——刚重生（2026-05-17 上半段），跟 timeline 迁移正交，等迁移完再说

## 迁移路径（PR 切片）

完整切片见 `docs/design/composition-timeline-v0.md` Axis 7.2 + 7.5。摘要：

| PR | 主题 | 风险 |
|---|---|---|
| 1 | Timeline IR 脚手架（纯 additive，已合 `c555449`） | 极低 |
| 2 | Primitive 物理拆 + 渲染器注册化（删 `style.py` / `overlays.py` / `news_desk_overlays.py`） | **中**（491 行 libass 搬家） |
| 3 | `compile_timeline()` 真实现 + Component.compile() 协议 | 低 |
| 4 | News_desk 切到 timeline（render + preview） | **高** |
| 5 | Clip 切到 timeline + 老路径删干净 | 中 |

每个 PR 走完测试全绿、老路径在被替换前仍能跑。PR 2 硬前置 = 在 main 上跑 8 个
ASS golden 落 `tests/golden/`（ASS-text 等价是行为保持的唯一可执行证据；不做
pixel-exact golden）。

## 参考

- 完整设计：`docs/design/composition-timeline-v0.md`（权威，所有 Axis 决策都在那里）
- 关联 ADR：[ADR-0003](0003-editor-modules-decoupling.md)（派生作品快照原则）/ [ADR-0004](0004-three-tier-plugin-architecture.md)（三层架构）/ [ADR-0005](0005-componentized-data-layer.md)（创作绑素材的 model API）
- PR 1 commit: `c555449` — timeline IR 脚手架（timeline.py + compile.py + primitives/__init__.py + 24 测试）
