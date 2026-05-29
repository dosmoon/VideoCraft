# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。

---

## ▶ 重构主线:OTIO 核心数据模型 + AI 生成管线(2026-05-29 深化)

**架构经一轮深挖后收敛到比"Electron 迁移"更底层的地基决策**,奠基稿:
**[`docs/draft/composition-otio-foundation.md`](draft/composition-otio-foundation.md)** ← 本会话核心产出。

> **新对话起手序**:① 本节(接力点)→ ② 奠基稿 `composition-otio-foundation.md`(**权威**:数据模型/渲染/进程拓扑)→ ③ 迁移稿 `electron-migration-design.md`(**只看** IPC/打包/菜单范围;数据模型/渲染/拓扑已被奠基稿取代,见其 §0.5)→ ④ 记忆 [[project_ir_nle_standard]]/[[reference_phase_repo]]/[[feedback_no_universal_standard]]/[[project_recorded_autoedit]]。**第一块代码** = 在 Electron renderer(TS)里建 OTIO composition(奠基稿 §10)。架构已闭环,新对话进实现层。

**已锁定的方向(逐条有 memory 支撑)**:
- **VideoCraft = 一台"剪辑师是 AI"的 NLE**:数据模型 = 不打折的 NLE 行业标准 **OTIO 式全多轨**(N 视频+N 音频+N 叠加轨,统一 Track/Clip/Transition;反 CapCut 自创轨型)。差异只在编辑面(语义段落,无 timeline UI)。见 [[project_ir_nle_standard]]。
- **AI 写语义意图,不吐底层 OTIO**;确定性品类生成器展开成 OTIO;OTIO = 持久化核心编辑模型;一个 compositor → preview≡render(结构性保证)。
- **渲染引擎 = 自建 GPU 合成器**(WebGPU/WebGL)走 OTIO + libass-wasm 字幕层 + WebCodecs 导出;ffmpeg 降为编解码 I/O;**Phase 当引擎参考实现**([[reference_phase_repo]])。否决 Remotion(react2video 阻抗+license)/ Revideo(Canvas-2D+停更)。
- refine ADR-0006(timeline 从瞬态→持久化全多轨;AI 写意图原则存活);关联 ADR-0003 快照 / 0005。

**Electron 迁移降为"UI 外壳"层**:[`electron-migration-design.md`](draft/electron-migration-design.md) 已收窄范围(§0.5:只建 框架 + 素材 + 创作,遗留 menubar 工具全砍含 Publish;§4 渲染后端"留 ffmpeg"作废→改自建 GPU 合成器;§2.3 dual-client 已删,磁盘即真相源)。引擎/UI 边界实测全零 tkinter,业务/引擎 0 行重写。Electron 进程边界是**数据级**(Python 不渲染),不重演现在的 UI 合成 bug。supersede `docs/design/01-architecture.md`(单进程无 IPC)。

**本会话已决(2026-05-29,逐条有 memory/doc 支撑)**:
- 钉1 ✅ **AI 写语义意图、确定性生成器展开成 OTIO**(沿用现成 `hotclips→clip` / `chapters→news_desk` 形状;chapter.py 实证"AI 出 per-point 时间戳→prompt 爆炸"被否)。
- 钉2 ✅ **用户编辑 vs AI 重生成 = 快照 + 显式替换 + 手工调和,不自动合并**(AI/ASR 非确定,无可靠锚,自动 merge=建在沙子上)。
- AI 分析层 vs 创作层 = **多对多**(分析=材料正交物件库;creation 经 get_artifact 组合;EDL 是 creation 级)。
- **prompt hub 判定缺陷已弃** → prompt 回插件、调试每插件自带(AI console 去 Prompts tab)。
- 钉3 ✅ **消解**:无"品类 profile"抽象,品类 = 创作插件本身;视频组件 = **公共全栈库**(UI+compile→OTIO,服务三插件视频预览/编辑/导出,纯数据面板除外),per-plugin 只剩 挑组件+映射+preset+workbench。见 [[feedback_no_universal_standard]]。
- **架构总纲**:框架(运行时+库)+ 两种插件;**功能 = 创作插件**(不是规则引擎);共享只有框架契约(composition/OTIO + Material Model artifact API + host),其余 per-plugin。
- **A1/A2 ✅**(奠基稿 §2.5):OTIO **相对定位**全轨(video/audio/overlay 统一序列 + Gap + Transition,反绝对定位——严格推演后服从标准);分 **Clip/Gap/Transition** 结构类型,kind 派发活在 Clip.kind;TimeMap 降为"源↔输出派生函数"非存储定位。
- **composition 整块 → TS/renderer**:compositor(WebGPU/WebCodecs/libass-wasm)必须在 renderer,components+compile→OTIO co-locate;**Python 退出 composition/render 路径**(只剩 project/material/analysis/AI;ffmpeg→mux)。composition 重构 ≡ 建 Electron renderer。现有 Python composition 随 Tk 退役,词汇作 catalog 复用。
- 菜单留/砍定案(迁移稿 §0.5);奠基稿 §2.5/§3/§4.5/§5/§9 已同步。

**下一步**:架构对齐已闭环(三颗钉 + A1/A2 全解,composition→TS)。第一块代码 = **在 Electron renderer(TS)里建 OTIO composition**——IR 数据结构(奠基稿 §2.5,Timeline/Track/Clip/Gap/Transition,相对定位)+ 不变量单测 + 公共视频组件库(去重 news_desk/clip 重复组件)+ GPU compositor,设计口径一次覆盖三插件(news_video 预览 + news_desk + clip)。自建合成器 spike 验三关(libass-wasm 字幕 / 多段拼接 seek 精度 / WebCodecs 导出)穿插其中。**注:composition 重构 ≡ 建 Electron renderer,不再是独立 Python 任务。**

**✅ 已落地(2026-05-29,§10 step 0+1)**:`desktop/` TS 工程脚手架(pnpm + TypeScript strict + Vitest,**暂不引 React/Electron/WebGPU**——保持 IR 层 substrate 无关、纯可单测)。`desktop/src/composition/` 已建:
- `ir.ts` — OTIO IR 类型(Timeline/Track/Clip/Gap/Transition,相对定位)+ 构造器 + 放置/时长派生(`placeTrackChildren` 累积定位、transition pull 重叠模型、`computeTrackDuration`/`computeTimelineDuration`)+ `validateTimeline`(6 条不变量逐条收集 issue)/`assertValidTimeline`。
- `catalog.ts` — clip-kind catalog,overlay 词汇 **1:1 移植** `src/core/composition/primitives/*.py`(subtitle_cue/hook_text/outro_text/chapter_hero_card/topic_strip/text/image_watermark)+ media(video/audio)。
- `timemap.ts` — TimeMap 派生函数(`buildTimeMap` 从视频轨装配出 segments;`outToSource`/`sourceToOut` 剪掉区返 null)+ `deriveOverlayTrack`(源锚 cue → 合法 OTIO overlay 序列,跨切点拆分,invariant #6)。
- `ir.test.ts` + `timemap.test.ts` — **29 测全绿**,逐条钉死 6 不变量 + TimeMap。`pnpm test` / `pnpm typecheck` 均通过。

**⚠️ 一处对奠基稿 §2.5 schema 的工程偏离(已确认正确)**:给 Clip/Gap/Transition 加了 `type` 结构判别字段(schema 草图里没有)。理由:TS 判别联合需运行期 tag,且 invariant #3「transition 只在两 clip 间」要能运行期判。这是把 A2「三结构类型」显式化,**不是**塌成统一 Item;两轴(结构 `type` vs 渲染图元 `Clip.kind`)仍正交。下次成熟升 ADR 时同步进 schema。

**✅ 已落地(2026-05-29 续,§10 step 2 上半:公共视频组件库骨架)**:`desktop/src/composition/` 新增——
- `assemble.ts` — `OverlaySegment` + `packOverlaySegments`(绝对窗口 → 相对 overlay Track,gap 填充;**单轨禁重叠**,重叠 throw=「该分轨」信号)。
- `components/contract.ts` — `VideoComponent<I>` 契约:`compile(instance, ctx) → Track[]`(纯函数)。关键结构发现:OTIO 相对单轨不能容重叠 clip,故 compile 返 **Track[]**(多数 1,chapter 返 2)。`CompileContext{durationSec, timeMap, cues?}`。
- `components/{subtitle,watermark,card,chapter}.ts` — 6 个共享组件,**去重 + 归一化** news_desk/clip 双份实现(详见下「归一化决议」)。
- `components/index.ts` — `COMPONENT_REGISTRY`。`components.test.ts` — **15 测**(各组件 compile 输出 + 全链路 timeline validate 通过)。**44 测全绿**,typecheck 干净。

**契约洞察**:共享的不是 instance schema(那是 per-plugin 映射),是 **emit 的 OTIO Clip(primitive kind + style + data)**。源锚组件(subtitle/chapter)经 `ctx.timeMap` ripple(`identityTimeMap(dur)` 给不剪辑的 news_desk);输出锚组件(watermark/hook/outro)直接产输出时间窗。

**归一化决议(pre-alpha no legacy,移植即清理)**:① 所有 `*_pct` 统一 float 分数(砍 news_desk int%);② 字段名统一(`textFontsizePct`/`textOpacity`/`imageScale`,砍 news_desk 的 `fontsize_pct`/`opacity`/`scale_pct`);③ text watermark 不再 emit 冗余 image_* style key;④ hook/outro 各只 emit 自己 role 的 style key(legacy 两 role 都盖);⑤ **chapter 样式内联到 Clip.style**(奠基稿 §2.5「style inlined at compile」),弃 overlay_styles registry + style_class 间接层。⑥ subtitle `bg_enabled` 折进 `bgOpacity=0`。

**✅ 已落地(2026-05-29 续 2,step 3 per-plugin 映射层:clip 垂直切片)**:`desktop/src/creations/clip/` 新增——把 **clip 完整链条** `hotclip candidate + config → canonical instance → 共享组件 → OTIO Timeline` 打通并验证。
- `types.ts` — clip wire 形状(**镜像真实 Python**:`config.components` 的 5 种 dict + `<lang>.hotclips.json` candidate{start/end 时间戳串, hook, outro, suggested_title} + `clips_overrides`)。
- `mapping.ts` — config dict→canonical instance 适配器(snake→camel)+ `parseTimestamp`(镜像 clip_tool `_TS_RE`)+ candidate 窗口/hook/outro 解析(override 逐字段胜)+ `stackSubtitleMargins`(移植 composer.py `_stamp_subtitle_margin_v`;同位字幕按列序堆叠 +0.04;**折掉 legacy `effective_block_margin_pct` 双字段**)。
- `assemble.ts` — `buildClipTimeline`:candidate 切源成单 media clip(`sourceStart=start`)→ `buildTimeMap` → 按 config 序驱动各共享组件 → 列序即 z 序(顶部=最高 z)→ 全多轨 Timeline。**取代 composer.py `compile_for_candidate`**(产出从 overlay-only 旧 IR 变全多轨 OTIO)。
- `clip.test.ts` — **10 测**(parse/resolve/adapter/stacking/全装配验证:timeline validate 干净、SRT cue 经 timemap ripple 进 [start,end] 窗口、hook 文本从 candidate 回填、z 序)。**54 测全绿**,typecheck 干净。

**验证到的契约**:SRT 源 cue 不预过滤——`buildTimeMap` 的段 [sourceStart=start, sourceEnd=end] 自动 drop 窗外 cue 并 rebase(等价旧 clip per-cue clamp)。subtitle 经 `ctx.cues` 喂入(host 解析 SRT,组件保持纯)。

**下一步两条岔路**:
- **A**(纯逻辑续):**news_desk 映射层**——证明 dedup(同一套 canonical 组件,news_desk 用另一套适配器,含 int%→float 大改造 + chapter schedule 映射 + `identityTimeMap` 不剪辑路径)。这能正面验证「公共组件库一次覆盖多插件」。
- **B**(上 substrate):§10 step 2 下半 **GPU compositor + 三关 spike**(libass-wasm / 多段拼接 seek / WebCodecs 导出),此时引 React/Electron/WebGPU。

倾向 **A** 收口纯逻辑层(两插件都映射完=组件库设计口径真正验证),再整体上 compositor。

> 注:本会话(更早)完成了 uv 迁移 + portable 构建 + 一批 WebView 预览 bug 修复(canvas 合成 / range 重载 / 管道死锁),都已 commit+push 到 main。clip 原始的两个小诉求(属性框打字、预设默认)在排查 canvas 问题时回退了,待重做(真因已知)。

---

## (旧) 继续 dogfood，暂缓重构

clip 第二轮 dogfood 走完（2026-05-23/24）。功能"基本能用，可用"——决定**先多用一阵**再动测试/重构。

### 起点 HEAD

`a6c9092` —— `0fdb047` 之后跟着 3 个 revert commit（见下"2026-05-25 回滚"段）。
代码等价于 `0fdb047`，但 Antigravity 的 3 个 commit 仍在历史里可追。
**337 测试全绿；7 个 goldens。**

### 当前阶段：dogfood 优先

不急着重构和补测试。先把 clip / news_desk 多用一段时间，攒第三轮 bug 再批量处理。
触发以下任一条件再切到下方"测试 + 重构主线"：

- 第三轮 dogfood 收集到 ≥5 个新引擎/UX bug
- 用户体感 clip/news_desk 卡点已经稳定，不再每天碰新 bug
- 准备开新形态（PPT2Video / 字幕工作台等）需要先稳引擎契约

### 测试 + 重构主线（暂挂）

1. **复盘 12 个 dogfood bug，每个回填一个 reproduction 测试**
   - 已经开了头（subtitle wrap 那条 + CJK 自动检测那条，共 2 个）。
   - 还差 10 条，按 [[project_composition_core]] "契约总览" 清单走。

2. **引擎契约用测试钉死**（测试即文档）
   - `Element.__post_init__` 校验 kind/style/data 形状
   - pct 字段分母语义：`fontsize_pct / stroke_pct / box_padding_pct → target_h`，`margin_x_pct → target_w`，`margin_y_pct → target_h`
   - `PositionedRect.to_drawtext()` / `to_drawbox()` wrapper 封 `iw/ih` vs `w/h` 常量差
   - cue 时间基准：timeline IR clip-relative；preview JS 需要 `-clipStart` 后比

3. **各模块单元测试补全**（不仅是引擎）
   - `creations/clip/composer.py` `expand_for_candidate` 模板展开 corner case
   - `creations/clip/presets.py` 已补 14 测，但缺端到端 apply 后 cfg.components 形状 assert
   - `creations/news_desk/` 各 component 的 default_instance + compile 形状
   - `materials/news_video/` chapters_io / context.json envelope round-trip
   - `core/composition/layout.font_size_px` / `font_line_height_px` 多字体多 size 矩阵

4. **preview ≡ render 不变量**：把"应该有的不变量"用测试钉死。preview 和 render 在同一参数下产生的可对比量必须 byte-equal 或 px-equal。

### 入手顺序建议

1. 12 个 bug 各回填一个 reproduction（最高 ROI）
2. Element + `PositionedRect` 契约校验类
3. layout 计算函数的矩阵测试
4. 各 creation 模块往下挖

---

## 2026-05-25 回滚 Antigravity 3 commit

让 Antigravity 看 composition 还能优化什么 → 它产出三个 commit 后被发现都不解决实际痛点：

| 原 commit | revert commit | 评价 |
|---|---|---|
| `0617dd1` composition Element validation + PositionedRect + 428 测 | `a6c9092` | 给内部代码加防御性校验（违反 [[feedback_check_callers_first]]），单点 OOP 抽象，测试跟 backlog 错位 |
| `b4cdc2e` ComponentSpec 搬到 `creations/component_spec.py` | `2df3977` | 方向对（杀 cross-plugin import），但目标应该是 `core/` 不是 creations 层 |
| `e9ed52a` `atomic_write_text` dedup + 78 测 | `c80d5dc` | 真 DRY，但低 ROI；改基础 IO 默认重试副作用面更大；测试过度 |

伴生事件：一晚上调试 preview overlay 不显示，最初怀疑这 3 个 commit，后来发现是更深的 WebView page-ready race（见 [[project_webview_preview_race]]），跟它们无关。3 个 commit 自身没破坏功能，但因为时间相关性把搜索空间放大。

教训：**别让 LLM agent 做开放式 "什么可以优化" review**（[[feedback_open_ended_llm_optimize]]）。

---

## 已完成（2026-05-23 ~ 2026-05-24）

### 第二轮 dogfood patch（5 commits → push 至 `e886382`）

| Commit | 主题 |
|---|---|
| `6a4e66e` | 修 subtitle wrap budget 3 个引擎 bug（取错 key / 4.7 魔数 / 8 字下限） |
| `3868192` | wrap 端自动检测 CJK，解耦 is_chinese style flag（用户没勾选导致溢出的最后一公里） |
| `841b250` | hub auto-refresh 在 close 时取消 after-id（修 Tcl `invalid command name`） |
| `425473a` | chapter_editor 字幕预览字号 14→48 默认，max 60 |
| `e886382` | clip preset 从 CompositionStyle 切到 components-based（删 `core/composition/presets.py` + 3 处 `template_from_style` + legacy migration；4 builtins 重建） |

### 第二轮 dogfood 的 5 个引擎/UX bug

- subtitle wrap 取错 key（`fontsize` vs `fontsize_pct`）
- compute_subtitle_max_chars 残留 `ass_render_scale=4.7` 魔数
- max_chars 的 `max(8, ...)` 硬下限阻挡新路径正确算出 6
- `is_chinese` 作为 wrap 预算输入是 UX 陷阱（不勾就溢出）
- root.after 在 close 未取消

### 重构欠债剩余（继续挂着）

- **ComponentSpec 搬 `core/composition/component_spec.py`**：当前从 `creations/news_desk/components` import；纯文件移动 + import 修。独立 PR。

---

## 第一轮 dogfood 归档（2026-05-19，8 commits → `b0123be`）

| Commit | 主题 |
|---|---|
| `5de49e5` | short-edge pct 归一化（首版） + clip dogfood fixes |
| `07e0ffa` | 显式 ASS PlayRes + clip-relative cue offset in preview |
| `9dce838` | libass 指 `C:/Windows/Fonts` 找系统字体 |
| `c8ebbc0` | 字号 pct 分母从 short_edge 改回 target_h |
| `eed2c10` | 行间距 1.15 → 1.4（CJK win-metrics，临时） |
| `0a9b03e` | 行间距改 PIL 测的 ascender+descender，无魔数 |
| `86469f2` | hook/outro 统一 drawbox 背景 |
| `b0123be` | drawbox 用 `iw/ih`、drawtext 用 `w/h` |

第一轮 12 bug 三类归属：纯 clip 责任 2 / 引擎封装契约缺失 6 / 引擎自身错 4。

---

## 仍生效的开发约定

- prompt 改动必须 git commit
- 改 UI 布局/模块结构前 grep `docs/`（[[feedback_check_design_docs]]）
- UI 文案先 grep `src/i18n/*.json`（[[feedback_user_facing_naming]]）
- 新 `tk.Toplevel` 弹窗照 `src/ui/dialog_utils.py` docstring 模板写
- 创作**任何**新代码必须遵守 [[ADR-0003]] / [[ADR-0004]] / [[ADR-0005]]
- 创作插件访问素材数据**必须**经 Material Model（[[feedback_material_via_model_only]]）
- 每个创作的 config.json **必须**有单一内存所有者（[[project_creation_config_owner]]）
- pre-alpha 阶段，命名/迁移不要套"用户习惯/保守方案"（[[feedback_pre_alpha_no_legacy]]）
- **per-candidate 数据走模板展开，不走 ctx 隐藏通道**（5.5 教训）
- **所有视觉尺寸量归一化为 `pct of target_h`**（dogfood 教训）
- **drawbox/drawtext 的 ffmpeg 坐标常量约定不同**（dogfood 教训）
- **wrap 预算别从 user-set `is_chinese` flag 推断；从内容自动判**（第二轮 dogfood 教训）
