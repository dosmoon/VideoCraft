# ADR-0004: 三层架构 — Base / Materials / Creations 插件化

- **状态**: Active
- **决定日期**: 2026-05-16

## 决定

VideoCraft 形态正式升级为**三层插件架构**：

```
┌─────────────────────────────────────────────┐
│ Base (core/ + ui/ 通用部分)                   │
│   - 框架: Hub / Sidebar / Tab 系统            │
│   - 引擎: AI 网关 / composition / IO          │
│   - 通用 UI 工具箱: dialog_utils / web_preview │
│   ※ 对插件类型零认知                          │
└─────────────────────────────────────────────┘
       ▲ 消费 base API           ▲ 消费 base API
       │                          │
┌──────┴─────────┐  数据契约  ┌────┴─────────┐
│ materials/<x>/ │──────────▶│ creations/<y>/│
│  素材插件      │  显式声明   │  创作插件     │
└────────────────┘            └──────────────┘
```

**素材插件**（`materials/<type>/`）：提供一种**数据资产类型**及其加工流程。当前唯一类型 = 「新闻视频素材」（`materials/news_video/`）：源视频 + 字幕 + AI 分析 + 章节 + 新闻 context。

**创作插件**（`creations/<type>/`）：提供一种**视频成品工作台**。当前三种：`news_desk` / `clip` / `bilingual_video`（从 `tools/` 迁出）。

**Base**（`core/` + `ui/` 通用部分）：对插件类型零认知。`tools/` 留给真正的通用工具（download / translate / publish / preferences / router / speech / video）。

## 为什么

### 触发痛点

ADR-0003 把"数据准备 vs 派生编辑器"两层解耦后，又发现两个新问题：

1. **`core/derivative_types.py:37` 把 `bilingual_video` / `clip` / `news_desk` 三个插件名硬编码进了 core**——这是分层违规。Base 不该认识具体插件名字
2. **「派生作品」这个词汇语义错位**——按 ADR-0003 它们是独立编辑器实例，对用户而言就是"我做的创作"，但 UI 词汇/代码 identifier 还沿用 "derivative" 暗示从属关系
3. **`VideoCraftHub.py` 2122 行 god object**：sidebar 内插件特有的 `_build_source_section` / `_build_news_context_section` / `_build_subtitles_section` 都堆在 Hub 里，Hub 知道太多
4. **`src/ui/` 把插件特有 UI 跟通用 UI 工具混一锅**：`source_preview_pane.py` / `news_context_pane.py` / `chapter_editor.py` 这些只有新闻视频素材会用，跟 `dialog_utils.py` / `web_preview.py` 这种真通用工具混着

### 为什么三层不是两层

ADR-0003 只说了"数据 vs 编辑器"二层。但**数据本身也是插件**——它有自己的 schema、自己的加工流程（AI 章节 / context 校正 / ASR 字幕 / hotclips 抽取），不止"原始文件"。所以"数据准备"也该作为一种插件类型独立存在，而不是散在 Hub 和 core 里。

升级为三层后：
- Base 真正只剩"框架 + 引擎"（容器 + AI/composition/IO）
- 素材插件和创作插件**对称**：都是 type-extensible 的 self-registering 模块
- 加新功能 = 加新插件，不用改 base

### 为什么 self-register 注册机制

之前 `derivative_types.REGISTRY` 是个硬编码 list，加新类型要改 core。新机制：

- 每种插件类别（creations / materials）在自己的包下维护 registry：`creations/__init__.py` / `materials/__init__.py`
- 各插件自己在 `__init__.py` 调 `register()` 自报家门
- VideoCraftHub 启动时 import 所有插件 module，触发自注册
- Base 完全不出现任何插件名

## 如何应用

### 目录结构

```
src/
  core/                ← Base 引擎（无 Tk、无插件知识）
    composition/
    ai/
    project.py, io_utils.py, paths.py, ...
  ui/                  ← Base UI 工具箱（无插件知识）
    dialog_utils.py
    collapsible_frame.py
    web_preview.py
    video_preview_pane.py
    new_project_dialog.py
    ai_error_dialog.py
    disclaimer_dialog.py
  materials/           ← 素材插件根
    __init__.py        ← MaterialType base + registry
    news_video/        ← 「新闻视频素材」
      __init__.py      ← register() 自报家门
      type.py          ← MaterialType 实例定义
      schema.py        ← 数据 schema（含从 core 迁来的 15 字段 SourceContext）
      sidebar.py       ← 「素材」tab 内的树渲染
      actions.py       ← 添加源视频 / 重生字幕 / 跑 AI 分析等
      ui/              ← 本插件专属 dialog/pane
  creations/           ← 创作插件根（从 tools/ 迁出 3 个）
    __init__.py        ← CreationType base + registry
    news_desk/
    clip/
    bilingual_video/   ← 从 tools/subtitle 迁出
  tools/               ← 留通用工具（不再含创作插件）
    download/
    translate/
    publish/
    preferences/
    router/
    speech/
    video/
  VideoCraftHub.py     ← 容器 + tab 框架 + 插件 lifecycle，不再 _build_<插件特有>_section
```

### 插件注册契约（伪代码）

```python
# materials/__init__.py
@dataclass
class MaterialType:
    type_name: str
    display_name_key: str          # i18n key
    icon: str | None
    sidebar_renderer: Callable     # 渲染本类型素材树
    create_handler: Callable       # 处理「素材」tab 的 [+]
    artifact_resolver: Callable    # (instance, artifact_key) -> Path | None

REGISTRY: dict[str, MaterialType] = {}
def register(t): REGISTRY[t.type_name] = t
def get(name): return REGISTRY.get(name)
def all_types(): return list(REGISTRY.values())

# materials/news_video/__init__.py
from materials import register
from .type import NEWS_VIDEO_TYPE
register(NEWS_VIDEO_TYPE)

# VideoCraftHub.py 启动
import materials.news_video       # 触发自注册
import creations.news_desk
import creations.clip
import creations.bilingual_video
```

`creations/` 同形。

### 素材 ↔ 创作的契约

创作插件 import 素材时通过 `MaterialType.artifact_resolver(instance, key) -> Path`：

- `key = "subtitle:zh"` → 返回当前素材实例的中文 SRT 路径
- `key = "chapters"` → 返回 analysis.json
- `key = "context"` → 返回 context.json

创作 plugin 拿到路径后**按 [[ADR-0003]] 复制进自己的 `<instance_dir>` 做快照**——不持有引用，不回扫上游。

artifact_key 命名空间归素材插件 schema 定义；创作插件 hard-code 它需要哪些 key。

### Sidebar 三栏

```
┌─[素材]─[创作]─[文件]─┐
│                       │
└───────────────────────┘
```

- **素材**：所有 `materials.all_types()` 的根节点 + 实例树。tab 级 `[+]` 触发 type-picker
- **创作**：所有 `creations.all_types()` 的 instance 平铺（**不按 type 分栏**），type 信息靠 instance 行的 icon/badge 表达。tab 级 `[+]` 触发 type-picker
- **文件**：磁盘 file browser（保留现状）

### Preview tab 0 = 「主窗口」

右栏永久不可关 tab，标题 `hub.preview_tab.title` = 「主窗口」（不再叫「项目」）。承载 inline 预览 + 轻量编辑（素材层字段直接在主窗口里改）。

### UI 文件归属规则

| 类型 | 归属 |
|---|---|
| 通用 Tk 工具（dialog 模板 / 折叠面板 / WebView 宿主 / 视频播放器 / 通用 pane） | `src/ui/` |
| 素材类型特有的 dialog/pane | `materials/<type>/ui/` |
| 创作类型特有的 dialog/pane | `creations/<type>/ui/` |

判断标准：**只有一种插件类型会用 = 属于该插件；多种或框架级用 = 属于 base ui/**。

### Hub 瘦身后只保留的职责

- Window / PanedWindow / Notebook 容器
- 插件 discovery（启动时 `import materials.* / creations.*` 触发自注册）
- 三 tab 渲染：调 `materials.all_types()` 让各素材插件自渲染节点；调 `creations.all_types()` 让各创作插件自渲染 instance 行
- 点击事件路由：sidebar 点了什么 → dispatch 给对应插件的 callback
- Tab bar / 主窗口 lifecycle

**Hub 不再有 `_build_<插件特有>_section`**，全部由插件自己负责。

## 迁移路径

按 slice A→J 推进，详见 task.md：

- **A**: 本 ADR + task.md handoff
- **B**: `creations/` + `materials/` 空骨架 + abstract base classes
- **C**: 迁 `creations/news_desk` ← `tools/news_desk`
- **D**: 迁 `creations/clip` + `creations/bilingual_video`
- **E**: 删 `core/derivative_types.py`，调用切到 creations registry
- **F**: 建 `materials/news_video/` 骨架 + 迁 `SourceContext`
- **G**: 迁插件特有 UI 文件到插件包
- **H**: 重写 `VideoCraftHub.py` — 三 tab + 插件自渲染
- **I**: i18n key 全量改名 derivative → creation
- **J**: tab 级 [+] 收口 + type-picker 通用化

## 不在本 ADR 范围

- 第二种素材类型（如「普通视频素材」无新闻 context）的拆分——按 [[feedback_no_code_structure_in_ux]] 等第二种真出现再做
- 通用插件元数据 schema（manifest.json 之类）——当前 Python 自注册够用，未来需要"未加载也能列出"时再加
- 插件间依赖声明语法——当前 artifact_resolver 一招够，复杂依赖出现再扩
