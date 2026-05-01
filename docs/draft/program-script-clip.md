# 切片稿（Clip Script）

**状态**：Phase A 已上线 / Phase B 待开
**日期**：2026-05-01（创建）/ 2026-05-01（Phase A 实施同步）
**优先级**：P1（节目稿子生成 5 形态之首）
**命名约定**：本文是 `docs/draft/program-script-<form>.md` 系列的第一份。
未来 4 份对应：`-summary.md` / `-commentary.md` / `-dialogue.md` / `-theater.md`。
视频生成层另立 `program-video-synthesis.md`，等稿子层 MVP 跑通后写。

---

## 实施状态

| Phase | 状态 | 内容 |
|-------|------|------|
| **A** Walking skeleton | ✅ 已上线 | 手工版端到端：cut 文件 + 4 Tab UI + ffmpeg 导出 pipeline，无 AI |
| **B** AI 叠加 | ⏳ 待开 | 三个 AI 按钮：rank chapters / find peaks / package text |

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

- **Phase B 实施**：3 个 AI 按钮 + 3 个 prompt + tri-state cancel + 失败降级
- **其余 4 形态文档**（summary / commentary / dialogue / theater）：等 Phase B 跑稳后批量产出，复用本文章节模板
- **视频生成层**（program-video-synthesis.md）：等切片稿在生产中用过几轮再立项
