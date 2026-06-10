# 重构奠基:OTIO 核心数据模型 + AI 生成管线

> **状态**:草案 / 2026-05-29 · 成熟后升级为 ADR(数据模型一条;可能再拆渲染引擎一条),并 **refine [ADR-0006](../adr/0006-composition-timeline-ir.md)**、关联 [ADR-0003](../adr/0003-editor-modules-decoupling.md)/[ADR-0005](../adr/0005-componentized-data-layer.md)。
> **性质**:整个渲染/编辑层重构的**地基文档**。先于 substrate 实现、先于 UI、先于 Electron 迁移落地的数据模型与管线决策。
> **关联**:[`electron-migration-design.md`](../_archive/electron-migration-design.md)(UI 外壳迁移;其"渲染后端留 Python ffmpeg"一节被本文 §4 取代)。

---

## 1. 题眼:一台"剪辑师是 AI"的 NLE

> **VideoCraft = 一台 NLE,只是"剪辑师"是 AI,不是手工 K 帧的人。**

OTIO 多轨结构**以下**(预览 / 渲染 / 合成)跟 DaVinci 一模一样;**唯一不同 = 这根结构怎么被生产**——DaVinci 靠人拖拽 K 帧,VideoCraft 靠 AI 生成。

由此两条结构性结论,贯穿全文:

1. **数据结构必须是不打折的 NLE 行业标准(OTIO),不是为 AI 生成另搞一套。** 因为"视频这件事"本身就是多轨的,跟谁来编辑无关。
2. **preview 与 render 吃同一份 OTIO、走同一套合成逻辑 → preview≡render 是结构性保证**,不是靠两条路径对齐凑出来的(这正是当前 ffmpeg 烧录 + canvas 近似预览那套永远消不掉差异的根因)。

VideoCraft 的**全部差异收敛到"编辑面"**:语义级、有意义段落的编辑(留哪些段、章节、转场、品类风格),AI 生成 + 用户段落级微调,**不暴露 timeline UI、不做逐帧 K 帧**。

---

## 2. 核心数据模型:OTIO 式全多轨

### 2.1 为什么是 OTIO

- **OpenTimelineIO**(Pixar / ASWF;Premiere、Resolve、Flame、Nuke Studio 等互换都用它)是剪辑数据的**行业标准**,存在的全部目的就是"让剪辑数据跨工具、跨时间不腐烂"。
- **数据模型是整个引擎里最难事后改的一层**——渲染器、编辑面、AI 生成、导出全挂在它上面。把这层钉在十年验证过的标准上 = 地基不会因"当初模型设窄了"而塌(呼应 [[early-stage-foundation]]:早期就把最核心的选对)。

### 2.2 模型形状(OTIO 概念)

```
Timeline
└── Stack of Tracks            ← 每条 Track 有 kind: Video / Audio
      └── items: Clip | Transition | Gap
            Clip = media_reference + source_range(源 in/out, RationalTime)
                   + transform / opacity / effects / metadata
合成语义 = 视频轨按轨序堆叠(blend/opacity);音频轨混音;相邻 clip 间 Transition
```

**N 条视频轨 + N 条音频轨 + N 条叠加/字幕轨,全是 Track,统一对待。**

> 上面是 OTIO 自身概念(用 RationalTime)。**我们的适配**:时间用 **float 秒**、相对定位、分 Clip/Gap/Transition 三型——具体 schema 见 §2.5。

### 2.3 反 CapCut:统一模型,不自创轨型

剪映的重大缺陷 = 给 PIP / 贴纸 / 文本 / 特效各搞**专属轨型 + 专属面板**,把统一模型碎掉,结果每加一个能力都得再发明一套。**本项目红线:看到"给 X 单独搞个轨/单独定义"的冲动,先问"标准 NLE 用统一 Track/Clip 是不是已经表达了"(八成是)。**

**VideoCraft 的远景全部由统一模型"白送":**

| 远景能力 | 在统一模型里就是 |
|---|---|
| 视频融合 / 画中画 / B-roll | 上层视频轨叠下层,按轨序合成(多一条视频轨,不是一个"融合特效") |
| 多段拼接 / 精简录播 | 视频轨上的多个 Clip(各带 source_range)+ 段间 Transition |
| 多音轨(源音频 / 配乐 / TTS 旁白) | 多条 Audio 轨混音 |
| 字幕 / 卡片 / 水印 | overlay 轨(§2.5 定)上的 generator 类 Clip,按轨序叠加 |

### 2.4 现有 Python IR → 新 TS 模型的 delta

当前 `core/composition/timeline.py`(Python):`CompositionTimeline{duration, tracks:[Track]}`,`Track` 全是 overlay 组件轨,`Element{kind, start/end, z, style, data}`;**base 视频在 IR 外(单 `ClipRange`)、音频不在 IR**。

> ⚠️ 注:**代码不是"扩展这个 Python 文件",而是在 TS 重建**(§2.5:composition→TS,Python IR 随 Tk 退役)。下面讲的是**模型层的 delta**——现有 Python 的 primitive/component **词汇**作 clip-kind catalog 复用,但落地是 TS 新代码,不是改 Python。

模型 delta:
- Track 加 `kind`(video/audio/overlay)。
- 视频/音频轨内放 **media Clip**(带 `source_range`)——多段拼接落在这里。
- 相邻 Clip 间放 **Transition**。
- 现有 `Element`(subtitle_cue / hook_text / topic_strip / chapter_hero_card…)**re-home 成 generator 类 Clip**(kind 仍是 primitive registry key,style/data 进 clip),挂在叠加轨上。现有 primitive 词汇**不丢**,只是换了挂载点。
- 现有 overlay 组件轨**降级为众多轨型里的一种**,不再是全部。

---

## 2.5 具体数据结构(相对定位)+ 不变量

> **代码归属 = TS / Electron renderer。** compositor(WebGPU + WebCodecs + libass-wasm)必须在 renderer;components 编辑 UI + `compile→OTIO` 跟它 co-locate → **OTIO IR 是 TS 类型**。Python sidecar 只管 project / material / analysis / AI;ffmpeg 降为 mux,**Python 退出 composition/render 路径**。现有 `core/composition` 的 Python IR 随 Tk 退役;其 primitive/component **词汇**作为 clip-kind catalog + 公共组件库复用,但 timeline 代码在 TS 重建。下面是语言无关 schema(TS-flavored)。

**OTIO 相对定位**:item 只存**时长**,绝对位置 = 前面 item 时长累积(算出来,不存)。**全部轨(video/audio/overlay)统一这套**——A1 已论证:Gap/相对定位服务的"可编辑序列 + ripple + 转场邻居"语义对装配成立,对叠加也用并行 cut/ripple 对齐,不另搞绝对定位。

```ts
interface Timeline { durationSec: number; tracks: Track[] }

interface Track {
  kind: "video" | "audio" | "overlay";
  z: number; enabled: boolean;
  children: (Clip | Gap | Transition)[];   // 有序;位置由顺序+时长隐式算
}

interface Clip {
  kind: string;            // 渲染图元:"video"|"audio"|"subtitle_cue"|"chapter_card"|...
  durationSec: number;
  sourceStart?: number;    // 媒体 clip:源时间窗起点(窗长 = durationSec)
  mediaRef?: string;       // 媒体 clip:源 id/path
  crop?: CropRect;         // 媒体 clip:空间取景(reframe);缺省=整源。per-clip 变换(ADR-0011)
  style: object; data: object;
}

interface CropRect { x: number; y: number; w: number; h: number }  // 归一化源坐标 [0,1]

interface Gap { durationSec: number }

interface Transition { kind: string; inOffsetSec: number; outOffsetSec: number }
```

**A2 = 分 `Clip / Gap / Transition` 三个结构类型(贴 OTIO),不是统一 Item。** 跟 ADR-0006 不冲突:结构层用这三型;**渲染图元的 kind 派发活在 `Clip.kind`**(两个轴)。

**不变量(可单测,钉死契约)**:
1. `Track.children` 有序;**绝对位置 = 累积时长**(OTIO `range_in_parent`),不存。
2. 媒体 Clip:`sourceStart ≥ 0` 且 `sourceStart + durationSec ≤ 源时长`;v0 无变速。
3. Transition 只在两 Clip 之间;`in/outOffset ≤ 邻居 durationSec`。
4. `Timeline.durationSec = max over tracks(Σ children.durationSec − Σ transition 重叠)`。
5. `Clip.kind ∈ 图元 catalog`;`Track.kind ∈ {video,audio,overlay}`。
6. **overlay 轨派生**:把装配的 cut/ripple 施加到源锚定内容(SRT/分析)→ 合法 OTIO 序列(cue-clip + Gap 交替)。
7. 媒体 Clip 的 `crop`(若有):归一化源矩形,各分量有限、`w,h>0` 且 `[x,y,x+w,y+h]⊆[0,1]`。空间取景是 per-clip 变换,不是叠加组件、不是全局属性(详见 [ADR-0011](../adr/0011-spatial-crop-clip-transform.md))。

**TimeMap = 派生函数(源↔输出),不是存储的定位系统**:由视频轨装配算出,用来把源锚定内容 cut/ripple 成标准 OTIO overlay 轨。`outToSource` / `sourceToOut`,剪掉区返回 null。

---

## 3. AI 生成管线(分层)

**核心决策:AI 写"语义意图",不直接吐底层 OTIO。** 由确定性生成器把意图展开成 OTIO。理由同时守住两条铁律:[ADR-0006](../adr/0006-composition-timeline-ir.md)(AI 写高层意图,不写低层布局/时序)+ [[feedback_ai_call_budget]](别让 AI 做程序工种、吐成千上万低层 token)。

**两层正交,关系是多对多(不是一条流水线)**:

```
AI 分析层 = 材料上一组【正交、可复用】的语义物件库
   SRT / 翻译 / context(5W+) / chapters+titles / hotclips / 未来「有效段·废段·片段评分」…
   每个 = 一个分析 kind 插件(prompt+schema+runner),彼此正交,可独立增删
        │  creation 经 Material Model.get_artifact(key) 各取所需
        ▼  (一个 creation 吃多个物件;一个物件喂多个 creation)
Creation 层 = 按【品类 profile】从库里【挑选 + 组合】若干物件 → OTIO
   news_desk ← chapters + context + SRT;clip ← hotclips + SRT;字幕烧录 ← SRT
        │
        ▼
OTIO Timeline = 持久化的核心编辑模型(用户做段落级微调,不下沉 element/帧)
        │
        ▼
一个 compositor 吃 OTIO → 预览 + 渲染(同逻辑,preview≡render)
```

**三条要点**:
- **AI 不吐底层 OTIO,只吐语义物件**(段时间范围 + 文本 + 分数/标签),由品类生成器(确定性)展开成 OTIO。
- **"留哪些段"的 EDL 是 creation 级输出**(组合材料级分析而成),不是材料级——同一份分析,4 分钟精简版和教程版会组出不同装配。
- **两层独立演化**:加一个分析 kind 不碰任何 creation;加一个 creation 重组现有分析、不需新 AI 产物。= ADR-0004(分析 kind = Tier-2 plugin)+ ADR-0005(material artifact 命名空间)。

**这把 ADR-0006 refine 成**:AI 仍写意图(原则存活);但**编译目标从"瞬态、只有叠加层的 timeline"升级成"持久化、全多轨的 OTIO 编辑模型"**。ADR-0006"timeline 永不持久化/永不被人编辑"那条被本文取代——pre-alpha 无包袱([[feedback_pre_alpha_no_legacy]]),该超就超。

---

## 4. 渲染引擎:自建 GPU 合成器,走我们的 OTIO

(取代 [`electron-migration-design.md`](../_archive/electron-migration-design.md) §4"渲染后端留 Python ffmpeg"一节。)

- **自建 GPU 合成器**(WebGPU / WebGL),在 Electron renderer 内,**直接 walk OTIO**(按 Clip/primitive 的 kind 派发画,正是 Phase `WebGPUBackend` ~150 行那种)。
- **libass-wasm 当字幕层**(canvas/texture 层合成)——保住字幕质量,web 文本比不过 libass 这条不动。
- **WebCodecs 解码 + 导出**;**ffmpeg 降级为编解码 / 封装 I/O**,不再做合成。
- **Phase 是引擎参考实现**(数据模型 / compositor / 回放 / WebCodecs 解码坑全可借;只逐帧 scrub 交互不借)。见 [[reference_phase_repo]]。
- **不用 Remotion 这类"react2video"框架**:它要用自己的场景/时序模型,而我们已自有 OTIO IR + 生成管线,套它 = 翻译进 React 的阻抗 + 不自有 + 规模化 license 崖。OSS 只在**渲染库**层用(WebGL/Skia helpers),不引入**框架**。

**为什么 preview≡render 这次是真的成立**:不再是"ffmpeg 烧录 + canvas 近似"两条路径;而是同一个 compositor、同一份 OTIO,预览就是渲染的实时版本。这是采用 OTIO + 自建合成器的**结构性副产品**,不是额外努力。

---

## 4.5 全栈公共视觉组件库(单一视觉引擎)

**composition = 整个 app 唯一的视觉引擎**。凡是"视频 + 叠加"的预览或渲染——news_video 的视频类预览、news_desk/clip 的编辑/预览/导出——**全走同一套 compositor + 公共视频组件库**。纯数据面板(raw SRT 列表、context 表单、分析 JSON 视图)不归它,仍是普通 UI。

**组件 = 全栈单一定义,但很薄**:
- 一个视频组件只定义两件:**① 编辑 UI(property panel / widget)+ ② `compile() → OTIO`**。
- **compositor 拿 OTIO 同时驱动预览 + 最终渲染** → `preview≡render` 是结构副产品,不是额外努力。
- "全栈 UI→渲染" ≠ 每组件各写一遍 UI/预览/渲染;**一份组件定义贯穿全栈**,重活在共享 compositor。

**公共库,不是每插件自造(修遗留)**:现 `creations/news_desk/components/` 与 `creations/clip/components/` **各自重复造了 subtitle/watermark**(= "每插件瞎搞")。重构抽成**一个公共视频组件库**,catalog 一次覆盖三方所需:`subtitle / watermark(text+image) / chapter-card / hook / outro` + 未来 `video-segment / transition`。

**per-plugin 只剩**:挑用哪些组件 + "分析结构→组件配置"映射 + preset + workbench。组件本身 + 组件→OTIO 翻译 = 公共(见 [[feedback_no_universal_standard]]:公共积木库 ≠ 通用标准)。

**设计口径 = 一次同时满足三个现有插件**(news_video 视频预览 + news_desk + clip),不是 clip-first 再 retrofit。

**一刀铲掉三处遗留重复**:① 每插件组件重复 ② 预览(canvas 近似)vs 渲染(ffmpeg)两套引擎 ③ 素材预览 vs 创作渲染两套 → 统一成 **1 个组件库 + 1 个 compositor**。

> 实施次序:**OTIO IR 数据结构(§10.1,纯逻辑、substrate 无关)是前置**;在它之上建公共组件库 + compositor,设计口径覆盖三插件;然后 news_video 预览 / news_desk / clip 都改成"从库挑子集 + 各自映射"。

---

## 5. 持久化 + 段落级编辑 + "AI 重生成"共存

OTIO timeline 是**用户的核心劳动成果**(留哪些段、切点、转场、顺序),必须**持久化、可复核、可微调**——这正是它不能再是"瞬态编译产物"的原因。

**与 AI 重生成的共存 = 快照 + 显式替换 + 手工调和,明确不做自动合并。**

为什么不自动合并:**AI/ASR 输出非确定**——换 ASR 引擎结果变,同一引擎深度学习模型每次跑也不保证一样,而且**分段本身**(选哪些段、怎么切)每次都变。**没有可靠的"这条新段 ↔ 那条旧编辑"身份**,锚到 ASR 句索引或源时间都救不了。在模糊重叠上做自动 merge / override 自动重贴 = 建在沙子上的过度工程。

政策:
1. **快照(ADR-0003)**:创作只读自己的快照,上游 AI/ASR 重生成**默认不碰创作**。
2. **re-import = 显式 + 确认 + 警告 + 替换**:用户主动"从分析重新导入",明确告知"会替换当前编辑",用户决定。**杀掉当前 `_import_from_analysis` 的 wholesale 静默覆盖(那是违反 ADR-0003 的 bug)。**
3. **调和 = 手工**:系统不建稳定锚、不建 override 层、不自动 merge。用户对照新分析自己手工搬想要的(或接受替换、重做 curation)。
4. (可选 ergonomics,非必须)新旧并排视图**方便**手工搬,但只是看,不自动 merge。

呼应 [[project_creation_config_owner]](re-import 走单一 owner 的受控替换)+ ADR-0003(无静默传播)。

> 教训:**AI/ASR 非确定 → 别在它上面建自动合并/稳定身份系统**;regenerated 分析与用户编辑的调和 = 手工。未来别再提"锚到 ASR 自动合并"这种诱人但站不住的方案。

---

## 6. 品类 = 生成器 profile

教程 / 口播 / 历史故事…**各品类 = 一个创作插件**(§9 钉3:**无独立 "profile" 抽象**)。品类间差异 = 该插件的【挑哪些公共组件 + "分析结构→组件配置"映射 + preset + 段间转场/音轨编排策略】。**不是新轨型、不是新数据结构,是同一 OTIO 模型 + 公共组件库(§4.5)上的不同组合/映射。** 对应 architecture-vision 的 program.* 路线 + [[project_media_modules]];自包含插件形态见 [[feedback_no_universal_standard]]。

---

## 7. 与现有 ADR / 文档的关系

| 文档 | 关系 |
|---|---|
| [ADR-0006](../adr/0006-composition-timeline-ir.md) Composition Timeline IR | **refine**:多轨结构 / kind 派发 / 纯函数 compile 全部保留并升级;"timeline 瞬态、永不持久化、仅叠加层"被本文取代为"持久化全多轨 OTIO";"AI 写意图不写 timeline"原则保留 |
| [ADR-0003](../adr/0003-editor-modules-decoupling.md) 派生解耦 + 快照 | **关联**:OTIO 持久化 + AI 重生成共存走快照原则 |
| [ADR-0005](../adr/0005-componentized-data-layer.md) Material/Creation | **关联**:OTIO timeline 落在 creation instance 内;素材经 Material Model |
| [01-architecture](../_archive/01-architecture.md) 单进程无 IPC(已归档) | 已由 electron-migration-design 标记 supersede |
| [`electron-migration-design.md`](../_archive/electron-migration-design.md) | **互补 + 修订**:本文定数据模型 + 渲染引擎;迁移文档定 UI 外壳 + IPC。迁移文档 §4"渲染后端留 ffmpeg"由本文 §4"自建 GPU 合成器"取代——迁移文档需同步更新 |

---

## 8. 范围红线

- 不做 timeline UI / 逐帧 K 帧编辑(那是 Phase 的场景;VideoCraft 编辑面 = 语义段落)。
- 不为 PIP / 融合 / 字幕 / 卡片 各造 bespoke 轨型或概念(反 CapCut)。
- AI 不吐底层 OTIO(只吐语义意图)。
- 渲染前的数据变换(wrap 等)仍是单一纯函数,preview/render 共用(ADR-0006 不变量 #6 延续)。
- 不碰 Phase repo(只读参考)、不碰 aistack repo。

---

## 9. 三颗钉决议(全决)+ 待验证 spike

**三颗钉(2026-05-29 会话,全部已决)**:
1. ✅ **已决 = 语义意图→生成器展开**(选项 B)。依据:现有 `hotclips→clip` / `chapters→news_desk` 就是这个形状(AI 产语义物件,creation 模板 + 确定性展开器出 timeline);[chapter.py](../../src/creations/news_desk/components/chapter.py) 注释还实证"让 AI 出 per-point 时间戳→prompt 爆炸"被否。详见 §3。
2. ✅ **已决 = 快照 + 显式替换 + 手工调和,不自动合并**。依据:AI/ASR 非确定,无可靠身份可锚,自动 merge = 建在沙子上。详见 §5。
3. ✅ **已解(消解)**:**不存在独立的"品类 profile"抽象——品类 = 创作插件本身**(ADR-0004 plugin = prompt+python),自包含 组件 + "分析结构→组件"映射 + 对接 composition;框架只给三契约(composition/OTIO 输出面 · Material Model artifact API · host)。无通用 profile/规则/expander 要造。news_desk / clip 即模板;加新品类 = 照写一个新创作插件。见 [[feedback_no_universal_standard]]。

**待 spike 验证的三关(自建合成器能不能立起来的最小闭环)**:
1. **libass-wasm 字幕层**合成进 canvas(质量 OK)。
2. **多段拼接 + 转场**(尤其源视频切点的 seek 精度)。
3. **WebCodecs 自托管导出**(帧 → 编码 → 封装)。

---

## 10. 实施前置顺序(建议)

> 前提:**composition ≡ Electron renderer(TS)**(§2.5)。所以这不是"先 Python 纯逻辑、最后再合流 Electron";composition 从第一行就在 TS renderer 里。

0. **脚手架**:Electron renderer(TS)工程 + 单测环境(composition 就住这)。
1. **(纯逻辑,可单测,先做)** OTIO IR 类型(§2.5)+ 不变量单测 —— TS,但不依赖 WebGPU/UI,可独立先写。
2. **公共视频组件库骨架(§4.5)+ GPU compositor**;穿插 spike 验三关(§9:libass-wasm 字幕 / 多段拼接 seek 精度 / WebCodecs 导出)。
3. 把 **news_video 预览 / news_desk / clip 接到公共库 + compositor**(口径一次覆盖三插件)。
4. **AI 生成管线接口 + 各创作插件的映射**(分析结构→组件);Python sidecar 经 IPC 供 project/material/analysis/AI。

---

## 音频 + compositing 实现状态(2026-05-30,commit `d0f8b00`)

> 本节由音频实现会话追加。奠基稿正文写于设计期、**完全没有音频章节**——这是补齐。代码全部在 `desktop/`(TS / Electron renderer),Python 一行未动。

### 音频(端到端落地)

OTIO 模型本就有 `Track.kind="audio"` 与 `Clip.kind="audio"`(catalog `MEDIA_CLIP_KINDS=["video","audio"]`、`style.gainDb`),但**引擎从未实现**:demuxer 只取视频轨、无 `AudioDecoder/AudioContext/AudioEncoder`、导出无声、预览无音画同步。本轮补齐:

- **解码层** `desktop/src/renderer/engine/source/`:
  - `Demuxer.ts` `demux()` 现同时抽第一条音轨(samples + `AudioDecoderConfig` + esds/AudioSpecificConfig `description`,递归 fallback),无音轨优雅降级(`DemuxResult.audio: AudioDemux | null`)。AAC 帧全标 sync。
  - `MediaSource.ts` 暴露 `audio` / `hasAudio`。
  - `AudioReader.ts`(新):长解码 `AudioDecoder` 整轨 → 拼接 planar `DecodedAudio`(Float32 PCM,源采样率)。
  - `sample-types.ts` 加 `AudioTrackMeta` / `DecodedAudio`。
  - `webcodecs-audiodata.d.ts`(新):本 TS DOM lib **缺 `AudioData` 类型**(`AudioDecoder/AudioEncoder/EncodedAudioChunk/VideoFrame` 都在),补最小 ambient 声明。
- **装配层**:`creations/clip/assemble.ts` + `creations/news_desk/assemble.ts` 各产一条 audio Track(单 media clip,`style.gainDb=0`,与视频同窗)。`draw.ts` 显式 `if (track.kind === "audio") continue`——音频非视觉,绝不进 paint。
- **解析层(纯)** `composition/compositor/resolveAudio.ts`(新):`resolveAudioSegments(timeline) → AudioSegment[]`(复用 `placeTrackChildren`,与 `resolveFrameAt` 平行;`dbToGain`)。**预览 + 导出走同一解析**(preview≡render 延伸到音频)。
- **导出混音** `engine/export/audioMix.ts`(新,纯函数,重点单测):segments + 各源 `DecodedAudio` + 输出采样率 → 求和/gain/线性重采样/clamp[-1,1] planar PCM。`encode.ts` 现加 muxer audio 轨(AAC `mp4a.40.2` @48k)+ `AudioEncoder`,在视频 pass 后混音编码;`ExportTab.tsx` 解码源音频喂 `audioSources`。
- **预览播放** `engine/playback/AudioPlayback.ts`(新):Web Audio 按 segment 调度 `AudioBufferSourceNode`+per-seg `GainNode`;`currentTime` 作**主时钟**;`CropPreview.tsx` 加播放/暂停按钮 + rAF 循环(有音轨→音频主时钟,视频帧追;无音轨→墙钟静默回退),seek 同步音频。
- **测试**:`resolveAudio.test.ts`(7)+ `audioMix.test.ts`(8)纯逻辑全覆盖;总 **118 测全绿 + typecheck 干净**。GPU/WebCodecs/WebAudio 部分靠真 renderer 肉眼验(headless 覆盖不到)——**已 live 验通过**(2026-05-30/31,task.md 续 15:预览有声 + 进度条可拖 + 导出 mp4 有声同步)。
- **承重决策**:① 预览音画同步 = 音频主时钟(NLE 标准);② 导出 = decode→mix(PCM)→AAC re-encode,**不做压缩域 passthrough**(clip 任意点切 + gainDb + 未来多轨混音都需 PCM 域);③ 音频解析独立于 `resolveFrameAt`(后者是视觉 FrameSlice)。

### Compositing 现状(本轮复核 = 已完整,转场除外)

- ✅ **多 overlay 轨 alpha 叠加**:`draw.ts` 按 z 升序 paint,Backend overlay 管线 alpha-over。
- ✅ **image_watermark**:`overlay/canvas2d.ts` `drawImageWatermark`(decode→`imageCache`→scale/opacity/position)+ `preloadImageOverlay`,预览/导出均在用。**非 TODO,已实装**。
- ✅ 视频:外部纹理 + fit / 空间裁剪 crop(reframe)。**2026-06-08 升级为 per-clip `Clip.crop` IR 字段**(退役旧 `DrawDeps.cropRect` 渲染旁路;clip + news_desk 统一;见 [ADR-0011](../adr/0011-spatial-crop-clip-transform.md))。
- ⏳ **转场(crossfade / dip_to_black)= 唯一缺口,本轮用户决定暂不做**。地基已就位:IR 有 `Transition` 结构类型 + 不变量,`resolveFrameAt` 已在重叠区返回两个 active clip(outgoing 先)。缺 GPU per-layer alpha blend + 创作产出转场 + UI。当前两形态(clip 单窗口 / news_desk 全片)语义上不需段间转场;真实需求来自未来录播自动剪辑(多段装配)。
