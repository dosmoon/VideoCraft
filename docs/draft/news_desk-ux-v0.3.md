# news_desk UX v0.3 草稿 — 控件分类与三栏布局迁移

**状态**: 草稿 / 等讨论
**日期**: 2026-05-15
**对应代码**: `src/tools/news_desk/news_desk_tool.py`（HEAD `5bc249f`，1535 行）
**前置阅读**: [[project_news_desk_status]]、[[project_subtitle_oneline_invariant]]

---

## 0. 问题陈述

当前 v0.2 面板把"全片唯一属性"和"多实例时间组件"塞进同一张竖向滚动表单，导致：

- 参数同时占满视觉带宽，用户 90% 时间只关心当前选中那一个组件的属性
- `enable` 复选框被滥用在了不该用 enable 的地方（如字幕轨道显示）
- 多个时间组件实例的 in/out/内容平铺在 Treeview，看不出**跨组件冲突**也看不出**单组件细节**
- 没有"添加新组件类型"的扩展点，每加一类组件就要在 `_build_form` 里新写一组按钮 + 一个 `_add_xxx` + 一个 `_derive_xxx`

---

## 1. 核心区分：两类对象

整个面板里所有控件可以严格切成两类。这是 v0.3 重构的根基，先定下来再谈布局。

### 类别 A — 全片属性（singleton, project-level）

整片唯一、不存在"多个实例"的概念，本质是**项目级配置**。

| 现有控件 | 当前位置 | v0.3 归属 |
|---|---|---|
| 预设 (Type1/Type2/...) | 顶部 | **顶栏**（保留） |
| 主字幕轨 `subtitles/zh.srt` | 字幕轨道区 | **全片属性栏** → "字幕轨"组 |
| 副字幕轨 `subtitles/en.srt` | 字幕轨道区 | **全片属性栏** → "字幕轨"组 |
| 字幕样式（位置/距边/轨距/sub1·sub2 字号·颜色·底衬·中文标记） | 字幕样式区 | **全片属性栏** → "字幕样式"组（折叠默认收起） |
| 名牌默认样式 (LowerThird) | 默认样式区 | **全片属性栏** → "默认样式"组 |
| 章节条默认样式 (TopicStrip) | 默认样式区 | **全片属性栏** → "默认样式"组 |
| 水印 (启用/类型/位置/文字·图片/字号/颜色/不透明/缩放/边距) | 水印区 | **全片属性栏** → "水印"组 |

**为何归类 A**：这些东西要么是"轨道入口"（字幕 srt 路径），要么是"模板默认值"（LT/TS 样式被新建组件继承），要么是"全片唯一渲染层"（水印只能有一个）。`enable` 在这里是**合理的**——水印就是一个开关。

### 类别 B — 时间组件实例（instances, time-bound）

多实例、每个实例有 `start_sec` / `end_sec` / 各自参数。本质是 NLE 时间线上的 clip。

| 当前类型 | 实例数 | 数据形态 |
|---|---|---|
| LowerThird (名牌) | 0..N | dataclass + start/end |
| TopicStrip (章节条) | 0..N | dataclass + start/end |
| ChapterPointCard (章节卡 L3) | 0..N | dataclass + start/end |
| DateStamp (日期戳) | 0..N | dataclass + start/end |
| **未来**: PullQuote、Citation、BulletList、CountdownClock... | 0..N | 同上 |

**为何归类 B**：每个实例都有自己的时间区间和内容；属性面板编辑模式天然适用；扩展新类型时不该污染主面板。

### 边界争议项（先记下来，等设计时再决）

- **字幕样式**到底算 A 还是 B？
  - 当前结论：**A**。因为字幕轨是全片唯一的，样式跟着轨走。
  - 但未来如果做"逐句字幕样式覆写"（某句加大、某句换色），那部分得放进字幕属性面板的"高级"区，**不**升格成 B 类组件。
- **水印**未来会不会想要"前 5 分钟显示 LOGO，后面换文字"？
  - 真要做就升格成 B 类（多实例 watermark cue），但**当前不做**。v0.3 保持 A 类。

---

## 2. 三栏布局（NLE 范式 — 列表版）

> 决策更新（§5）：放弃时间轴可视化轨道，改用**分组列表**。点列表项 = 预览 seek + 属性面板切换。

```
┌─────────────────────────────────────┬─────────────────────┐
│  顶栏: [项目名]  [源: video.mp4]     ⋯ [菜单▾ 预设/导出/...] │
├─────────────────────────────────────┼─────────────────────┤
│                                     │                     │
│       预览 (WebView2, 主视觉)        │   属性面板          │
│                                     │   (跟随选中)        │
│                                     │                     │
│   [▶ 0:00 / 53:16]  [⏵ 渲 20s]      │  ─────────────      │
├─────────────────────────────────────┤  无选中:            │
│ 全片属性栏 (折叠分组, 横向铺)        │   项目摘要 +        │
│ [字幕轨▾][字幕样式▸][默认样式▸][水印▸]│   导出按钮          │
├─────────────────────────────────────┤                     │
│ 组件列表 (按类型分组)                │  选中字幕轨:        │
│ ▾ LowerThird (2)         [+ 添加]   │   字幕样式细节      │
│   • 0:09–0:15  万斯独立主持          │                     │
│   • 0:30–0:35  特朗普访华            │  选中实例:          │
│ ▾ ChapterPointCard (10)  [+ 添加]   │   in/out +          │
│   • 0:09–0:15  特朗普访华...         │   内容编辑 +        │
│   • 1:37–1:43  暂缓 13 亿...         │   样式覆写          │
│   • ...                             │                     │
│ ▸ TopicStrip (0)         [+ 添加]   │  [删除] [派生...]    │
│ ▸ DateStamp (1)          [+ 添加]   │                     │
└─────────────────────────────────────┴─────────────────────┘
```

### 各栏职责

**顶栏**：项目名 + 源视频 + 右上 `⋯ 菜单`（预设保存/另存/删除、导出 MP4、20s 预览、派生工具）。预设**不**常驻面板。

**预览栏（中上）**：保持现状。WebView2 + ffmpeg 预览，单击列表项时自动 seek。

**全片属性栏（中部，折叠组）**：A 类对象。每组 `LabelFrame` + 展开/折叠箭头，默认只展开"字幕轨"。**不**进属性面板——A 类需要随时看到当前值。

**组件列表（中下，分组列表 取代 Treeview）**：B 类实例容器。
- **按类型分组**（章节卡 / 章节条 / 名牌 / 日期戳 各自一组），章节卡和章节条**严格分开**
- 每组组头显示数量 `(N)` + `[+ 添加]` 按钮
- 每行显示 `start–end  内容摘要`，单击 → 预览 seek + 属性面板切到该实例
- 双击 → 弹出当前完整编辑器（保留作为高级入口）
- 派生功能挪到右上菜单（`从 basic_info / analysis.json 派生...`），**不再占面板**

**属性面板（右栏）**：跟随选中。
- 无选中 → 项目摘要（源时长、组件总数、导出按钮）
- 选中字幕轨 → 字幕样式细节（位置/字号/颜色/底衬）
- 选中 B 类实例 → in/out + 内容 + 样式覆写 + `[删除]` + `[派生...]`

---

## 3. 组件注册机制（解决"加新组件要改 N 处"）

当前 `_add_lower_third` / `_add_topic_strip` / ... 全部是硬编码方法。v0.3 引入轻量注册表：

```python
# src/tools/news_desk/components/__init__.py (新建)
@dataclass
class ComponentSpec:
    kind: str                    # "lower_third"
    label_key: str               # i18n key for menu/track label
    dataclass_type: type         # LowerThird / TopicStrip / ...
    default_factory: Callable    # () -> dataclass instance with sane defaults
    property_panel: type         # PropertyPanel subclass for right column
    derive_sources: list[str]    # ["basic_info"] / ["analysis"] / []
    derive_handler: Callable | None

REGISTRY: dict[str, ComponentSpec] = {}

def register(spec: ComponentSpec) -> None: ...
```

每类组件一个文件 `components/lower_third.py` 自注册。`[+ 添加组件 ▾]` 下拉自动从 `REGISTRY` 生成。新增 PullQuote 只要新建 `components/pull_quote.py`，**主面板代码不动**。

---

## 4. 迁移路径（分阶段，能逐步合入 main）

### Stage 1 — 控件分类落地（不动布局）
- 在代码注释/dataclass 里把现有控件标注 A/B
- 不动 UI，只为后续 PR 提供共识基础
- 体力活：~半天

### Stage 2 — 引入 ComponentSpec 注册表
- 把 4 类现有 B 类组件改成自注册
- `_add_xxx` / `_derive_xxx` 从注册表读
- UI 仍是当前布局，但 `[+ 添加组件 ▾]` 已变成数据驱动
- 这一步就能验证新增 PullQuote 的成本是否真的降下来

### Stage 3 — 三栏布局（列表版）
- 拆 `_build_ui` 为 `_build_topbar` / `_build_preview` / `_build_project_props` / `_build_component_list` / `_build_property_panel`
- Treeview → **分组列表**（每类组件一组，组头 + 行项）。零自定义绘制，纯 ttk
- 顶栏右上菜单收纳：预设保存/另存/删除 + 导出 MP4 + 20s 预览 + 派生入口
- 属性面板初版只支持：字幕轨 / B 类实例 / 空状态（项目摘要）

### Stage 4 — PullQuote 作为试金石
- 用新机制实现 PullQuote（task.md 里的剩余项）
- 整条链验证一遍，发现问题回头补

---

## 5. 决策（2026-05-15 已定）

1. **预设 (Preset)**：收进**右上角菜单**，不常驻顶栏。让出顶部空间给预览。
2. **章节卡 / 章节条**：**保持分开**两类组件。章节是重要叙事单元，合并会稀里糊涂。
3. **水印**：暂时 A 类（singleton）。未来如真要做分段水印再升 B 类。
4. **时间轴轨道**：**放弃**。Tk 内画时间线复杂度高、空间狭窄、价值有限。改用**分组列表 + 属性面板跳转**——点列表项就跳预览 + 切属性面板，比时间轴更清晰。

---

## 附录 A — 当前控件穷举（来自 `_build_form` + `_build_style_form`）

```
A 类(全片属性):
  preset_combo, preset_save, preset_save_as, preset_delete
  entry_sub1, sub1_pick, sub1_clear
  entry_sub2, sub2_pick, sub2_clear
  sub_position(top/bottom), sub_block_margin, sub_track_gap
  sub1_show, sub1_fontsize, sub1_color, sub1_cn
  sub1_backdrop_color, sub1_backdrop_opacity
  sub2_show, sub2_fontsize, sub2_color, sub2_cn
  sub2_backdrop_color, sub2_backdrop_opacity
  lt_bg_color, lt_accent_color, lt_title_fontsize, lt_subtitle_fontsize
  ts_bg_color, ts_text_color, ts_fontsize
  wm_enabled, wm_type(text/image), wm_position
  wm_text, wm_text_fontsize, wm_text_color, wm_text_opacity
  wm_image_path, wm_image_scale, wm_image_opacity
  wm_margin_x, wm_margin_y

B 类(时间组件实例):
  LowerThird     (按钮: 添加 + 从 basic_info 派生)
  TopicStrip     (按钮: 添加 + 从 analysis.json 派生)
  ChapterPointCard (按钮: 添加 + 从 analysis.json 派生)
  DateStamp      (按钮: 添加 + 从 basic_info 派生)
  + Treeview 总览 + 编辑/删除按钮
```
