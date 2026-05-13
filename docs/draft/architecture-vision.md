# VideoCraft 架构愿景(下一阶段)

> 状态:活文档 v1.0 / 2026-05-13 · **非最终版,随下一阶段推进迭代**
> 范围:在当前(2026-05 大重构完成 + 切片/烧录两核心功能稳定)基础上,
> 描述下一阶段的核心目标 + 配套架构整理
> 关联:`composition-style.md`(渲染引擎)、`derivative-snapshot-principle.md`
> (派生快照原则)、`project-restructure.md`(项目模型)

---

## 0. 当前基线(本文档的起点)

经过 2026-05 大重构 + 阶段一 composition core 落地,VideoCraft 现在的状态:

- **项目模型已规范**:`source/ + subtitles/ + derivatives/` 三段固定树
- **派生层有 snapshot 原则**:派生创建时快照决策性上游,上游重生成不污染派生
- **两个核心功能稳定**:
  - 字幕烧录(`bilingual_video` 派生)
  - AI 切片(`clip` 派生)
- **Composition core 完成阶段一**:统一 composition_style + 渲染 + 实时预览,只服务 clip 派生(阶段二迁 bilingual_video)
- **数据结构化彻底**:整个磁盘布局可形容为一棵规范树

> 重构的"地皮"已经平整完成。下一阶段从"能跑"进入"打磨 + 扩展"。

---

## 1. 架构两层视图(刷新版)

### 1.1 数据三层

```
═══════════════════════════════════════════════════════════════
LAYER 0:  原始输入
═══════════════════════════════════════════════════════════════
  source/video.mp4                ★ 唯一根节点

═══════════════════════════════════════════════════════════════
LAYER 1:  感知提取(modality 跨越,接近 deterministic)
═══════════════════════════════════════════════════════════════
  audio → text(ASR)
    └── subtitles/<src>.srt

═══════════════════════════════════════════════════════════════
LAYER 2:  LLM 转换(prompt 驱动,主观,重生成不稳定)
═══════════════════════════════════════════════════════════════
  每条转换 = (prompt + schema + provider/model/tier + 可选 pre/post)

  <src>.srt ─┐
             ├─ translate ─────────→ <tgt>.srt × N
             ├─ subtitle.titles ────→ <lang>.titles.json
             ├─ subtitle.pack ──────→ <lang>.chapters.json
             │                       <lang>.chapter_refined.md
             └─ subtitle.hotclips ──→ <lang>.hotclips.json

  非 LLM 衍生(从 SRT 纯函数算):
    <lang>.transcript.md / <lang>.chapter_transcript.md

═══════════════════════════════════════════════════════════════
LAYER 3:  Composition(派生合成,确定性)
═══════════════════════════════════════════════════════════════
  derivatives/* 消费 Layer 1+2,产出可发布视频
    bilingual_video / clip / (5 种未来节目稿)
```

### 1.2 能力两层

```
┌─────────────────────────────────────────────────────────────┐
│ Tier 1 · 框架基础(地基)                                       │
│                                                             │
│   外部成熟工具 + VideoCraft 内置基础设施                       │
│     yt-dlp · ASR/TTS providers · ffmpeg · libass             │
│     WebView2 + tk · project model · composition core         │
│     core/ai router · prompt 注册 · preset 存储                │
│     snapshot 机制                                             │
│                                                             │
│   特征:确定性 / 工程问题 / API 稳定 / 跨 plugin 复用          │
│   定位:VideoCraft 的"水电煤气",不是核心 IP                  │
└─────────────────────────────────────────────────────────────┘
            ▲ 提供能力 / 接口
            │
            │ 调用 / 注册
            ▼
┌─────────────────────────────────────────────────────────────┐
│ Tier 2 · LLM 扩展能力 + 派生形态(可演化)                      │
│                                                             │
│   每条能力 = prompt + Python 二元结构,缺一不可                │
│                                                             │
│   现有:translate / titles / segments / refine / pack /       │
│        hotclips(含 outro) + clip 派生 + bilingual_video      │
│                                                             │
│   未来:program.{summary,commentary,dialogue,theater} +       │
│        对应派生工作台 + 其他主题特化的 hotclips 变体           │
│                                                             │
│   特征:主观 / 创造性 / prompt 驱动 / 跟 LLM 进化              │
│   定位:VideoCraft 的"个性",所有差异化和质量飞跃从这里来      │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 Plugin 二元结构

```
plugin = prompt 部分 + Python 部分(两半不可分割)

  Prompt 单独做不到:数据驱动的 UI 卡片、pre/post 业务逻辑、
                  schema 校验/修复、provider 路由、错误处理
  Python 单独做不到:写死 if-else 永远做不出主观决策类任务,
                  需要 LLM 智能

  Tier 2 分析能力 plugin
  ├── plugin.toml
  ├── prompts/<task>.md
  ├── schemas.py        (结构化输出的 JSON schema)
  ├── runner.py         (pre/post + AI 调用 + 落盘)
  ├── preview_card.py   (UI 卡片渲染)
  └── i18n/

  Tier 3 派生 plugin
  ├── plugin.toml
  ├── workbench.py      (交互工作台,占绝大多数代码)
  ├── runner.py         (Snapshot + 调 composition 出片)
  └── i18n/
```

**判断 "进 core 还是 plugin" 的标准**:

| 进 core(Tier 1) | 进 plugin(Tier 2/3) |
|---|---|
| 服务于所有 plugin 都用得到的能力 | 某个具体 AI 任务 / 派生形态的实现 |
| composition 引擎 / AI router | 单个 prompt + 该任务 pre/post |
| ASR/TTS provider 接入 | 单个分析 kind 的 runner |
| 项目模型 / snapshot 机制 | 派生类型注册 / 派生工作台 UI |

---

## 2. 下一阶段四大核心目标

### 目标 1:UI 完善 + 交互完善

**现状痛点**:
- Tab 字号 / 各工具风格 / 色卡 / 按钮样式不统一
- 错误信息工程师友好,用户友好度低,无 actionable 入口
- 空状态(无项目 / 无字幕 / 无 hotclips)/ loading / error 视觉不规范
- 首启没引导,新用户开 hub 一脸懵

**改造方向**:
- **全局 ttk style 统一表**:字号 / 色卡 / radius / 按钮 / labelframe 一处定义
- **Hub 主题色卡 + 视觉语言**:primary / accent / muted / error 一套
- **错误信息 i18n + actionable**:报错时给"点这里修复 X"按钮(打开模型管理 / 重新生成 / 等等)
- **空状态规范**:每个空容器有明确的"接下来做啥"提示
- **首启 onboarding**:启动器引导 / 模型管理首启提示 / 派生创建 wizard
- **快捷键 + 常用操作**:hotkeys 注册;最近操作 / 模板复用

**评估指标**:新用户能不能在没看文档情况下走通"装好 → 建项目 → 加视频 → ASR → 切片"全流程。

### 目标 2:质量提升(数据 + 视频)

#### 2.1 数据质量(Layer 2 LLM 输出)

**现状痛点**:
- prompt 调优主要靠改 prompts.py + 重跑全流程,迭代慢
- 同一任务在不同 provider 上效果差异大,无对比工具
- 缺少 prompt 性能 / 输出质量的回归基线
- Few-shot 样本管理无系统

**改造方向**:
- **Prompt 调式 playground**(已有 ai_console_playground 雏形,继续完善)
  - 单任务实时调 prompt + 直接看输出
  - 同一 prompt 跑多 provider 并排对比
  - 输入样本管理(本地 SRT / 用户上传 / 历史回放)
- **Few-shot 样本系统**:per task 一个 samples/ 目录,prompt 可引用
- **Prompt 版本追踪**:sidecar JSON 加 `prompt_version / prompt_hash`,产物可追溯
- **回归测试集**:固定 SRT + 期望输出对照,prompt 改动后跑回归看变化

#### 2.2 视频质量(Layer 3 渲染输出)

**现状痛点**:
- composition v0.1 出片质量比剪映 / Submagic 差一档(无 karaoke、无 smart crop、hook 卡是矩形 box、字体单一)
- 字幕渲染对齐基本到位,但视觉档次有限
- 出片可识别为"工具产物"

**改造方向(composition v0.2+)**:
- **karaoke 词级高亮**:消费 ASR `words[]`,libass `\k` tag 实现
- **smart-crop face-center**:OpenCV haar / mediapipe 引入(评估 venv 体积)
- **Hook 卡模板**:红 pill / 黄 banner / 极简 等几款 PNG/ASS 模板
- **Brand kit**:primary color / accent / brand font / logo 一套全局应用
- **多档字体 + 字重系统**:用户可选思源黑体 Heavy / 苹方 Bold 等,跟随预览
- **动画基础层**:字幕入场 / hook 卡 pop-in / outro fade
- **多语言字幕同框**(sub2 真渲染,目前是 schema 占位)
- **输出编码自适应**:不同内容自动选 CRF / preset(对话型 vs 动作型)

### 目标 3:基础框架夯实 + 派生物插件初步设计

#### 3.1 框架夯实(Tier 1)

- **Composition core 阶段二**:bilingual_video 迁过来,跟 clip 共用一套样式/渲染/预览底座
- **Snapshot 原则普及**:bilingual_video / 未来派生 全部按 snapshot 原则落地
- **AI router 增强**:per-task 偏好持久化、provider 健康度监测、tier 路由策略可视化
- **Prompt hub 增强**(为 plugin 化铺路):
  - prompts.py DEFAULTS / PLACEHOLDERS / SCHEMAS 改成 **runtime registry**(`prompts.register(task_id, ...)`)
  - 当前模块级常量 → 运行时可注册(为 plugin 加载做准备)
  - 同 task 多版本 prompt 共存(用户选用哪个)
- **PIL / 字体 / WebView 抽象边界**:整理 helper,避免 plugin 重复造轮子

#### 3.2 派生物插件初步设计

不做完整 plugin 框架,先**铺路 + 选 1 个内置作 dogfood**:

**第一步:Registry 重构**(框架层准备)
- `core.prompts` → runtime registry
- `core.prompts_schemas` → runtime registry  
- `core.subtitle_analysis.ANALYSIS_TYPES` → runtime registry
- `core.derivative_types.REGISTRY` → runtime registry
- 重构后行为完全等价(注册位置从模块顶层挪到启动时调用)

**第二步:Plugin 形态定义**(纸上)
- `plugin.toml` manifest 字段约定
- Plugin 目录结构约定(`plugins/<name>/...`)
- Plugin 加载顺序 + 优先级 + 项目级覆盖语义

**第三步:Dogfood — 把 hotclips 拆成首个 plugin**
- `plugins/hotclips-classic/` 包含 prompt / schema / runner / preview_card / i18n
- 内置 `core/` 不再直接持有 hotclips 实现,改为加载 plugin
- 验证 plugin 机制可用 + 完整覆盖一个真实 feature

**第四步**(本阶段不一定做):剩余分析 kind + 派生类型陆续 plugin 化。

#### 3.3 Prompt 工程化

- Prompt 文件统一在 `plugins/<plugin>/prompts/<task>.md` 或 `prompts/<task>.md`(项目级覆盖)
- 内嵌 default(prompts.py 字符串)只作 fallback,不再是主路径
- per-(task, provider) 变体支持:`<task>.<provider>.md`(已记 BACKLOG)
- Playground 跟 plugin 联动:可对当前 plugin 的 prompt 在线 fork / 改 / 跑 / 对比 / 保存

### 目标 4:Composition 引擎深度打磨

**现状评估**:

阶段一 composition 落地,完成了"功能能跑通",但**仍然是整个 VideoCraft 最薄弱的环节**。原因:

1. **预览 ≡ 渲染** 的一致性保证刚刚靠"单源 wrap"勉强建立,但**字号/字体/字距等更深的差异未根除**
2. **核心视觉能力不足**:hook 卡只是 drawtext+矩形 box,字幕只能整句染色无 karaoke,字体写死
3. **Smart crop 缺失**:9:16 输出还是手动 / center,跟剪映自动跟脸有代差
4. **没有动画 / 转场层**:零特效,出片"静态"感强
5. **多 plugin 共用时尚未经历过考验**:阶段二迁 bilingual_video 后才知道抽象是否经得起两个消费者

**深度打磨的具体方向**:

| 方向 | 内容 | 优先 |
|---|---|---|
| 多消费者验证 | 阶段二 bilingual_video 迁进来,跟 clip 共用同一份 composition | P0(下个 sprint) |
| 一致性根治 | 字幕字体在预览端走相同的 libass-equivalent 渲染(或承认差异并标定 delta) | P1 |
| Karaoke 词级 | ASR words[] → libass \k tag → 预览 CSS animation 同步实现 | P1 |
| Hook 卡模板 | 红 pill / 黄 banner / 极简等几款,预览/渲染同一套 PNG/ASS | P1 |
| Smart crop | 引入 mediapipe 或 OpenCV,自动 face-center | P2 |
| 动画 | fade in/out / pop-in / slide,预览端 CSS animation 同步 | P2 |
| Brand kit | primary/accent/brand font/logo 全局应用 | P2 |
| Multi-track | sub2 真渲染、多语言同框 | P2 |
| 编码自适应 | CRF / preset 跟内容类型联动 | P3 |

**命名**:暂保留 `core/composition/`(已大量代码引用)。如未来命名"composer / studio"更合适,届时统一改名。本文档不在命名上花精力。

---

## 3. 不在下一阶段范围

为了聚焦,以下明确不做:

- ❌ Plugin marketplace / 远程加载 / 版本兼容矩阵 / 商业模式设计
- ❌ 多机器协同 / 云端渲染 / 服务化部署
- ❌ 完整的 plugin SDK + 第三方开发者文档(只做 dogfood 验证)
- ❌ AI 模型训练 / fine-tuning(只用现成 LLM)
- ❌ 自动化测试覆盖(只对纯逻辑层小范围补;不强求覆盖率)
- ❌ 跨平台适配 (Linux / Mac)(VideoCraft 当前 Windows-first,跨平台延后)

---

## 4. 阶段推进顺序建议

```
Sprint A:复用 composition core
  └── 阶段二 - bilingual_video 迁进 composition + SRT snapshot

Sprint B:UI 一致性 + 错误信息打磨
  ├── 全局 ttk style 表
  └── 错误信息 i18n + actionable

Sprint C:Composition v0.2 视觉飞跃
  ├── Karaoke 词级高亮
  ├── Hook 卡 2-3 款模板
  └── 安全区 + 字体多档

Sprint D:Plugin 化铺路
  ├── 4 个 registry 重构成 runtime
  ├── plugin.toml 形态定义
  └── hotclips 拆成 dogfood plugin

Sprint E:Prompt 工程化 + AI 调式
  ├── Playground 跟 plugin 联动
  ├── per-(task, provider) prompt 变体
  └── Few-shot 样本系统雏形
```

各 sprint 间可并行 / 调换;以上仅建议序。

---

## 5. 跟当前 doc 体系的关系

| 文档 | 角色 |
|---|---|
| 本文档 `architecture-vision.md` | **下一阶段统筹愿景** — 战略层,定方向 |
| `composition-style.md` | composition core 详细设计 — 战术层,实现指导 |
| `derivative-snapshot-principle.md` | snapshot 原则 — 横切原则,所有派生遵守 |
| `ai-clip-redesign.md` | AI 切片两层架构历史 — 已落地,作历史参考 |
| `project-restructure.md` | 项目模型基础 — 已落地,作历史参考 |
| `tech-selection-embedded-ai.md` | 内嵌 AI 选型 — 已落地,作历史参考 |
| BACKLOG.md | 任务级清单 — 操作层,具体 ticket |

本文档**只定方向**,不写具体实现。具体到 sprint 内每条 ticket 落 BACKLOG.md。

---

## 6. 文档自身的迭代

本文档明确**非最终版**:

- 每个 sprint 收尾时回顾本文档,把已落地的部分挪进"已完成"小节(或拆到对应专门 doc)
- 下个 sprint 启动时,补充新的认知和方向修正
- 当某一层逻辑稳定到"几乎不动"时,从本文档抽取为独立 doc(类似 snapshot 原则那样独立成文)
- 当 plugin 化真正落地时,本文档可能要再次大改

---

## 7. 一句话总结

> 下一阶段:**把 VideoCraft 从"两个能跑的核心功能"打磨成"两个上得了台面的核心功能",同时把基础框架夯实到能支撑 5+ 种节目稿派生的程度,并通过 plugin 化机制让 LLM 创造性能力以"prompt + python 二元结构"独立演化,不再让核心代码因为新 feature 而膨胀。**
