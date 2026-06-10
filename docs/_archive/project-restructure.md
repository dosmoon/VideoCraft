# 项目结构重塑：一个项目 = 一个源视频

**状态**：草案（2026-05-11）
**作者**：与 Claude 协作
**关联**：BACKLOG 第一批 P1「AI 切片：YouTube 链接一站式输入」+ 「双语字幕视频 UX 深度优化」
**适用**：VideoCraft 不再考虑前向兼容，用户只有作者本人，可大胆重构

---

## 1. 动机：定位 1:1 落地到数据结构

「创作」战略已锁定 VideoCraft 为 **「源视频派生工具」** —— 一段原视频进来，生成 N 种派生作品（双语字幕视频 / AI 切片 / 摘要 / 解读 / 对话 / 剧场）。

但现在的数据结构仍是 **「开发者方便型」**：

- 一个 folder 可放任意多 manifest，每个 manifest 可挂任意多视频
- 字幕、ASR 产物绑定到 manifest 不绑定到源视频
- AI 切片的 `clip_<cut>` 目录散落在 project 根
- 用户心智 = "我有个工作台和一堆 manifest"，不是"我在做这个视频的衍生作品集"

**作者本人开发时用着不别扭，但任何新用户/未来的自己回看都会被结构噪音劝退。**

本次重塑核心命题：

> **一个 VideoCraft 项目文件夹 = 一个源视频的衍生作品集。**

所有派生工具默认从同一 source 取材，字幕族项目级共享，目录结构强可预测。

---

## 2. 新目录结构骨架

```
<project>/
├── .videocraft/                # VideoCraft 内部元数据(用户不应手动改)
│   ├── project.json            # 项目元数据(单文件,取代 manifests/ 目录)
│   └── background.json         # 项目背景(host/audience/topic/notes…),所有派生 AI 共享
├── source/
│   ├── video.mp4               # 源视频(下载或导入,文件名固定)
│   └── meta.json               # URL / 时长 / 分辨率 / 下载时间 / yt-dlp info
├── subtitles/                  # 项目级共享字幕族
│   ├── raw.srt                 # ASR 原始输出
│   ├── canonical.srt           # cue-sized 后(可读切分)
│   ├── zh.srt                  # 中文译文
│   ├── en.srt                  # 英文译文
│   └── bilingual.srt           # 双语合并
└── derivatives/                # 派生作品(每形态一子目录)
    ├── bilingual_video/
    │   └── <instance>/
    │       ├── config.json     # 烧录样式 / 字幕选择 / preset
    │       └── output.mp4
    └── ai_clip/
        ├── <cut-name-1>/
        │   ├── cut.json        # 章节排序 + 切片定义 + Hook/Outro
        │   └── output/
        │       ├── clip-001.mp4
        │       └── clip-002.mp4
        └── <cut-name-2>/       # 同源不同方案(不同 style/角度)
```

**层次原则**:
- `.videocraft/` = 项目级内部控制信息(用户既看不到也不动)
- `source/` / `subtitles/` / `derivatives/` = 用户内容与产物(用户可理解、可备份、可手动检查)
- 派生内部的 `config.json` / `cut.json` 留在派生目录内(整个派生目录已经是 VideoCraft 生产空间,不再二次隔离)
- `source/meta.json` 跟视频文件直接关联,留在 source/ 内更直观

未来扩展形态各自占 `derivatives/<type>/` 子目录：
- `derivatives/summary/`
- `derivatives/commentary/`
- `derivatives/dialogue/`
- `derivatives/theater/`

---

## 3. 关键架构决策（已敲定）

### 3.1 源视频唯一性 = 硬性 1:1
- 一个项目 = 一个源视频。不允许同项目挂多视频
- 多个视频 = 多个项目
- **理由**：软性建议会被自己绕过，最后退化回现状

### 3.2 项目入口 = 源驱动
新建项目对话框只问两件事：
1. **源**：YouTube 链接 / 本地视频文件（二选一）
2. **项目名**：default = 视频标题 / 文件名（可改）

YouTube 链接走 yt-dlp 下载到 `source/video.mp4`（结合 BACKLOG P1 一站式链接输入）；本地文件按选项**拷贝**或**软链**到 `source/video.mp4`（默认拷贝，避免源文件移动后断链）。

### 3.3 manifest 概念完全消失
- 取代物 = 项目级单一 `project.json`
- 现有 manifest 的"workflow step 状态"概念转化为 `derivatives/<type>/config.json` 的形式表达
- **理由**：manifest 复杂度本质来源于"一 folder 多视频"，1:1 后这套机制完全多余

### 3.4 字幕族 = 项目级共享 + derivative 例外覆盖
- 默认：ASR / 翻译/ cue-sizing 一次产出，落 `subtitles/`，所有 derivatives 复用
- 例外：切片可能需要更激进的句子切分（短视频 cue 更短），允许 `derivatives/ai_clip/<cut>/subtitles_override/` 优先级高于项目级
- **理由**：复用是常态、覆盖是少数

### 3.5 derivative 多实例化
所有派生类型统一走 `derivatives/<type>/<instance-name>/` 二级结构：
- AI 切片高频多 cut（不同角度试 → cut-news / cut-funny / cut-formal）
- 双语字幕视频通常单实例，但目录形态保持一致（instance-name=`default`）
- 未来摘要/解读等同理

---

## 4. 概念契约（schema 草案）

### 4.1 `.videocraft/project.json`
```json
{
  "schema_version": 1,
  "name": "项目显示名",
  "created_at": "2026-05-11T10:00:00Z",
  "source": {
    "origin": "link" | "local",
    "url": "https://...",                       // origin=link 时
    "imported_from": "/path/to/original.mp4",   // origin=local 时
    "clip_range": {                              // 可选(高级选项),null 表示完整视频
      "start": "00:10:00",
      "end":   "00:20:00"
    },
    "title": "...",
    "duration_sec": 1234,
    "width": 1920,
    "height": 1080
  },
  "language": {
    "source": "en",
    "translated_to": ["zh"]
  }
}
```

注意:措辞统一用 "link"(中性),不暗示具体站点,跟 UI 措辞保持一致。

### 4.2 `source/meta.json`
yt-dlp `--write-info-json` 的完整输出（保留完整 metadata，包括 channel / upload_date / tags 等，供 AI prompt 注入用）。

### 4.3 `.videocraft/background.json`
搬自现有 `ProjectBackground` dataclass，但从 cut 文件提升到项目级（所有派生 AI 共享同一项目背景）：
```json
{
  "show_type": "...",
  "host": "...",
  "host_bio": "...",
  "guests": [...],
  "audience": "...",
  "episode_topic": "...",
  "platform_tone": "...",
  "notes": "..."
}
```

### 4.4 字幕命名规范（subtitles/ 下）
| 文件 | 含义 |
|---|---|
| `raw.srt` | ASR 直出，未做任何切分调整 |
| `canonical.srt` | 经 cue-sized（可读宽度） |
| `<lang>.srt` | 单语翻译产物（如 `zh.srt` / `en.srt`） |
| `bilingual.srt` | 双语合并（每条 cue 包含双语两行） |

---

## 4.5 启动器 + 主窗口两段式架构(节点 ⑤ 关键决策)

VideoCraft 采用 **独立启动器窗口 + 主窗口** 模式(对标 Unity Hub / UE Launcher / IntelliJ Welcome / DaVinci Project Manager)。

```
启动 VideoCraft
   ↓
┌─ 项目启动器(独立小窗口) ────────────────┐
│                                          │
│         VideoCraft                       │
│      源视频派生创作工具                   │
│                                          │
│      [+ 新建项目]                        │
│      [□ 打开已有项目...]                  │
│                                          │
│  最近项目:                               │
│  · 某访谈节目 ........ 2 天前            │
│  · 鲍威尔发布会 ...... 上周              │
│  · ...                                   │
│                                          │
└──────────────────────────────────────────┘
   ↓ 选定项目
启动器销毁 → 主窗口(VideoCraftHub)打开,完整主界面
(菜单/Sidebar/工作区全开,项目已就绪)
   ↓
File → 关闭项目 → 主窗口销毁 → 启动器重新出现
File → 退出     → 程序结束
```

### 关键决策与价值

| 决策 | 价值 |
|---|---|
| 启动器是 **独立窗口**(非 Hub 内 Welcome frame) | Hub 永远 with-project,无"无项目"分支 |
| Hub 构造函数强制要求 `project: Project`(不允许 None) | 静态保证状态机干净 |
| 关闭项目 = 销毁主窗口 + 重启启动器 | 切换项目动作清晰,跟启动一致 |
| Hub 菜单栏永远完整 | 不需要 disable/隐藏/重建菜单逻辑 |

### 消失的复杂度

| 原本需要处理 | 现在 |
|---|---|
| 「创作」菜单的 disable 状态 | 不存在(无项目时主窗口本身不存在) |
| 工具栏按钮 disable + tooltip | 不存在 |
| Sidebar Project tab "未打开项目"占位 | 不存在 |
| 派生工作台被打开但无源视频 | 不会发生(项目就绪才进 Hub) |
| Hub 内 Welcome / 工作 两态切换 | 不存在 |

### 实施

1. 新增 `src/launcher.py` —— 独立 Tk 启动器窗口
2. `VideoCraftHub.__init__` 改造:强制要求 `project: Project` 入参,删除所有 `self.project is None` 分支
3. 入口逻辑(main):
   ```
   project = launcher.show()  # 阻塞直到用户选定
   if project is None: sys.exit()
   hub_root = tk.Tk()
   hub = VideoCraftHub(hub_root, project)
   hub_root.mainloop()
   # 用户 File → 关闭项目时设置 reopen_launcher 标志并销毁 hub_root
   if reopen_launcher: 重入 launcher 循环
   ```
4. File 菜单加「关闭项目」(销毁主窗口 + 重启启动器)
5. 删除 Hub 中 `_show_welcome` / `_welcome_frame` / `project is None` 相关代码

### 启动行为细节

- **首启**(无最近项目):启动器只显示新建/打开两个按钮 + 空"最近"占位
- **后续启动**:启动器显示最近项目列表(默认 5~10 条),双击即开
- **自动重开上次项目**:默认 OFF。设置可开。开了之后启动跳过启动器直进上次项目
- **启动器关闭(X)**:退出程序

---

## 4.6 「新建项目」流程(节点 ①~④ 已敲定)

### 新建项目对话框

```
┌─ 新建项目 ─────────────────────────────┐
│                                          │
│  源视频:  ○ 视频链接                     │
│            ○ 本地文件                    │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ [URL 输入框 / 文件选择器]          │  │
│  └────────────────────────────────────┘  │
│  [获取视频信息]  ← 链接模式时显示        │
│                                          │
│  项目名:  [自动填入_可编辑           ]   │
│  保存到:  [父目录                    ]   │
│                                          │
│  ▼ 高级选项 (折叠默认隐藏)               │
│     源视频范围(可选):                    │
│      起 [00:00:00]  止 [完整    ]        │
│     留空 = 完整下载/拷贝;                │
│     已知精彩段时填入可节省下载/磁盘。    │
│                                          │
│  ⓘ 由你确认对所提供内容的合法使用权,    │
│     版权责任自负。  ← 永久小字,常驻      │
│                                          │
│           [取消]  [创建项目]            │
└──────────────────────────────────────────┘
```

**关键设计要点**:
- 措辞中性:**「视频链接」/「本地文件」**,不出现任何站点名(YouTube/B 站/...)
- **「获取视频信息」按钮**:显式触发(避免输入即请求),链接模式下显示
- 项目名自动填入(链接→视频标题;本地→文件 basename),可手改
- **源视频范围**:折叠的高级选项,链接和本地模式都适用
  - 链接 → yt-dlp `--download-sections "*起-止"`
  - 本地 → ffmpeg `-ss <起> -to <止>` 切段后拷贝
- **永久小字版权提示**:常驻对话框底部,不可关闭

### [创建项目] 按下后的流程

```
1. 校验(在对话框内,失败原地报错不关闭)
   ├ 父目录可写
   ├ 项目名合法 (无 \ / : * ? " < > |)
   ├ 父目录下不存在同名子目录
   ├ 链接模式: URL 格式有效
   ├ 文件模式: 文件存在且是视频
   │   (白名单 .mp4/.mkv/.mov/.avi/.webm/.flv)
   └ 范围模式: 起 < 止,格式 HH:MM:SS 或 MM:SS

2. 创建项目骨架(同步,几十毫秒)
   <project>/
   ├── project.json
   ├── source/      (空)
   ├── subtitles/   (空)
   └── derivatives/ (空)

3. 链接模式 + 首次 → 弹一次免责对话框
   勾过后写 settings,后续不再弹

4. 进入源视频下载/拷贝 modal(同步阻塞,见下)

5. 完成后 → 关闭 modal,Hub 切到新项目,opens 项目工作台
```

### 源视频准备:同步 modal + 进度 + 取消

```
┌─ 准备源视频 ────────────────────────────┐
│                                          │
│  正在下载: <视频标题>                    │
│  ████████████░░░░░░░░  62%               │
│  78.4 MB / 126.5 MB · 1.2 MB/s · 剩 35s  │
│                                          │
│            [取消并删除项目]              │
└──────────────────────────────────────────┘
```

**为什么改成同步**(原方案是异步):
- 没源视频派生工作台全灰,用户在等待时无事可做
- 用户在等下载时本就会切到浏览器/IDE,不会盯着 VideoCraft
- 异步带来的"半状态机"(downloading/copying/failed/missing)是复杂度但无价值
- 同步 modal + 进度 + 取消 = 用户心智最简单,失败/重试都在同一处理

**取消 = 删除项目目录回滚**(干净一次性操作)。

**失败 = modal 内显示错误 + [重试] / [改 URL] / [取消]**:
- 网络超时 → [重试]
- URL 无效 / 不支持的站点 → [改 URL]
- JS runtime 缺失 → 链接到安装指引
- 需要 cookies → 引导到 cookies 配置入口
- 磁盘空间不足 → 显示需要 / 剩余空间

### 简化后的源视频状态机

只有 **2 个状态**(去掉了运行时半状态):

| 状态 | 含义 | UI 表现 |
|---|---|---|
| `ready` | `source/video.mp4` 存在且完整 | 正常状态(进 Hub 主窗口) |
| `missing` | 文件被外部删除/移动 | 启动器打开此项目时检测,提示"源视频丢失",提供 [重新下载] / [重新指定文件] |

状态运行时计算(`os.path.exists` + 大小校验),不写盘,避免 stale。

启动器打开项目时若源缺失,先弹"恢复源视频"小流程,恢复完成后才进 Hub 主窗口;Hub 永远只接收 ready 项目。

### 项目存放位置策略(节点 ④)

**方案 = 默认目录 + 可改 + 记忆上次**。

默认值来源(按优先级):
1. 用户在 Preferences 设置的「项目默认目录」
2. 上一次新建项目用的父目录(settings 记忆)
3. 首装兜底:`~/Documents/VideoCraft/` (Windows) / `~/VideoCraft/` (其他平台)

**不放 `<repo>/user_data/projects/`** 的理由:
项目数据是用户内容(视频几 GB + 派生几十 GB),portable repo 装不下;用户也会想把项目放到大盘上。
`feedback_portable_data` 那条规则针对的是应用内部数据(配置/缓存/模型),不覆盖用户内容。
类比浏览器:配置放 AppData,下载放 `~/Downloads/`,两个体系。

**Preferences 入口**:
「设置 → 项目 → 项目默认目录」单字段;改它只影响下次新建的默认值,不迁移已存在项目。

**对话框呈现**:
```
保存到:  [D:\Documents\VideoCraft         ] [浏览...]
```
预填默认值,改完点 [创建项目] 后,新值写回 settings 作为下次默认。

**边角处理**:
- 默认目录不存在或不可写 → 弹错误要求改,不自动 fallback(避免静默坑)
- 用户用网络盘/OneDrive → 不阻拦,但首启提示一次"建议放本地盘,同步盘会拖慢字幕/导出"
- 项目目录改名/移动后 → 不主动追踪;从「文件 → 打开已有项目」重新指定

**实施影响**:
- `core/project.py` Project 类加 classmethod `default_parent_dir()` 读 settings
- Preferences UI 加一个字段
- 新建项目对话框预填 + 写回

---

## 4.7 「新建派生」流程

### 入口层语义分工

| 入口 | 语义 | 触发什么 |
|---|---|---|
| 「创作」菜单 → 双语字幕视频 / AI 切片 | 我要**新建**一个该类型的派生 | 弹 [命名对话框](类型已确定) |
| Sidebar Project tab 顶部 [新建派生] 按钮 | 我要新建派生(还没想好类型) | 弹 [完整选择对话框](含类型 + 命名) |
| Sidebar Project tab 列表项双击 | 我要打开已有派生 | 直接进对应工作台 |

**核心原则**:菜单 = 创建路径;Sidebar = 浏览/打开路径。两条不重叠、不冲突。

**双语字幕视频「已存在」特殊处理**:菜单点击时若项目已有该派生 → 弹"项目已有双语字幕视频派生" + [打开已有的] / [新建另一个] / [取消]。AI 切片始终新建。

### [完整选择对话框](Sidebar 按钮触发)

```
┌─ 新建派生 ──────────────────────────────┐
│                                           │
│  类型:                                    │
│   ○ 双语字幕视频                          │
│     把源视频做成带双语字幕的完整视频      │
│                                           │
│   ● AI 切片                               │
│     从源视频找峰段,导出 N 个短切片        │
│                                           │
│  实例名:  [cut-1                       ]  │
│           将创建: derivatives/ai_clip/cut-1/ │
│                                           │
│           [取消]  [新建并打开]            │
└───────────────────────────────────────────┘
```

未来加摘要/解读/对话/剧场 = 同对话框多 4 个 radio。

### [命名对话框](菜单触发,类型已定)

```
┌─ 新建 AI 切片 ───────────────────────────┐
│                                           │
│  实例名:  [cut-1                       ]  │
│           将创建: derivatives/ai_clip/cut-1/ │
│                                           │
│           [取消]  [新建并打开]            │
└───────────────────────────────────────────┘
```

### 默认实例名规则

| 类型 | 首个实例 default | 多实例 default(自增) |
|---|---|---|
| 双语字幕视频 | `default` | `v2`, `v3`, ... |
| AI 切片 | `cut-1` | `cut-2`, `cut-3`, ... |
| 未来 4 形态 | `default` | `v2`, `v3`, ... |

自增逻辑:扫 `derivatives/<type>/` 已存在子目录,推下一个未占用名。

### 命名约束

| 规则 | 说明 |
|---|---|
| 长度 1~64 字符 | 避免过长路径 |
| 文件系统兼容 | 禁用 `\ / : * ? " < > \|` 及首尾空格 |
| 同类型下唯一 | `derivatives/<type>/<name>` 不能撞名 |
| 不允许 `.` 开头 | 避免隐藏目录陷阱 |

校验在对话框内完成,失败标红字段不关闭。

### [新建并打开] 按下后

```
1. 校验实例名(对话框内)
2. mkdir derivatives/<type>/<name>/
3. 写一份初始 config.json:
   ├ bilingual_video → 默认烧录样式 preset
   └ ai_clip → 空章节 + 默认 Hook/Outro 预设
4. 关闭对话框
5. Hub 打开该类型工作台 tab,加载这个实例
6. Sidebar Project tab 刷新,新派生加到列表
```

零网络/磁盘 IO 风险(mkdir + 一个小 json),毫秒级完成,不需要进度 modal。

### 暂不在本期处理

- **派生模板/克隆**("复制 cut-1 为 cut-2 再改"):MVP 不做,用户手动复制目录已能用
- **派生重命名/删除**:进入 Sidebar 列表右键菜单层,后续节点处理
- **跨项目复用派生模板**:不做

---

## 5. UI/UX 影响

### 5.1 Hub 主界面变化
- **Hub 永远 with-project**:不存在"无项目"分支,移除 Welcome frame / 菜单切换 / disable 状态逻辑
- **左侧 Sidebar** "Project tab":从"manifest 列表" → **"derivatives 列表"**
  - 显示该项目下已存在的派生作品(双语字幕视频 / AI 切片 cut-1 / AI 切片 cut-2 …)
  - 每条派生可双击 → 打开对应工作台并加载该实例
  - 顶部 [新建派生] 按钮 = 弹完整选择对话框
- **菜单 → 创作 → 双语字幕视频 / AI 切片**:点击 = 在当前项目下新建该类型派生(弹命名对话框)
- **File 菜单加「关闭项目」**:销毁 Hub,重启启动器

### 5.2 各工作台变化
- **双语字幕视频工作台**（原项目工作台）：从 manifest editor 重写为 "**当前项目 → 字幕状态 → 烧录配置 → 一键产出**" 单流程页
- **AI 切片工作台**：保留章节为中心的 master-detail UX，但去掉"挑视频文件"步骤，去掉"项目背景"卡片（提升到项目级），cut 文件路径改 `derivatives/ai_clip/<cut>/cut.json`

---

## 6. 实施影响范围(粗估)

| 模块 | 改动量 | 关键点 |
|---|---|---|
| `src/launcher.py`(新建) | 中 | 独立启动器窗口:新建/打开/最近项目 |
| `src/VideoCraftHub.py` | 大 | 改造为 with-project 单态;删除 _show_welcome / project=None 分支;menu 不再切换;File 加「关闭项目」 |
| `core/project.py`(Project 类) | 大 | 从 manifest 容器 → project schema 加载/保存;字段:source/subtitles/derivatives 三类访问 |
| `tools/project/project_workbench.py` | 重写 | manifest editor 概念消失,改成"当前项目→字幕状态→烧录配置→一键产出"单流程页 |
| `tools/program/clip_workbench.py` | 中 | source/字幕注入路径变更;项目背景上移 |
| `core/program/clip.py`(ClipProjectConfig) | 中 | background 字段从 cut 移到项目层 |
| `core/manifest_*.py` | 删除 | manifest pipeline 不再需要 |
| Hub Sidebar Project tab | 重写 | manifest 列表 → derivatives 列表 + [新建派生] 按钮 |
| 新建项目对话框 | 新建 | 源链接/本地 + 项目名 + 范围 + 免责声明 |
| 新建派生对话框 | 新建 | 类型选择 + 实例命名 |
| Preferences | 加字段 | 「项目默认目录」+「自动重开上次项目」开关 |
| 「创作」菜单 wiring | 改 | 点击 = 在当前项目下新建该类型派生 |
| BACKLOG「AI 切片 YouTube 链接一站式」P1 | 合并 | 这条 P1 的核心能力(链接输入 + 免责)被新建项目流程自然吃掉,可关闭 |

---

## 7. 风险 / 待解决

### 7.1 已知陷阱
- **本地文件 import 默认拷贝**：长视频几个 GB 拷贝慢，可加"软链或拷贝"开关；但默认拷贝保证源稳定（用户移动原文件不断链）
- **字幕族 schema 升级**：现有 ASR/翻译工具产出的字幕命名/位置都要适配新规范
- **多 cut 命名冲突**：用户起重名 cut → 加 basename 校验（已有，复用即可）

### 7.2 暂不解决（标记为后续）
- **同项目复用源视频片段**（比如同一长视频做多角度切片但实际只想用前 30 分钟）：未来用 source 级别的"工作区间" metadata 解决，本期不做
- **派生作品的"已过时"标记**（source 或字幕改了导致老 derivative 不再匹配）：本期不做，假设用户知道自己在干嘛
- **跨项目的资源共享**（比如同一 host 多期节目共享 background.json）：暂不做，作品级别 metadata 独立

---

## 8. 不在本期范围

- 现有项目数据迁移工具 —— 用户确认不需要（VideoCraft 未发布，作者本人手工迁/弃即可）
- 字幕处理综合工作台 —— BACKLOG 已暂缓
- 视频生成层（合成视频）—— 跟「创作」主轴并行的另一支
- 节目稿子 5 形态中的后 4 个（摘要 / 解读 / 对话 / 剧场）—— 本期只把架构腾出位置，不实现

---

## 9. 实施顺序建议

不要瀑布大一统。分小步切换,每步可独立运行验证:

| 阶段 | 内容 | 验证标志 |
|---|---|---|
| **P0** | `project.json` schema + 新目录约定 + Project 类重写 | 单元测试通过,新建/加载项目工作 |
| **P1** | 启动器窗口 + Hub 改造为 with-project 单态 + File→关闭项目 | 启动看到启动器,选项目进 Hub,关闭项目回启动器 |
| **P2** | 新建项目对话框(链接/本地 + 范围 + 免责) + 源视频准备 modal | 粘链接 / 选本地文件,创建项目,源就绪 |
| **P3** | Hub Sidebar derivatives 列表 + 新建派生对话框 | 在项目内新建派生实例,Sidebar 看到 |
| **P4** | AI 切片工作台改造(source/字幕/background 注入路径;background 从 cut 移到项目层) | 新结构项目下跑通切片导出 |
| **P5** | 双语字幕视频工作台重写(manifest 模型 → project + config 模型) | 新结构下跑通烧录 |
| **P6** | 删除 manifest 旧代码 + 旧字段 + 老 Welcome 残留 | 代码减肥,grep 不到 manifest |

各 P 之间允许混合形态短暂共存(旧 manifest 文件忽略),但用户不应再创建任何新 manifest。

---

## 10. 决策日志

- 2026-05-11 形成草案,涵盖节点 ①~⑤(入口/对话框/创建后流程/项目存放/启动器+派生对话框)
- 关键决策:
  - 1:1 源视频/项目(硬性)
  - manifest 概念退场
  - 字幕族项目级共享
  - derivatives 二级实例化(`<type>/<instance>/`)
  - **启动器 + 主窗口两段式**(对标 Unity Hub / UE Launcher)
  - Hub 永远 with-project,删除所有"无项目"分支
  - 同步 modal 准备源视频(取消异步状态机)
  - 措辞中性,不出现具体站点名
  - 永久小字版权声明 + 首次免责弹窗
- 待回看:实施 P0 之前重新通读本草案,看是否还有遗漏

---

## 11. 2026-05-12 实施差异 (UX 进化记)

P0~P4.8 + P6 全部上线,此外 UX 在草案之上进一步演化,**实际形态以此节为准**:

- **派生类型名字微调**: "双语字幕视频" → "字幕烧录" / Subtitle Burn(对应行为而非视频种类)
- **Hub 右栏 = 永久 tab 0 (项目) + 可关闭工具 tabs**:点 sidebar 任意预览对象(source / SRT / 派生 output)都在 tab 0 inline 显示;点派生实例(单击)开工作台 tab。所有详情对话框删除,内容折进 tab 0 的预览面板(视频左+元数据右,SRT 左+问题列表右)
- **底部日志面板**改为可折叠:24px 状态条 + ▲ 上拉按钮,默认收起
- **字幕检测三档**(必须处理/自动修复/建议)+ sidebar 行内 [🔧 修 N] 一键修可修项 + 行内 [↻] 单条重生(替代"重新生成"全杀按钮)
- **派生作品产物在 sidebar 树展开**:每实例下挂 `▶ output.mp4` + `📄 subtitles_<iso>.srt`(选了字幕就必产,屏幕适配后的版本)
- **ASR 句子级 regroup** (`core/sentence_regroup.py`):port stable-ts 默认链;无 words[] 时段级 fallback 兜底
- **字幕检测消息 + 预览面板 UI 全部走 tr()**(32 个 zh/en key 对)
- **Tab 0 不可关闭** via `TabBar.add_tab(closable=False)`

清理:`src/tools/project/project_workbench.py` (1500 行 manifest editor) + `Project.manifest_*` 全删;149 个 `tool.project_workbench.*` i18n key 移除。

详见记忆 `project_create_milestone.md` (持续维护版).
