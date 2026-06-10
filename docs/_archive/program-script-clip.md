# 切片稿（Clip Script）

**状态**：Phase A + B + UX 重构 + Phase C（4-tab + 项目背景 + AI context 注入）已上线
**日期**：2026-05-01（创建）/ 2026-05-03（最近更新）
**优先级**：P1（节目稿子生成 5 形态之首）
**命名约定**：本文是 `docs/draft/program-script-<form>.md` 系列的第一份。
未来 4 份对应：`-summary.md` / `-commentary.md` / `-dialogue.md` / `-theater.md`。
视频生成层另立 `program-video-synthesis.md`，等稿子层 MVP 跑通后写。

---

## 实施状态

| Phase | 状态 | 内容 |
|-------|------|------|
| **A** Walking skeleton | ✅ 已上线 | 手工版端到端：cut 文件 + 4 Tab UI + ffmpeg 导出 pipeline，无 AI |
| **B** AI 叠加 | ✅ 已上线 (`4e28539`) | 3 prompt + 3 AI 函数 + 3 tri-state 按钮 |
| **B+** Prompt 契约重构 | ✅ (`da2ef47`) | rank=原文 paragraphs / peaks=cue-id 整数 / package=单 placeholder |
| **UX 重构** | ✅ (`9c39a38` + `c61b64e`) | 4 tab → 2 tab master-detail，章节为工作单元，全自动 AI |
| **M-A~M-D + M-H** | ✅ (`140568f`/`77e9790`/`5942d22`/`4c0d5a0`) | Output style 数据模型 + Tab 0 表单 + WebView 真视频预览 + 字幕水印叠层 + 导出 pipeline 接通 cfg |
| **Hook/Outro 样式系统** | ✅ (`f293be1`) | HookOutroStyle 扩字段 + 9 个工业级模板 + WebView 实时预览 + aspect-aware 字号公式 |
| **Phase C** UX 拆分 + 项目背景 + AI context 注入 | ✅ (`b2ead2a` + `401745a`) | 4 tab（项目/样式/章节/导出）+ ProjectBackground dataclass + clip.package prompt 注入"谁/对谁/什么场合"上下文 |

---

## 1. 定位

**一句话**：长视频（直播 / 演讲 / 访谈 / 发布会）→ N 条 30-60 秒竖屏短视频，每条带 hook + 原片片段 + outro + 标题 + hashtags，可独立发布到 TikTok / YouTube Shorts / Reels。

**对标**：OpusClip（2024 年估值 ~2.15 亿美金，赛道标杆）。

**与 OpusClip 的核心差异**：

| 维度 | OpusClip | VideoCraft 切片稿 |
|------|---------|-----------------|
| 找亮点的方式 | 端到端 AI 扫长视频，自带"病毒性预测"模型 | **基于 chapter 级联**：复用前置 `subtitle.pack` 的章节划分，AI 只在已切好的章节内打分/找峰 |
| AI 训练数据需求 | 需要"什么爆过"的真实数据 | 不需要，纯 LLM prompt 工程 |
| 用户控制权 | 弱（黑盒推荐，被动接受） | **强（AI 推荐，人工守关每一步）** |
| 横转竖 | Face tracking 自动 pan/crop | **人工拖矩形框**（face tracking 砍出 MVP） |
| B-roll / 表情包覆盖 | 自动 | **MVP 不做** |
| 字幕动态高亮 | 关键词逐字放大 | MVP 不做（独立 backlog 项） |

**目标用户场景**：
- 自媒体主：一场 90 分钟直播 → 5-10 条短视频引流
- 财经/科技博主：把发布会切成"X 谈 Y"系列
- 教育创作者：把 1 小时讲座切成"金句合集"

---

## 2. 项目模型（Phase A 实际）

### 2.1 Cut 文件（项目身份）

切片稿是**显式命名的项目文件**（不是隐式状态）。每份 cut = 一个 `.json` 文件，自包含所有上下文。

**位置约定**：`<project>/.videocraft/clips/<cut_name>.json`
- `<project>` = Hub File→打开文件夹 选的当前项目根
- `<cut_name>` = 用户起的名字（同一项目可有多份 cut，比如 `tiktok` / `youtube` / `中文版`）

**Schema**（v2，详见 `core/program/clip.py:write_cut_file`）：
```json
{
  "version": 2,
  "name": "tiktok",
  "saved_at": "2026-05-01T...",
  "sources": {
    "pack_path":  "<absolute path to postprocess.json>",
    "video_path": "<absolute path to source mp4>",
    "srt_path":   "<absolute path to srt>"
  },
  "output_dir": "<auto or user-set>",
  "clips": [ ClipDraft... ]
}
```

**自动保存**：任何编辑（加切片 / 改文案 / 拖 crop / 改源路径）→ 立刻写盘，无询问。

### 2.2 输出目录

每份 cut 的成品落在：`<project>/clip_<cut_name>/output/`

- `clip_` 前缀防止与 manifest unit 文件夹（基于源视频 basename）撞名
- 自动算好填到 Tab 4 的输出目录字段，用户可手动改
- 改完跟着 cut JSON 一起持久化

### 2.3 路径示例

```
D:\My_新闻短片\20260430\鲍威尔议息\           ← Hub 打开的项目根
├── 美联储议息会议20260429\                   ← manifest unit（已有）
│   ├── 美联储议息会议20260429.mp4
│   ├── subtitles\
│   │   └── 美联储议息会议20260429_zh.srt
│   └── output\
│       └── 美联储议息会议20260429-postprocess.json
├── .videocraft\
│   ├── manifests\
│   │   └── 美联储议息会议20260429.json       ← manifest 数据（已有）
│   └── clips\                                ← 新增
│       ├── tiktok.json                       ← cut 文件
│       └── youtube.json
├── clip_tiktok\                              ← cut 输出（新增）
│   └── output\
│       ├── clip-01-鲍威尔承认通胀有点黏.mp4
│       └── clip-02-失业率反差.mp4
└── clip_youtube\
    └── output\
        └── ...
```

---

## 3. UI 工作流（Phase A 实际）

4 Tab wizard。**没打开 cut 时 Tab 2/3/4 灰**，强制走 [新建] / [打开]。

### Tab 1：项目 + 源文件 + 章节

```
┌─ 剪辑稿（项目文件）──────────────────────────────┐
│ [新建…] [打开…] [另存为…]                          │
│ 当前剪辑: tiktok    路径: D:\...\.videocraft\... │
└──────────────────────────────────────────────────┘

┌─ 输入文件（手动选）──────────────────────────────┐
│ Pack JSON   [...postprocess.json] [浏览…]         │
│ 视频        [...mp4]              [浏览…]         │
│ SRT         [...srt]              [浏览…]         │
│ [加载]                                             │
└──────────────────────────────────────────────────┘

┌─ 章节列表（来自 subtitle.pack）─────────────────┐
│ # │ 时间 │ 时长 │ 标题 │ 摘要                    │
│ 1 │ 0:00 │ 1:30 │ Intro │ ...                    │
│ 2 │ 1:30 │ 3:30 │ Body │ ...                     │
└──────────────────────────────────────────────────┘
```

**[新建]**：弹小输入框只问名字（默认填视频 basename），路径固定到 `.videocraft/clips/<name>.json` 不显示。
**[打开]**：模态 Listbox 列出当前项目下所有 cut 名（剥扩展名），双击 / 回车打开。
**[另存为]**：标准 Save As 对话框，做"另一个版本"用。

### Tab 2：段落（手工选段）

```
┌─ 新增切片 ──────────────────────────────────────┐
│ 章节 [#2 [01:30] Body              ▼]            │
│      章节范围: 01:30 – 05:00  (共 3:30)           │
│ 章节内偏移 (秒) [30]   时长 (秒) [45]              │
│ → 切片绝对范围: 02:00 – 02:45  (45s)              │
│ [对齐字幕边界] [加入切片] [删除]                    │
└──────────────────────────────────────────────────┘

┌─ 已选切片 ──────────────────────┬─ 视频预览 ─────┐
│ # │ 章节 │ 起 │ 止 │ 时长       │  [VLC 画面]   │
│ 1 │ Body │ ... │ ... │ 0:45      │               │
│ 2 │ Q&A │ ... │ ... │ 0:38       │               │
└──────────────────────────────────┴───────────────┘
```

**关键设计**：用户填**章节内偏移 (秒) + 时长 (秒)**，不是绝对 HH:MM:SS（更符合"在某章节里挑一段"的心智）。蓝字实时显示绝对范围预览。「对齐字幕边界」把绝对范围 snap 到最近 cue 边界后反算回 Spinbox，避免句子被切半。

### Tab 3：文案（每条切片一卡）

```
┌─ #1 · [02:00–02:45] Body ────────────────────────┐
│ <原片字幕摘录，灰字 200 字>                        │
│ Hook   [测试一下                          ]       │
│ Outro  [关注我看更多                      ]       │
│ 标题   [鲍威尔承认通胀有点黏              ]       │
│ 标签   [#美联储 #通胀 #鲍威尔             ]       │
└──────────────────────────────────────────────────┘
```

每个字段 trace 到 ClipDraft + 触发 _autosave。

### Tab 4：Crop + 导出

```
┌──────────────────────────────────────────────────┐
│ 切片 [#1 [02:00–02:45] Body         ▼]            │
│ [重设居中 (9:16)] [应用到全部]                     │
├──────────────────────────────────────────────────┤
│  ┌──────────────────────────────────┐             │
│  │  原视频 keyframe 截图             │             │
│  │  ┌────┐                           │             │
│  │  │红框│ ← 拖拽 / resize           │             │
│  │  └────┘                           │             │
│  └──────────────────────────────────┘             │
├──────────────────────────────────────────────────┤
│ 输出目录 [D:\...\clip_tiktok\output] [浏览…]       │
│                                       [一键导出全部]│
│ 进度：[████████░░] 3/5 (xx%)                       │
└──────────────────────────────────────────────────┘
```

**Crop 关键设计变更**：
- 原计划：在 VLC surface 上叠 tk.Canvas → **Windows VLC 用 set_hwnd() 接管 HWND，Canvas 鼠标事件被吞，方案不可行**
- 实际方案：用 ffmpeg 抽取 keyframe JPEG（切片中点），在普通 tk.Canvas 上叠红框拖拽 → 副作用是 VLC 缺失也能用
- 砍掉了"居中/手动"radio（reset_to_center 触发 _notify → 流程互锁），改为单一 [重设居中] 按钮 + 框始终可拖

---

## 4. 数据模型

### ClipDraft（每条切片）

dataclass，详见 `core/program/clip.py:ClipDraft`：

```python
@dataclass
class ClipDraft:
    id: int                     # 1-based, 同 cut 内唯一
    chapter_idx: int            # 来自 pack.segments[idx]
    chapter_title: str
    start_sec: float            # 已 snap 到 cue 边界
    end_sec: float
    original_excerpt: str = ""  # 原片字幕该段拼接
    hook: str = ""
    outro: str = ""
    title: str = ""
    hashtags: list[str] = []
    crop_rect: dict | None = None    # {x, y, w, h} normalized 0..1
    status: str = "draft"            # draft / reviewed / exported / skipped
    output_path: str = ""
```

### Cut 文件 schema

见上文 §2.1。完整 list[ClipDraft] 通过 `dataclasses.asdict` 序列化。

### 复用：subtitle.pack schema

不改动 `core/srt_ops.py:SUBTITLE_PACK_SCHEMA`，只读消费。

---

## 5. 复用清单（实际指向）

| 模块 | file:line | 用途 |
|------|----------|------|
| `core/srt_ops.py:21-47` | SUBTITLE_PACK_SCHEMA | Pack 输入 schema |
| `core/segment_model.py` | parse_timestamp / format_timestamp / safe_filename | 时间戳处理 |
| `core/subtitle_ops.py:21-26` | LAYOUT_DEFAULTS["vertical"] | 竖屏字幕样式 |
| `core/subtitle_ops.py:process_srt_split` | SRT 行宽分割 | 竖屏字幕重新分行 |
| `core/subtitle_ops.py:escape_ffmpeg_path / hex_color_to_ass` | ffmpeg 字符串 | filter_complex 构建 |
| `ui/vlc_player.py:VlcPlayerFrame` | VLC 嵌入 | Tab 2 视频预览 |
| `core/ai/__init__.py:complete_json` | AI 入口 | Phase B 三个按钮（待用）|
| `core/translate.py:302-307` | AIError unwrap 范式 | Phase B 错误处理（待用）|
| `tools/translate/translate_srt.py:93-250` | tri-state cancel 范式 | Phase B 取消按钮（待用）|

---

## 6. Phase A 实际文件清单

### 新增

| 路径 | 说明 |
|------|------|
| `src/core/program/__init__.py` | 模块标识 |
| `src/core/program/clip.py` | 业务层（ClipDraft / 三个 AI 函数留 stub / ffmpeg pipeline）|
| `src/tools/program/__init__.py` | 模块标识 |
| `src/tools/program/clip_workbench.py` | UI 主窗口（4 Tab）|
| `src/ui/crop_overlay.py` | 静态截图上的 9:16 矩形拖拽组件 |

### 修改

| 路径 | 改动 |
|------|------|
| `src/VideoCraftHub.py` | TOOL_MAP 加 `clip-script` + `节目` 菜单 |
| `src/i18n/zh.json` + `en.json` | +90 余 keys 双语对称（tool.clip.* + menu.program.*）|

### Phase B 时再加

| 路径 | 说明 |
|------|------|
| `prompts/clip.rank-chapters.md` | AI prompt 1 |
| `prompts/clip.find-peaks.md` | AI prompt 2 |
| `prompts/clip.package.md` | AI prompt 3 |
| `src/core/prompts.py` (mod) | DEFAULTS 加 3 条 |
| `src/core/ai/router.py` (mod) | task_routing 加 3 条（可选）|

---

## 7. 设计变更记录（Phase A 实施过程中的偏离）

| 原设计 | 实际做的 | 原因 |
|--------|---------|------|
| `<basename>-clips.json` 导出时才写 | **显式命名 cut 文件**，每次编辑自动保存 | 用户反馈"惰性运行 + 隐式逻辑无法理解"，要明确入口 |
| 自动从 manifest 反推 video/SRT 路径 | **三个源路径全手工选** | 反推链路过长 + 假定项目结构有局限（独立视频+字幕场景挂掉）|
| Pack 加载后弹"是否恢复历史草稿" | 砍掉，改为 [打开] 按钮显式恢复 | 同上，避免隐式弹窗困扰 |
| Tab 4 居中/手动 radio | 改为 [重设居中] 按钮，框始终可拖 | radio 状态机 + reset 互锁导致 "选了手动后选不回居中" bug |
| Tab 2 起止用绝对 HH:MM:SS | 改为 **章节内偏移秒 + 时长秒** | 用户已经选了章节，让他做减法是反人类 |
| Crop overlay 在 VLC 画布上叠加 | 改为 **ffmpeg keyframe JPEG + tk.Canvas** | Windows VLC set_hwnd() 吞 Canvas 鼠标事件 |
| 输出 `<unit>/output/clips/` 跟其他烧录产物混在一起 | 改为 `<project>/clip_<cut>/output/` | 一目了然属于切片稿；防止跟 manifest unit 撞名 |
| 工具入口仅菜单 | 同左 + Hub 自动传 `self.project.folder` 作 initial_file | 让 cut 路径有锚点，跟 project_workbench 范式一致 |

---

## 8. MVP 边界（明确不做）

| 功能 | 为什么不做 | 何时考虑 |
|------|----------|---------|
| Face tracking 自动 pan/crop | 工程量大 + 需要训练数据 | Phase 2 |
| B-roll / 表情包覆盖 | 需要素材库 + AI 选图 | 独立功能，未来另议 |
| 病毒性预测打分 | OpusClip 真护城河，需要平台数据 | 永远不做 |
| 字幕动态高亮（关键词放大） | 视觉灵魂但是独立工程量 | 单独 backlog 项 |
| 平台直接发布 | 走 buffer-publishing-integration 另议 | 看 Buffer 集成 |
| 多视频批量切片 | UI 复杂度 ×N | Phase 2 |
| 多 chapter 跨段拼接成 highlight reel | 改变数据模型 | Phase 2 |
| AI 配音替换原音 | 走对话稿 / 解读稿形态 | 对应形态文档 |

---

## 9. Phase B 设计（待开发）

### 9.1 三个 AI 按钮

| Tab | 按钮位置 | 调用 | 行为 |
|-----|---------|------|------|
| Tab 1 章节列表 | 顶部 [刷新 AI 排序] | `clip.rank_chapters(pack)` | 给所有 chapter 打 0-100 分 + 一句理由，按分排序，加列展示 |
| Tab 2 已选切片 | 列表上方 [AI 找峰 - 当前章节] | `clip.find_peaks(pack, chapter_idx)` | 在该 chapter 内找 1-3 个 30-60s 切点，自动加进列表（已 snap 到 cue 边界）|
| Tab 3 每张文案卡片 | [AI 生成文案] | `clip.package_clip(clip)` | 自动填 hook/outro/title/hashtags 4 字段 |

### 9.2 AI 调用规范

每个函数走 `core.ai.complete_json` + 严格 JSON schema + cancel_token 透传。错误处理仿 `core/translate.py:302-307`（AIError unwrap，CANCELLED 走 neutral 路径）。

按钮走 tri-state 仿 `tools/translate/translate_srt.py:93-250`：idle/running/cancelling 三态。

### 9.3 Prompt 设计要点

| Task | Tier | 要点 |
|------|------|------|
| `clip.rank` | STANDARD | chapter 标题 + refined 浓缩 → 评分。维度：钩子强度 / 观点密度 / 情绪 / 独立可看懂 |
| `clip.peak` | STANDARD | chapter paragraphs → 30-60s 段。AI 给秒数，外层 snap 到 cue 边界 + 限长（30 ≤ d ≤ 90）|
| `clip.package` | PREMIUM | clip 文本 + chapter 上下文 → hook（中文 ≤15 字）/ outro（≤20 字）/ title（≤30 字）/ 3-5 hashtags |

通用约束：输出语言 = 输入语言 / 严格 schema / 评分必给 reason / 不许编造原片没说过的事实。

### 9.4 失败降级

任何 AI 失败 → 弹 `ui/ai_error_dialog`（已有，按 Kind 分恢复动作），手工流程不被阻断。取消 <1s 内回 idle。

---

## 10. 验证（Phase A 已通过）

### Smoke test 路径

1. Hub 打开任意已跑过 step5_pack 的项目
2. 节目 → 切片稿 → [新建] → 输入名字 → 自动建 cut JSON
3. Tab 1 三个源路径手动填好 → [加载] → 章节列表出现
4. Tab 2 章节下拉 → 偏移/时长填值 → [对齐字幕边界] → [加入切片]，加 2-3 条
5. Tab 3 给至少 1 条填 hook + outro + 标题
6. Tab 4 选切片 → 截图出现 + 红框默认居中 → [一键导出全部]
7. 验证 `<project>/clip_<cut>/output/` 下：N 个 1080×1920 mp4 + 字幕烧录清晰 + hook 前 5s / outro 后 5s 显示

### 持久化验证

- 编辑任何字段 → 关闭 Hub → 重启 → [打开] 选同名 cut → 状态完整恢复

---

## 11. 跟进项

- ~~**Phase B 实施**~~ ✅ 已上线
- **Output Style Control**（用户标记的下一个大问题）：字幕字体/颜色 / hook 样式 / outro 样式 / intro/outro 卡片 / BGM / 水印预设
- **真实工程跑通 UX 重构验证**：master-detail 还没在真视频上端到端
- **VLC 实时播放回归**：当前只 keyframe 静态预览
- **其余 4 形态文档**（summary / commentary / dialogue / theater）：等切片稿真用过几轮再批量产出
- **视频生成层**（program-video-synthesis.md）：长期项

---

## 12. UX 重构记（2026-05-02）

### 动机

原 4 tab（章节 / 段落 / 文案 / 导出）把同一章节的工作物理切成 4 段：Tab 1 选章节 → Tab 2 再选一遍同一章节找峰 → Tab 3 找到该章节相关 clip 写文案 → Tab 4 一个个预览框选导出。**章节上下文反复丢失，操作发散**。

新模型：**章节是工作单元** —— 一个章节里包含找峰 / 预览 / 框选 / 文案的完整闭环；每个章节有「全自动 AI」一键搞定；最后用「汇总导出页」做总览 + 批量收尾。

### 落地后 2 Tab 架构

**Tab 1「章节」master-detail**（左 320px / 右 expand）

- 左：紧凑章节卡片（标题 + 热度分 + clip 数 + 状态点 ○◐●） + 顶部 [全局 全自动 AI] / [AI 排序]
- 右：选中章节的 detail pane
  - 章节头：一行（标题 + 时段 + 时长 + 热度徽章）
  - 章节级动作：[▶ 全自动 AI] / [找峰 AI] / [+ 手工切片]
  - meta 行：AI reason + refined 合并一行灰字
  - **Vertical PanedWindow**（用户可拖，初始 weight 2:3）
    - 上 = 共享 PreviewPane（keyframe + CropOverlay + [Reset center] + [Apply to all]）
    - 下 = 滚动 ClipCard 列表

**ClipCard 折叠化**（关键 UX 修复）

- 默认只一行头：`▶ ◯ #id [时段] dur · title  [跳过] [×]`
- 焦点的那张自动展开 → 露出 excerpt + PackageForm（hook/outro/title/hashtags） + per-clip [文案 AI] 按钮
- 点击任意 ClipCard → on_focus → 展开自己 + 折叠兄弟 + 共享 PreviewPane seek 到该 clip

**Tab 2「汇总导出」**

- 左：跨章节 ClipSummaryTreeview（# / 章节 / 时段 / 时长 / 状态 / 标题）
- 批量按钮：[跳过] / [取消跳过] / [重置 Crop] / [跳到该章节] （后者切回 Tab 1 + 自动选中 + clip focus）
- 右：焦点 clip 编辑（PreviewPane + PackageForm 复用同一对象）
- 底栏：输出目录 + Browse + [导出选中] + [导出全部]

### 全自动 AI 流（关键新逻辑）

**单章节 `_worker_chapter_full_auto(token, chapter_idx)`**：
1. `find_peaks(pack, chapter_idx, cues)` → N 个 clip 候选
2. snap 到 cue 边界 + 抽取 excerpt → 转 `ClipDraft`（in-thread，不操 UI）
3. 对每条新 clip 串行 `package_clip(clip, pack)` 写回 hook/outro/title/hashtags
4. 每条默认 `center_crop_rect(video_w, video_h)`
5. status=reviewed
6. 全程 cancel_token，单条 package 失败留 draft 不阻塞后续

**全局 `_worker_global_full_auto(token)`**：
- 章节按 `_ranks` 倒序遍历
- 跳过已有 clip 的章节（重复保护）
- 章节级失败不阻塞，记录错误继续下一章
- 进度回调按 chapter 推进

### 共享 widget 抽象

新建 `src/ui/clip_widgets.py` 定义 4 个 widget，Tab 1 / Tab 2 共用：

| widget | 输入 | 职责 |
|--------|------|------|
| `PreviewPane` | `bind_clip(clip, video_path, w, h)` | 抽 keyframe → 显示 → CropOverlay 绑 clip.crop_rect。`on_change` 回调 + `set_apply_all_callback` |
| `PackageForm` | `bind_clip(clip)` | 4 字段 Entry + 失焦 trace 写回 + 可选 per-clip AI 按钮（通过 ai_button_factory + ai_worker_for_clip） |
| `ClipCard` | clip + 4 callback | 折叠头 + 展开 body（excerpt + PackageForm） + skip/× 按钮。`set_focused(True)` 自动展开 |
| `ClipSummaryTreeview` | `bind(clips)` | 跨章节列表，iid=str(clip.id)，多选 + `get_selected_clips()` + `select_clip(id)` |

### 数据层（完全不动）

cut JSON schema 跟 Phase A 一致；ranks 数组、autosave 链路、ClipDraft 字段都不变。重构纯 UI。

### 砍掉了什么

- 老 Tab 2 (Peaks)：合并到章节 detail pane 的 [找峰 AI] / [+ 手工切片]
- 老 Tab 3 (Package)：合并到 ClipCard 内联 PackageForm
- VLC 实时播放：keyframe 静态预览已够用（独立 backlog 再加）
- 「居中/手动」radio：早期已删，仍保留 [Reset center] 单按钮

### 文件清单

| 路径 | 改动 |
|------|------|
| `src/ui/clip_widgets.py` | **新增** ~480 行：4 个可复用 widget |
| `src/tools/program/clip_workbench.py` | 重写主体 ~1450 行 |
| `src/i18n/zh.json` + `en.json` | 25 keys 双语补全（btn_chapter_auto / btn_global_auto / col_status / hint_pick_chapter / status_global_progress 等） |

### 用户反馈历史（额外补充）

- "章节上下文不能丢"：所以 master-detail，所有章节相关动作都在右 pane
- "3 clip 详情一个看不到"：所以 ClipCard 折叠化 + PanedWindow 可拖
- "为啥要单独生成文案"：所以文案与切片同卡片，不再独立 tab
- "最后通过汇总导出页完成最后工作"：所以保留 Tab 2 做总览 + 批量


---

## 13. Phase C 重构记（2026-05-03）

### 动机

切片稿越用越发现两个问题相互绞杀：

1. **Tab 0 太挤**：cut 文件管理 + 输入文件 + 完整输出样式（aspect/字幕/水印/Hook-Outro）+ 预览窗，全塞一个 tab 里，垂直滚动条永远在动。
2. **AI 文案产出平淡**：`package_clip` 的 prompt 只塞了 `{clip_excerpt}`，prompt 里甚至明确写"只有这一段，没有别的上下文"——AI 不知道说话人是谁、对谁说、什么场合，自然生成不出有人设的 hook/outro。
   - 用户原话："关键是生成内容的 prompt，以及获得'人们关注的那个 hook'……不够，不足"
   - 进一步追因："最大的问题是，提交上去的信息不够，这个是谁什么时候在哪里面向谁说什么"

两个问题指向同一个解：**项目级背景信息卡片**——既给 UI 减负（独立成区），又给 AI 喂料（接入 prompt）。

### 落地后 4 Tab 架构

| Tab | 内容 |
|-----|------|
| **0 项目** | cut 文件管理（new/open/save as）+ 输入文件（pack/video/srt）+ **项目背景卡片**（8 字段：show_type / host / host_bio / guests / audience / episode_topic / platform_tone / notes，含 multiline notes textarea） |
| **1 样式** | 原 Tab 0 的输出样式部分整体迁过来：preset 选择 / aspect / 字幕 / 水印 / Hook-Outro / BGM + 大尺寸 WebView 预览（PanedWindow 可拖） |
| **2 章节** | master-detail（不变） |
| **3 导出** | 汇总 + 批量（不变） |

### 项目背景数据模型

```python
@dataclass
class ProjectBackground:
    show_type: str = ""        # 访谈 / 演讲 / 直播切片 / 课程 / 评论 / 解说
    host: str = ""             # 主讲人姓名
    host_bio: str = ""         # 一句话身份
    guests: str = ""           # 其他出场人
    audience: str = ""         # 目标观众画像
    episode_topic: str = ""    # 整集主题
    platform_tone: str = ""    # B站 / 抖音 / 小红书 / YouTube
    notes: str = ""            # 杂项: 敏感话题 / 避雷词 / 特殊语气
```

挂在 `ClipProjectConfig.background`，跟着 cut 文件自动 round-trip（asdict + from_dict 同步处理）。

### AI context 注入

`package_clip(clip, pack, *, project_config=None, cancel_token=None)` 新增 keyword 参数。新增 helper：

```python
def _build_package_context_block(clip, pack, project_config) -> str:
    # 渲染 markdown bullet 列表，空字段跳过
    # 输出 8 个 bg 字段 + pack.title + clip.chapter_title + 切片在整集的位置
    # 全空时返回 fallback 提示
```

`prompts/clip.package.md` 加 `{context_block}` 占位 + 新区块「## 视频背景上下文」+ 在「约束」里明确告诉 AI："必须结合视频背景，同一句话不同人在不同场合说出来 hook 完全不一样（巴菲特在股东大会 vs 街头采访路人）"。

### Tab 标题美化（细节坑）

- ttk Notebook tab 在默认 vista 主题下文字小、颜色弱
- 第一版用 `style.map(background=[(selected, blue)])`：在 vista 上会破坏原生 tab 绘制，CJK 字形 fallback 成方框
- 修法：保留 vista 原生 background，只改 font + foreground，显式指定 `Microsoft YaHei UI 11 bold`

### 用户验证

- "tab 拆分 + 项目背景"：通过
- "tab 标题点击后变方框"：vista 主题坑，已修
- AI 文案产出："明显改善"——证明 context 注入这一步有效

### 下一步（不急）

- **Step B**（推迟）：hook 原型清单 + few-shot 范本 + 自评 rubric。等收集 20-30 条用户认可的真实 hook 范本再做。
- **战略层方向**：用户已表态——"VideoCraft 会逐渐走向优化 AI、Prompt 与引入定制化 agent、harness，随着内容处理深度加深难以避免"。AI 能力是水到渠成的事，先把功能骨架搭完，AI 是后面的"调味"层。

### 文件清单

| 路径 | 改动 |
|------|------|
| `src/core/program/clip.py` | 新增 `ProjectBackground` dataclass + `_build_package_context_block` helper + `package_clip` 加 project_config 参数 |
| `src/tools/program/clip_workbench.py` | 4-tab 拆分 + `_build_background_card` + `_build_tab_style` + `_sync_background_from_form` + Notebook.Tab restyle |
| `prompts/clip.package.md` | 新增 `{context_block}` 占位 + 视频背景区块 + 强化约束 |
| `src/i18n/zh.json` + `en.json` | 17 个 key 双语对齐（tab_style + section_background + bg_*） |

## 14. 二改：drawtext `%` 修复 + 预览长寿化（2026-05-04）

两件独立但同日完成的小事，因为体量都不大合并记录。

### 14.1 drawtext 含 `%` 静默失败

**症状**：导出"成功"（ffmpeg returncode 0）但 hook 文字完全不渲染，outro 正常。出现在 401745a 注入项目背景之后——AI 开始写出"失业率4.3%, 问题出在哪?"这种带数据的 hook，触发隐性 bug。

**根因**：ffmpeg drawtext `text=` 默认 `expansion=normal`，把不带 `{...}` 的裸 `%` 当残缺的 `%{...}` 表达式 → "Stray %" warning + **整条 drawtext filter 静默丢弃**。原 `_escape_drawtext` 用 `\%` 转义同样被丢。

**修法**（commit `3467052`）：
- `_drawtext_filter` / `_build_text_watermark_drawtext`：drawtext 加 `expansion=none`
- `_escape_drawtext`：删掉错误的 `\%` 转义

**经验**：ffmpeg drawtext 的 expansion 语法很容易给「短文本场景」埋雷，以后任何 drawtext 默认都加 `expansion=none`，不需要 `%{...}` 表达式时一律关掉。

### 14.2 PreviewPane 长寿化（章节 tab clip 切换从秒级降到毫秒级）

**症状**：用户反映「章节界面预览总是调一下，效率很低」。每点一次切片，预览要花 1~3 秒重新出来。

**根因**：`_build_detail_clip` 第一行 `for w in self._detail_pane.winfo_children(): w.destroy()` 把整个 detail pane 砍光，包括 PreviewPane —— 每次切片都要：派生新 pywebview 子进程 + WebView2 init + 加载 HTML + `vid.src=` 重新解码视频。1~3 秒级。

但 PreviewPane 内部本来就为复用设计：`_push_clip` 在 `video_path` 不变时只发 `vc.setClipRange(start, end)`（毫秒级）。这条优化路径被 destroy 大杀器废掉。

**修法**（commit `154aaa9`）：右侧 detail pane 拆成
- `_detail_pane` —— chrome 区，仍按 mode 整片重建（placeholder / 章节摘要 / 切片 header+time+actions）
- `_detail_body` —— 稳定 PanedWindow，含 `_preview_holder` + `_form_holder`，仅在 clip-detail mode `pack`，PreviewPane / PackageForm **首次进入时懒构造，之后永驻直到工作台关闭**

切片切换路径：`_build_detail_clip` 只清 chrome，调 `self._preview.bind_clip(new_clip, ...)` + `self._clip_form.bind_clip(new_clip)` 完成切换。Mode 切换走 `_detail_body.pack_forget()` / `pack()`。Inner tab 切换（项目↔样式↔章节↔导出）由 `ttk.Notebook` 自然 unmap 处理，不破坏 SetParent 关系。

**性能对比**：
- 切片→切片：1~3s → ~50ms
- inner tab 切换 + 切回：原本要重建预览，现在零成本
- 副作用：样式 tab 调样式时 push_style 路径终于稳定生效（之前预览常被销毁导致看似不刷）

**架构教训**：
- `winfo_children() + destroy()` 是粗活儿，对长寿组件杀伤过大。chrome 和长寿组件**必须分开 holder**。
- pywebview 子进程的 spawn 成本（WebView2 + HTML + video first-frame decode）远超过 Tk widget 重建，复用 PreviewPane 的收益是数量级的。
- ttk.Notebook unmap 不销毁，SetParent 关系在 unmap/remap 间稳定——验证过 4 tab 来回切换无异常。

### 14.3 文件清单（§14 整体）

| 路径 | 改动 |
|------|------|
| `src/core/program/clip.py` | drawtext 加 `expansion=none`，去掉 `\%` 转义 |
| `src/tools/program/clip_workbench.py` | 右侧 detail pane chrome / body 拆分，PreviewPane / PackageForm 长寿化，3 处 `hasattr` 守卫改 `is not None` |
