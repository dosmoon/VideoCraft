# Composition 引擎设计文档(阶段一)

> 状态:草稿 v0.3 / 2026-05-12
> 范围:新 core 模块 `core/composition/`,VideoCraft 视频输出样式与合成的统一层
> 阶段切分:**阶段一(本 doc)= 抽离老 clip_workbench 样式工程 + 让新 AI Clip 派生用上**;阶段二 = subtitle_tool / bilingual_video 派生迁移

---

## 0. 立项动机

### 0.1 触发点

2026-05 大重构后,新 AI Clip 派生(`derivatives/clip`)上线,但 MVP 渲染层(`core/clip_render.py`)是最薄烧录——只调 `video_split.split_one(ACCURATE)` 切段,没有样式、没有字幕、没有 hook 卡、没有水印、没有 aspect 转换。产物仅"原片片段 mp4",不是短视频。

与此同时,老 `tools/program/clip_workbench.py`(2918 行)+ `core/program/clip.py`(1416 行)已经实现了一整套样式工程:18 个内置预设、双线字幕、双预览(PIL + WebView)、单 ffmpeg 调用的 filter_complex 渲染。这套东西菜单入口已经去掉,代码处于**孤岛**状态。

### 0.2 现状评估

VideoCraft 当前所有视频输出工具的样式 + 合成层都是"够用就行":
- **bilingual_video 派生**(`tools/subtitle/subtitle_tool.py`)有自己的 preset 系统(`user_data/presets/subtitle_burn.json`,5 预设),字段命名跟 clip_workbench 完全不同
- **新 clip 派生**根本没有样式层
- **未来的 4 种节目形态**(摘要/解读/对话/剧场)都要做视频输出,各自再造一遍样式系统不可承受

**核心问题**:VideoCraft 输出视频质量低,功能能跑通但产品像 demo。这个短板的根源不是 AI 选段不准,是**最后一公里的样式 + 渲染缺乏统一工程**。

### 0.3 决策

把老 clip_workbench 已经走通的样式工程**抽离成 `core/composition/`**,作为 VideoCraft 统一的视频合成 core 层,跟 `core/ai`、`core/subtitle_pipeline` 并列。先让新 AI Clip 派生用上(阶段一),后续 subtitle_tool 等老消费者再迁(阶段二)。

老代码不是业界标杆——字幕没有 karaoke 高亮,字体写死,aspect 不能智能裁剪,hook 卡只是 drawtext 矩形。这些**不是阶段一的目标**,阶段一只把"已经走通的工程"以干净姿态搬过来,作为后续质量飞跃的底座。

### 0.4 全程原则:零兼容包袱

**不写 migration 逻辑**:老 ClipProjectConfig 有 v3/v4 schema 兼容、有 `background` 字段、有 `from_dict` 里的 v3→v4 转换。**这些一律不带过来**。CompositionStyle 是一个全新的、干净的 dataclass,只接受新 schema,字段不对的预设直接弃。

**不留过渡期**:老 `core/program/`、`tools/program/clip_workbench.py`、`core/clip_presets.py`、老 prompt 文件——阶段一最后一步全删。没有 deprecation warning,没有"将来再清理"。

**老资产能迁就迁,不能迁就弃**:18 个老预设里能直接构造 CompositionStyle 的就保留,字段名对不上的弃。老踩坑的修复(`%` 字面量 / `'` 转 curly / 字体路径 fallback)直接照抄,但不带任何"兼容老路径"的分支。

---

## 1. 阶段切分

### 阶段一(本 doc 范围)
**目标**:抽离 + 适配,让新 AI Clip 派生达到老 clip_workbench 的输出质量。
**范围**:
- 新增 `core/composition/` 模块
- 新 AI Clip 派生工作台(`tools/clip/clip_tool.py`)接入 composition,3 tab(候选/样式/导出)一次做完
- 老内置预设能直接迁的迁过来,不能迁的弃
- 老 `core/program/{clip,clip_render}.py` + `tools/program/clip_workbench.py` + `core/clip_presets.py` 全删

**硬指标**:
1. AI Clip 派生能选预设 / 视频级实时预览 / 批量渲染 9:16 短视频
2. 输出质量跟老 clip_workbench 持平(并排对比无明显回归)
3. `core/composition/` API 稳定,只被 `derivatives/clip` 消费,无 leak 到工作台层
4. 内置预设可用(数量见 §6)
5. 老孤岛代码全删,grep 全仓无残留引用

### 阶段二(本 doc 不展开,只占位)
**目标**:打磨稳的 core 接其他派生消费者。
**范围**:
- bilingual_video 派生(subtitle_tool)改吃 composition
- subtitle_burn.json 老 preset:**同样不做兼容**,要不就重写要不就弃
- 未来摘要/解读/对话/剧场派生统一吃 composition

### 后续(不在 doc 内,先记录)
真正的能力增强(karaoke 词级高亮 / smart_crop face_center / 字号系统量化 / brand kit / 动画转场)等 core 在两个阶段消费者打磨稳定后再做。先把架构落地,再做质量飞跃。

---

## 2. 模块定位

```
core/
├── ai/                       智能层:选什么内容
├── subtitle_pipeline.py      数据层:ASR + 翻译
├── subtitle_analysis.py      分析层:hotclips/titles/chapters...
├── composition/              ★ 本 doc 新增 ★ 样式 + 合成层:做出来好不好看
│   ├── __init__.py
│   ├── style.py              CompositionStyle schema(纯 dataclass,无 migration)
│   ├── presets.py            内置 + 用户预设 JSON 读写
│   ├── render.py             ffmpeg + libass + overlay 单调用渲染
│   ├── preview.py            视频级实时预览 — WebView 样式 dict 序列化
│   └── fonts.py              字体名 → 路径解析
└── (其他)
```

**消费者(阶段一)**:仅 `derivatives/clip`(`tools/clip/clip_tool.py`)
**消费者(阶段二)**:加上 `derivatives/bilingual_video`(`tools/subtitle/subtitle_tool.py`)
**消费者(将来)**:摘要/解读/对话/剧场派生

**单向依赖**:composition 不反向依赖任何派生类型,不依赖 `core/subtitle_analysis`,不依赖 `core/source_context`。它只接受 schema 化的输入(style + 一组 cue/clip 数据 + 源视频路径)。

---

## 3. 已有资产盘点

### 3.1 直接搬运(无兼容包袱,纯 copy + 改名)

| 老位置 | 新位置 | 主要内容 |
|---|---|---|
| `core/program/clip.py:43-310` | `core/composition/style.py` | SubtitleLineStyle / SubtitleStyle / WatermarkStyle / HookOutroStyle / BgmConfig / ClipProjectConfig → CompositionStyle。**`from_dict` 不搬**,改写成接受新 schema 的纯构造 |
| `core/program/clip.py:728-1050` | `core/composition/render.py` | `_escape_drawtext` / `_drawtext_filter` / `_build_subtitle_force_style` / `_build_text_watermark_drawtext` / `_build_image_watermark_chain` / `export_clip` → `render_composition` |
| `core/program/clip.py:315-395` | `core/composition/style.py` | `compute_subtitle_max_chars` / `_measure_glyph_width` / `effective_max_chars` |
| `core/program/clip.py:140-187` | `core/composition/fonts.py` | `_HOOK_OUTRO_FONT_MAP` / `_hook_outro_font_path` / `_y_expr_for_position` / `_ass_alignment_for_position` |
| `tools/program/clip_workbench.py:1148-1203` | `core/composition/preview.py` | `_build_web_style_dict` 提取为模块级函数 `style_to_web_dict(style)` |
| `ui/web_preview_clip.html` | 移到 `src/ui/composition_preview.html` 或保持原位 | WebView 实时预览前端(JS 监听 timeupdate + setStyle) |

### 3.2 完全不搬

| 老内容 | 不搬原因 |
|---|---|
| `core/program/clip_render.py`(PIL 静态预览) | 阶段一只做视频级预览,PIL 静态预览删除 |
| `ClipProjectConfig.from_dict` v3→v4 migration | 零兼容包袱,新 schema 不接受老格式 |
| `ProjectBackground` 字段及方法 | 已被 `core/source_context.SourceContext` 取代 |
| `core/program/clip.py` 内 AI 函数(rank_chapters / find_peaks / package_clip) | 已被 hotclips 分析层取代 |
| `core/program/clip.py` 内章节解析(load_pack / list_chapters / chapter_paragraphs) | 已被 `core/subtitle_analysis` 取代 |
| ClipDraft 数据类 | 阶段一用 CompositionRequest 直接表达 |
| `ClipsJSON` 旧 v1 格式 | 派生模型已经解决 |

### 3.3 阶段一**不做**(老代码也没做或很弱)

下列能力都是真正的增量,**放到后续迭代**,不在阶段一里塞:

- 词级 karaoke 高亮(老系统按句染色)
- smart_crop / face_center 自动框选(老系统手动 crop_rect,阶段一固定 center crop)
- 字幕字体 picker(老系统 sub1=YaHei、sub2=Arial 写死,保留)
- 描边默认值校准(老默认 2px,先保留;后续视觉打磨阶段再调)
- Hook 卡复杂样式(圆角/弧形/PNG 卡)— 老系统是 drawtext + 矩形 box,保留
- BGM 接线(老 schema 占位但未真接,继续占位)
- 动画 / 转场 / 淡入淡出
- Brand kit 全局色 / logo 统一
- 字幕模板扩展(花字/气泡/字幕条)
- sub2(第二语言字幕)真实渲染。老代码 sub2 在 schema 占位但 `_build_subtitle_force_style` 只用 sub1,**阶段一保留这一现状**

阶段一只保证:**老 clip_workbench 能做的,新 AI Clip 派生也能做,且没有回归**。

### 3.4 老代码删除清单(阶段一最后一步)

- `src/core/program/clip.py` — 全删
- `src/core/program/clip_render.py` — 全删
- `src/core/program/__init__.py` — 删
- `src/tools/program/clip_workbench.py` — 全删
- `src/tools/program/__init__.py` — 删
- `src/core/clip_presets.py` — 全删(已被 `core/composition/presets.py` 取代)
- `prompts/clip.rank-chapters.md` / `prompts/clip.find-peaks.md` / `prompts/clip.package.md` — 全删
- `core/prompts.py` DEFAULTS/PLACEHOLDERS 里对应键删除
- i18n `tool.clip.*` 里专属老 workbench 的 key(章节/AI 排名/peaks 等) — zh/en 同步删
- `docs/draft/program-script-clip.md` → 归档到 `docs/draft/archive/`

**前置检查**:删之前 grep 整仓,确认 `core/program/clip.py` 内的工具函数(`load_cues` / `slice_srt_for_clip` / `snap_to_cue_boundaries` 等)没被 `core/composition/` 之外的地方引用。被引用的搬到 `core/srt_ops.py` 或保留独立位置。

---

## 4. CompositionStyle schema(全新干净版)

直接照抄老 dataclass 字段,**砍掉所有兼容代码**:

```python
# core/composition/style.py
from dataclasses import dataclass, field

@dataclass
class SubtitleLineStyle:
    enabled: bool = True
    fontsize: int = 24
    color: str = "#FFFFFF"
    bold: bool = False
    is_chinese: bool = False
    auto_max_chars: bool = True
    manual_max_chars: int = 20

@dataclass
class SubtitleStyle:
    sub1: SubtitleLineStyle = field(default_factory=lambda: SubtitleLineStyle(
        enabled=True, fontsize=24, color="#FFFF00",
        bold=True, is_chinese=True))
    sub2: SubtitleLineStyle = field(default_factory=lambda: SubtitleLineStyle(
        enabled=False, fontsize=24, color="#FFFFFF",
        bold=False, is_chinese=False))
    stroke_color: str = "#000000"
    stroke_width: int = 2
    position: str = "bottom"

@dataclass
class WatermarkStyle:
    enabled: bool = False
    type: str = "image"
    image_path: str = ""
    image_scale: float = 0.15
    image_opacity: int = 100
    text: str = ""
    text_fontsize: int = 36
    text_color: str = "#FFFFFF"
    text_opacity: int = 70
    position: str = "top-right"

@dataclass
class HookOutroStyle:
    font: str = "Microsoft YaHei"
    size: int = 48
    color: str = "#FFFFFF"
    bg_color: str = "#000000"
    bg_opacity: int = 70
    stroke_color: str = "#000000"
    stroke_width: int = 3
    box_padding: int = 10
    hook_position: str = "upper-third"
    outro_position: str = "lower-third"
    hook_duration_sec: float = 5.0
    outro_duration_sec: float = 5.0

@dataclass
class BgmConfig:
    path: str = ""
    volume: int = 50  # 占位,未接线

@dataclass
class CompositionStyle:
    aspect: str = "9:16"
    encode_preset: str = "veryfast"
    subtitle: SubtitleStyle = field(default_factory=SubtitleStyle)
    watermark: WatermarkStyle = field(default_factory=WatermarkStyle)
    hook_outro: HookOutroStyle = field(default_factory=HookOutroStyle)
    bgm: BgmConfig = field(default_factory=BgmConfig)

    def aspect_ratio(self) -> tuple[int, int]:
        w, h = self.aspect.split(":", 1)
        return (max(1, int(w)), max(1, int(h)))
```

**无 `from_dict` 兼容方法**。需要从 JSON 加载时调用 `dacite.from_dict` 或手写直接 unpack(老 18 预设里 v3 那 6 个加载时会因字段名不匹配直接抛错——预期行为)。

**无 schema_version 字段**。不留扩展位,改 schema 就改 schema,不写迁移。

---

## 5. 渲染 API

### 5.1 输入数据类

```python
# core/composition/render.py
from dataclasses import dataclass
from .style import CompositionStyle

@dataclass
class CompositionRequest:
    """一次合成调用的全部输入。AI Clip 工作台从 hotclip 数据构造。"""
    source_video: str
    start_sec: float
    end_sec: float
    output_path: str
    style: CompositionStyle
    source_srt: str | None = None   # 主字幕 SRT,空表示不烧字幕
    hook_text: str = ""             # 顶部 hook overlay 文本
    outro_text: str = ""            # 尾部 outro overlay 文本
    crop_rect: dict | None = None   # {x,y,w,h} 归一化,None=center crop

@dataclass
class CompositionResult:
    output_path: str
    duration_sec: float
    width: int
    height: int
```

### 5.2 调用入口

```python
def render_composition(
    req: CompositionRequest,
    on_progress: Callable[[str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> CompositionResult:
    ...
```

实现 = 老 `export_clip` 函数体几乎原样,把 `clip: ClipDraft, project_config: ClipProjectConfig` 两个参数换成 `req: CompositionRequest`。filter_complex 构造逻辑、ffmpeg 命令、进度回调、cancel 处理——全部照抄。

### 5.3 hotclip → CompositionRequest 适配(在 clip_tool 里)

```python
# tools/clip/clip_tool.py
def _hotclip_to_request(self, hotclip: dict, src_idx: int) -> CompositionRequest:
    out_idx = ...
    return CompositionRequest(
        source_video=self.project.source_video_path,
        start_sec=_parse_ts(hotclip["start"]),
        end_sec=_parse_ts(hotclip["end"]),
        output_path=os.path.join(self._instance_dir(),
                                  f"clip_{out_idx:03d}.mp4"),
        style=self._current_style,
        source_srt=self._resolve_source_srt(),
        hook_text=hotclip.get("suggested_title", "") or hotclip.get("hook", ""),
        outro_text="",
        crop_rect=None,
    )
```

`suggested_title` 作为 hook 默认是阶段一的合理选择(hotclips prompt 让模型产出"可作为短视频标题"的 18-25 字短句)。

---

## 6. 预设系统

### 6.1 预设文件位置

阶段一保持现有路径,不动用户配置:
- `user_data/presets/clip_project.json` — CompositionStyle 完整预设
- `user_data/presets/clip_hook_outro.json` — HookOutroStyle 子预设

阶段二再考虑统一到 `user_data/presets/composition/`。

### 6.2 预设迁移策略

老 18 个预设分两批:

**A 批 — 字段干净的(直接迁)**:
- `clip_project.json` 里 `subtitle.sub1/sub2` 结构的 4 个:`TikTok 9:16 单语中文` / `YouTube 16:9 单语中文` / `Instagram 1:1 中文` / `my-tiktok 中文字幕`
- `clip_hook_outro.json` 里 9 个内置 + 用户 1 个

**B 批 — 字段不对的(弃)**:
- `clip_project.json` 里 `subtitle.mode/size/color` 扁平结构的 6 个:`Default` / `TikTok 9:16 单/双语` / `YouTube 16:9 单语` / `B站 16:9 双语` / `Instagram 1:1` — **删掉**,后续如果需要可以从干净的 4 个里复制扩展

具体执行:写一个一次性脚本(或手动) 编辑 `clip_project.json`,只保留 A 批 4 个 + 用户存的。脚本不在 repo 里长留,跑完即弃。

**B 批弃掉的影响**:用户如果之前用 B 批某个预设(比如 `Default`),下次启动 clip_tool 找不到对应名,落到 fallback(`my-tiktok 中文字幕` 或第一个可用)。这是预期行为,符合"零兼容"原则。

### 6.3 presets.py API

```python
# core/composition/presets.py
PROJECT_PRESETS_PATH = ".../clip_project.json"
HOOK_OUTRO_PRESETS_PATH = ".../clip_hook_outro.json"

def load_project_store() -> dict: ...
def save_project_store(store: dict) -> None: ...
def list_project_presets(store: dict) -> list[str]: ...
def get_project_preset(store: dict, name: str) -> CompositionStyle | None: ...
def upsert_project_preset(store, name, style: CompositionStyle) -> None: ...
def get_last_used_project(store: dict) -> str: ...
def set_last_used_project(store, name: str) -> None: ...
# hook_outro 版本签名一致
```

`get_project_preset` 直接返回 `CompositionStyle` 实例(内部 dataclass 构造),字段对不上抛 `ValueError`,不兜底。

### 6.4 内置 fallback

clip_tool 启动时:
1. 加载 store,取 `last_used`
2. 不存在或加载失败 → 取 store 里第一个可用
3. 全没有 → 用 `CompositionStyle()` 默认值,不强行写 JSON

---

## 7. 视频级实时预览(替代老 PIL 静态预览)

### 7.1 架构

```
┌─ tk Frame ────────────────────────────────────────┐
│ ┌─ WebView2 子进程 ─────────────────────────────┐ │
│ │  <div class="stage" data-aspect="9:16">      │ │
│ │    <video src="source.mp4" autoplay loop>    │ │
│ │    <div class="hook">{{hook_text}}</div>     │ │
│ │    <div class="subtitle">{{cue_now}}</div>   │ │
│ │    <img class="watermark" src=...>           │ │
│ │  </div>                                       │ │
│ │                                                │ │
│ │  JS:                                           │ │
│ │    video.ontimeupdate = pickCueForTime()      │ │
│ │    window.vc.setStyle(json) → applyCSS()      │ │
│ └────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────┘
```

`<video>` 元素加载源视频片段(`source.mp4#t=start,end`),自动循环播放整段。JS 监听 `timeupdate`,根据当前 currentTime 从 SRT cue 数组里挑当前时刻应显示的字幕,推到 `.subtitle` 元素。`vc.setStyle(json)` 由 Python 侧调用,更新 stage 容器 + 各 overlay 的 CSS。

### 7.2 样式 → CSS 映射

| Style 字段 | CSS 实现 |
|---|---|
| `aspect: "9:16"` | `.stage { aspect-ratio: 9/16; overflow: hidden }` + `<video>{ object-fit: cover; object-position: center }` |
| `subtitle.sub1.fontsize` | `.subtitle { font-size: ${px}px }` (按预览容器高度 / 1080 缩放) |
| `subtitle.sub1.color` | `.subtitle { color: ... }` |
| `subtitle.sub1.bold` | `.subtitle { font-weight: 700 }` |
| `subtitle.stroke_color/width` | `.subtitle { -webkit-text-stroke: Wpx C }` 或 `text-shadow: ...` 模拟 |
| `subtitle.position` | `.subtitle` 定位 top/middle/bottom |
| `watermark` | `.watermark` 元素(text 或 image)4 角定位 |
| `hook_outro.hook_position` | `.hook` 定位 + `enable` 时段控制显隐 |
| `hook_outro.bg_color/opacity` | `.hook { background: rgba(...) }` |
| `hook_outro.size` | `.hook { font-size: ... }` |

### 7.3 实时刷新流程

1. 用户在样式表单改一个字段(slider/color/dropdown)
2. tk 触发 trace_add → 更新 `self._current_style`
3. debounce 100ms 后调 `self._preview.push_style(style_to_web_dict(style))`
4. WebView 收到 `setStyle({...})` → 直接改 CSSStyleDeclaration
5. 视频继续播,样式立刻变

aspect 切换由于改的是容器形状(不是单纯样式),WebView 需要也重 layout——CSS `aspect-ratio` 改了就会自动 reflow,无须额外处理。

### 7.4 hook/outro 时段控制

用户填的 `hook_duration_sec=5.0` 表示 hook 卡在前 5s 显示。JS 侧 `timeupdate` 内:

```js
const localTime = video.currentTime - startSec;
hookEl.style.display = (localTime < hookDurationSec) ? 'block' : 'none';
outroEl.style.display = (localTime > durationSec - outroDurationSec) ? 'block' : 'none';
```

### 7.5 预览跟最终输出的差异(已知妥协)

不追求像素级一致,只追求视频级一致:
- 字体渲染:CSS 用浏览器字体子像素 hinting,ffmpeg/libass 用 freetype。字距和厚度会有细微差异
- ASS force_style 的某些细节(BorderStyle / Outline 跟 Shadow 的精确叠放)CSS 无法完全复刻
- aspect 转换:CSS 用 `object-fit: cover` 是 GPU 缩放,ffmpeg 是 `crop + scale + pad`。视觉等价但缩放算法不同

**这些差异不在阶段一处理。**用户看到的预览能反映"位置/大小/颜色/时序/形状"就够了,渲染出来的视频会更精致一点(libass 实际比 CSS 渲染字幕更锐)。

### 7.6 预览源帧 / 预览片段

WebView 预览不再是"一帧",而是当前选中候选 clip 的完整 mp4 片段在循环播放。

策略:
- 用户在候选列表点选某条 → preview 切到那条的 (start, end) 区间
- 用户没点 → 默认第一条候选
- 用户没生成 hotclips → preview 容器显示提示文字 "请先生成 hotclips"

技术实现:用 HTML5 `<video src="source.mp4#t=START,END">` 媒体片段语法,Chromium 原生支持时间范围加载 + 自动循环播放。

---

## 8. UI 集成(新 clip_tool 改造)

### 8.1 三 tab 一次做完

```
┌──────────────────────────────────────────────────────────────┐
│  [候选] [样式] [导出]                                          │
├──────────────────────────────────────────────────────────────┤
│ 候选 tab:                                                     │
│   热点来源 [zh ▾]    样式预设 [my-tiktok 中文字幕 ▾] [应用]   │
│   ─────────────────────────────────────────────              │
│   候选列表(checkbox + #N + 时间 + score + hook + transcript) │
│   [全选] [全不选]                                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ 样式 tab(双 pane):                                          │
│ ┌─ 表单(scrollable)─────┬─ 视频级实时预览 ────────────┐    │
│ │ [预设 ▾] [应用][另存为]│                              │    │
│ │ [覆盖][删除]            │   <video> 循环播放          │    │
│ │ ─────                   │   + 字幕/水印/hook overlay  │    │
│ │ Aspect: ○ 9:16 ○ 16:9   │   实时反映表单改动           │    │
│ │         ○ 1:1  ○ 4:5    │                              │    │
│ │ Encode: [veryfast ▾]    │   候选: [#1 ▾]              │    │
│ │ ─────                   │   切候选 → 切预览片段        │    │
│ │ ▾ 字幕                  │                              │    │
│ │   sub1 enabled [✓]      │                              │    │
│ │   字号 [━●━] 24         │                              │    │
│ │   颜色 [█]              │                              │    │
│ │   ...                   │                              │    │
│ │ ▸ 水印                  │                              │    │
│ │ ▸ Hook/Outro            │                              │    │
│ │ ▸ BGM(占位)            │                              │    │
│ └─────────────────────────┴──────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ 导出 tab:                                                     │
│   [选中候选 N 条] [当前样式: my-tiktok 中文字幕]              │
│   ─────                                                       │
│   [▶ 开始渲染]   进度: ━━━━━━━━━━ 3/5  当前: clip_003.mp4   │
│   ─────                                                       │
│   已渲染:                                                     │
│     ▶ clip_001.mp4   00:43   2.1 MB   2026-05-12 18:24      │
│     ▶ clip_002.mp4   00:38   1.8 MB   2026-05-12 18:24      │
│   [打开输出文件夹]                                             │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 持久化

`derivatives/clip/<inst>/config.json`:
```json
{
  "source_subtitle": "zh",
  "selected_clip_indices": [0, 2, 5],
  "style": { ... CompositionStyle as_dict ... },
  "preset_name": "my-tiktok 中文字幕",
  "rendered": ["clip_001.mp4", "clip_002.mp4"],
  "rendered_at": "2026-05-12T..."
}
```

style + preset_name 都存:preset_name 是用户看的标识,style 是真实当下值(用户可能在预设基础上微调过没保存)。**无 schema_version 字段**,跟整个 doc 的"零兼容"原则一致。

---

## 9. 实施顺序

| 步骤 | 文件 | 内容 | 风险 |
|---|---|---|---|
| 1 | `core/composition/style.py` | 写新 dataclass(SubtitleStyle/WatermarkStyle/HookOutroStyle/BgmConfig/CompositionStyle)+ compute_subtitle_max_chars | 低 |
| 2 | `core/composition/fonts.py` | 搬字体路径 / 位置 / alignment 三个 helper | 低 |
| 3 | `core/composition/render.py` | 写 CompositionRequest + render_composition(从老 export_clip 改造) | 中(参数面要谨慎) |
| 4 | `core/composition/presets.py` | 写 store CRUD,搬 last_used 逻辑;同时跑一次性脚本清理 `clip_project.json`(只留 A 批 4 个 + 用户的) | 低 |
| 5 | `core/composition/preview.py` | 写 `style_to_web_dict(style)` + WebView 实时预览组件封装 | 中(JS 侧 timeupdate 字幕逻辑) |
| 6 | `src/ui/composition_preview.html` | 从老 `web_preview_clip.html` 简化迁移(去掉跟老 workbench 耦合的 JS) | 中 |
| 7 | `tools/clip/clip_tool.py` | 候选/样式/导出 三 tab 改造 + 接入 composition | 高(UI 工作量大,占总工时一半以上) |
| 8 | E2E 验证 | hotclip → 9:16 短视频跑通,跟老 clip_workbench 同源素材并排对比无回归 | 阶段一收尾 |
| 9 | 删孤岛 | `core/program/`、`tools/program/`、`core/clip_presets.py`、旧 prompts、i18n key、`docs/draft/program-script-clip.md` 归档 | 低,但需 grep 全 |

每一步独立 commit,可单独 revert。步骤 4 的"一次性脚本清理 preset JSON"需要在 git 里把改动写进 commit message,这样将来能追溯老 B 批预设的丢弃事件。

---

## 10. i18n

老 clip_workbench 的 i18n key 前缀是 `tool.clip.*`(中英文都有),新 clip_tool 用的是 `clip_tool.*`。

**策略**:
- 新增 key 全部用 `clip_tool.*` 前缀(候选/样式/导出三 tab + 样式字段)
- 老 `tool.clip.*` 整批删除(zh/en 同步)
- 严格遵守 `feedback_i18n_symmetry.md`:zh/en 双语同步,新 UI 字符串走 `tr()`,core 层不引 `tr`

---

## 11. 跟现有 core 模块的边界

- `core/subtitle_analysis.py` — composition 不依赖,hotclip 字段由消费者(clip_tool)读出后构造 CompositionRequest
- `core/source_context.py` — 不依赖
- `core/subtitle_pipeline.py` — 不依赖,SRT 路径由消费者传入
- `core/video_split.py` — composition 自己用 ffmpeg filter_complex 单调用,不走 `split_one`
- `core/srt_ops.py` / `core/subtitle_ops.py` — composition.render 内复用 `process_srt_split` / `read_srt` / `hex_color_to_ass` / `escape_ffmpeg_path` 等工具

---

## 12. 不在阶段一里的事(明确边界)

- subtitle_tool 改造 → 阶段二
- 词级 karaoke 高亮 → 后续
- smart_crop face_center → 后续
- BGM 接线 → 后续
- 多语种第二条字幕渲染(老代码 sub2 是 schema 占位,实际 force_style 只用 sub1)→ 后续(可能阶段二一起做)
- 字幕模板 / 花字 / 气泡 → 后续
- 动画 / 转场 → 后续
- brand kit → 后续
- 测试:阶段一以**手动 E2E 对比**为验收,不强求自动化

---

## 13. 决策记录(已敲定)

1. **模块名**:`core/composition/` ✓
2. **API 形态**:`CompositionRequest` 入参 dataclass ✓
3. **零兼容**:无 schema_version、无 from_dict migration、老格式弃 ✓
4. **老资产**:能迁就迁(A 批 4 个 + hook_outro 9 个),不能迁就弃(B 批 6 个) ✓
5. **clip_tool tab**:三 tab(候选/样式/导出)一次做完 ✓
6. **预览**:视频级实时预览(WebView + `<video>` 循环 + CSS overlay),无 PIL 静态预览 ✓
7. **preset 文件位置**:阶段一保持 `user_data/presets/clip_*.json` 不改名,阶段二再考虑统一到 `user_data/presets/composition/` ✓

---

## 14. 阶段一完成定义(DoD)

视为完成的条件:

- [ ] `core/composition/` 5 个 .py(`style/fonts/render/presets/preview`)+ `__init__.py` 落地
- [ ] `src/ui/composition_preview.html` 视频级实时预览前端落地
- [ ] `tools/clip/clip_tool.py` 三 tab 改造完成,样式 tab 表单跟老 clip_workbench 视觉一致
- [ ] 候选/样式/导出三 tab 全部可用
- [ ] WebView 实时预览:改样式参数立即在视频上看到效果(字幕色 / 水印位置 / aspect 形状 / hook 卡显隐时段)
- [ ] A 批迁移过的预设全部可加载渲染,B 批已删除,grep `clip_project.json` 无 B 批名
- [ ] 一条 5 分钟源视频走 hotclips → 选 3 候选 → 选 `my-tiktok 中文字幕` → 渲染 3 个 mp4,跟老 clip_workbench 同样素材渲染对比**无视觉回归**
- [ ] 老 `core/program/` / `tools/program/` / `core/clip_presets.py` 删除,grep 全仓无残留引用
- [ ] 老 prompt 文件 `clip.rank-chapters.md` / `clip.find-peaks.md` / `clip.package.md` 删除,prompts.py DEFAULTS/PLACEHOLDERS 同步清理
- [ ] i18n zh/en 双语同步,无 missing key,无残留 `tool.clip.*` key
- [ ] `docs/draft/program-script-clip.md` 归档到 `docs/draft/archive/`
- [ ] BACKLOG.md 阶段一标记完成,memory 里 `project_clip_script.md` 同步更新

---

## 15. 相关文档

- `docs/draft/ai-clip-redesign.md` — 两层架构(分析层 + 派生层),本 doc 是派生层的样式工程化细化
- `docs/draft/project-restructure.md` — 项目模型 + 派生类型基础
- `docs/design/02-project-model.md` — 派生类型规范
- 老 doc `docs/draft/program-script-clip.md` — clip_workbench 设计文档,阶段一最后一步归档
