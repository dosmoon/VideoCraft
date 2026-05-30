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

**✅ 已落地(2026-05-29 续 3,step 3 news_desk 映射层:dedup 正面验证)**:`desktop/src/creations/news_desk/` 新增——同一套 canonical 组件,news_desk 用另一套适配器接入,**正面证明公共组件库覆盖多插件**。
- `types.ts` — news_desk wire 形状(镜像真实 Python:subtitle/text_wm/image_wm/chapter config;**故意与 clip 不同**——int%、`bg_enabled` flag、无 language/bold)。
- `mapping.ts` — 适配器,精确镜像 legacy compile 转换:`block_margin_pct`/`margin_*`/`scale_pct` **int→fraction**;margin clamp[0,0.20]、scale clamp[0.02,0.50];`bg_enabled` 折进 bgOpacity;canonical 独有字段(bold/bgPaddingXPct/language)取中性默认。chapter schedule + 嵌套 style 映射。
- `assemble.ts` — `buildNewsDeskTimeline`:**全源视频轨**(无剪辑)+ `identityTimeMap`(源时间≡输出时间)。**subtitle 不堆叠**(clip 特有,此处每条独立 margin)。chapter 两 mode → **2 overlay 轨**(strip + hero card),验证「一组件多轨」路径。
- `news_desk.test.ts` — **7 测**(int→fraction 转换 + clamp + chapter 映射 + 全装配验证 + identity 路径 cue 时间不变 + chapter 2 轨 + 显式 dedup 断言)。**61 测全绿**,typecheck 干净。

**纯逻辑层(step 1~3)已收口**:IR 核心 + 公共组件库 + clip/news_desk 双映射,端到端 `分析+config → canonical → 共享组件 → 全多轨 OTIO` 全验证(61 测)。组件库设计口径经两插件正面背书。**Python 一行未动。**

**✅ 已落地(2026-05-29 续 4,compositor 纯逻辑脊椎)**:`desktop/src/composition/compositor/resolve.ts`——
- `resolveFrameAt(timeline, t) → FrameSlice`:给定输出时间 t,walk OTIO,各 enabled 轨贡献的 active clip 按 z 升序(paint 序,背景在前)出层;gap 轨省略。**这是 preview≡render 的单一解析器**(同一函数喂预览 + 渲染,非两路对齐)。
- `activeClipsAt(children, t)`:半开 [start,end) 容纳;媒体 clip 算 `sourceTimeSec = sourceStart + (t - clipStart)`(给解码/seek),generator clip 为 null;**transition 重叠区返两个 active clip**(outgoing 先,给 blend)。
- `resolve.test.ts` — **8 测**(单 active / gap 省略 / 媒体源时间 / z paint 序 / disabled 跳过 / transition 双 active)。**69 测全绿**,typecheck 干净。纯逻辑、零 GPU(GPU 层消费 FrameSlice,不重算时序)。

**纯逻辑层全部收口(step 1~3 + compositor 脊椎,69 测)**:IR + 公共组件库 + clip/news_desk 双映射 + 帧解析器。`分析+config → OTIO → 逐帧解析` 全链路可单测验证完毕。**Python 一行未动。**

**✅ 已落地(2026-05-29 续 5,substrate 一轮全过 — 自建 GPU 合成器最小闭环立住)**:在真 Electron renderer 里跑通 + 用户肉眼验。完整发现录:**[`docs/draft/substrate-spike-findings.md`](draft/substrate-spike-findings.md)**。
- **P0 脚手架**:`desktop/` 加 electron-vite + electron 33 + React 19 + @webgpu/types;**main/preload 出 CJS**(ESM main 撞 Node `cjsPreparse` 崩);renderer 经 `@composition`/`@creations` alias(tsconfig paths + vite alias)引纯逻辑层,Vite 自动 `.js`→`.ts`。WebGPU 硬件可用(nvidia/lovelace)。
- **P1 decode→draw**:从 Phase 移植 Demuxer/SampleIndex/FrameRingBuffer/MediaSource/ClipReader(mp4box + 长生命 VideoDecoder + ring buffer)+ WebGPU `Backend`(`importExternalTexture` 画视频帧)。合成测试片(`testsrc2`,烧录帧号+timecode)解码播放。
- **P2 画面层**:`drawFrameSlice(resolveFrameAt(t))` 按 `Clip.kind` 派发——视频外部纹理 + overlay canvas2D→纹理,z 序 alpha 合成。喂**真组件 compile 出的 OTIO**(hook/outro card)。
- **Spike A 多段 seek** ✅:非单调 sourceStart 跨切点 seek 落对 GOP;播放型 reader at-or-before ±几帧容差(逐帧精确留导出层)。
- **Spike B 字幕** ✅:**走 canvas2D→纹理进单一 compositor**(与 Phase 设计殊途同归;jassub 是 display-only + 在本栈跑不起来被否);CJK 正常;3 个 headless 单测钉死。
- **Spike C 导出** ✅:逐帧 `resolveFrameAt → prepare/paint`(**预览同源**)→ **离屏纹理** copyTextureToBuffer 读回(swapchain 不可读=绿屏坑)→ VideoFrame → VideoEncoder → mp4-muxer → 主进程 fs 写。抽帧确认视频+字幕都烧进去,**preview≡render 成立**。
- **测试**:纯逻辑 + 引擎 dispatch 共 **72 测**;引擎渲染层靠真 renderer 肉眼验(headless 覆盖不到,已知)。

**代码定性**:保留=`desktop/src/renderer/engine/`(gpu/source/compositor/overlay/export — 生产引擎)+ `electron/`(壳)。探索性=`src/renderer/app.tsx`(spike harness)/`harness/*`/`spike-assets/`,接真 UI 时整理。**Python 一行未动。**

**下一步(下轮)= substrate → 产品化**:① 接 Python sidecar + 业务 IPC(migration doc M0/M1:project/material/analysis/AI 走 RPC);② 真 UI 壳(Hub + sidebar + 工作台)替换 harness;③ 引擎细化(导出逐帧精确 decode、音轨 mux、剩余 overlay kind、转场);④ libass-RGBA 仅当将来要完整 ASS 特效。foundation doc 可升 ADR(数据模型 + 渲染引擎)。

> **环境坑(记忆已存 [[reference_electron_run_as_node]])**:agent shell 带 `ELECTRON_RUN_AS_NODE=1`,启 Electron 必 `env -u ELECTRON_RUN_AS_NODE pnpm dev`;且本环境 Vite HMR 频繁送陈旧 bundle,改 renderer 后要全重启 + 清 `node_modules/.vite`,别信 HMR;GPU 进程偶发崩 → main 已加 `--disable-gpu-sandbox` + repo-local userData。

**▶ 续 6(2026-05-29 晚,真实视频验证 + harness bug — 这批改动 ⚠️ 未提交,在工作树里;已提交基线 = commit `0f49364`)**:
- 加了 **"Open video…" 文件选择器**(`vc:pickVideo` IPC + `vc-media://local/`)真实片源验证。**结论:真实视频播放基本流畅**(性能 de-risk 基本达成)。
- **Bug 1(已修+已验证)**:暂停拖动进度条 → 抖动/进度条长度跳/闪烁。真因 = rAF 循环**每帧无条件重渲染**(暂停时也是),60fps setState storm 跟受控 slider 拖拽打架 + 读数挤在 slider flex 行里随位数变宽挤压 slider。修:暂停不每帧渲染(只播放时渲);读数移到单独一行;`onSeek` 拖动时渲一次 + 停手 120ms debounce 一次 exact 帧定格。用户确认"不闪烁了"。
- **Bug 2(已修,⚠️ 未验证 — 明天先验这个)**:拖到**最右端/播到结尾**黑屏。真因 = clip 时间窗半开 `[start,end)`,`t=durationSec` 无 clip 覆盖 → 露清屏底色。修:`renderAt` 把 t 夹到 `durationSec - 1/FPS`(显示最后一帧)。**改完用户就收工了,没验**。
- **明天新对话第一步**:① Ctrl+R 重载验证 Bug 2(末端不再黑屏);② 把续 6 这批 harness 改动(file picker + 抖动修 + 末端夹取)作为跟进 commit 提上(基线 `0f49364` 之后);③ 再回到下轮主线"substrate → 产品化"(见上"下一步")。
- 改动文件(工作树未提交):`electron/main.ts`(pickVideo IPC)、`electron/preload.ts`、`src/renderer/global.d.ts`、`src/renderer/app.tsx`(loadMedia 重构 + Open 按钮 + 抖动修 + 末端夹取)、`src/renderer/engine/compositor/draw.ts`(drawFrameSlice 加 exact 透传)、`src/renderer/engine/source/ClipReader.ts`(已在基线内的 frameAtExact)。

> 注:本会话(更早)完成了 uv 迁移 + portable 构建 + 一批 WebView 预览 bug 修复(canvas 合成 / range 重载 / 管道死锁),都已 commit+push 到 main。clip 原始的两个小诉求(属性框打字、预设默认)在排查 canvas 问题时回退了,待重做(真因已知)。

**▶ 续 6 收尾状态更新(2026-05-30)**:续 6 那批 harness 改动**已提交**为 commit `0e76507`("desktop: real-video harness — file picker + paused-seek jitter fix + end clamp (WIP)",基线 `0f49364` 之后),工作树干净。即:续 6「明天第一步」的 ② commit **已完成**。① Bug 2 末端黑屏修复在 `app.tsx:159-162`(`renderAt` 把 t 夹到 `durationSec - 1/FPS`)——代码逻辑已复核正确,但**肉眼验仍欠**(需启 Electron 拖到末端看;headless 覆盖不到,与 substrate 渲染层同类)。

---

## ▶ 续 7(2026-05-30,productization 轨①:Python sidecar + JSON-RPC IPC 地基落地)

主线"substrate → 产品化"四轨(见续 5 末「下一步」)中选**轨① Python sidecar + 业务 IPC** 先行——它是 UI 壳(轨②)依赖的地基。权威设计 = `docs/draft/electron-migration-design.md` §2-3。**Python 业务/引擎一行未动**;sidecar 是**薄 dispatch 层**,只把已有 core/Project/Material API 转成 RPC。

**✅ 已落地 — Python 侧 `core_rpc/`(薄 JSON-RPC 2.0 sidecar,32 测全绿)**:
- `protocol.py` — JSON-RPC 2.0 报文 + 错误码 + `parse_request`/`make_response/error/notification`(纯数据,无 I/O)。
- `registry.py` + `jobs.py` + `session.py` — `@rpc_method` 注册表 + `Context`(handler 入参);长任务 `JobRegistry`(job_id + `progress.<kind>` + 终态 `event.job`,worker 线程);`Session` = **单一内存所有者**持当前 Project + 缓存 material model(subscribe 回调跨调用存活,§2.3)。
- `dispatch.py` — `dispatch_message(ctx, obj) → response|None`:**transport-free 可单测内核**(malformed→INVALID_REQUEST / 未知→METHOD_NOT_FOUND / RpcError 透传 / 其它异常包成 HANDLER_ERROR;通道永不因 traceback 而死)。
- `methods/{system,project,material}.py` — 绑定**只读 + 生命周期**面:`system.ping/echo/demo_job` + `job.cancel/active`;`project.recent_list/open/close/current/list_material_types/list_material_instances/list_materials/list_creations`;`material.slot_readiness/get_artifact`(经 `materials` registry `instance_factory` 解析,**零硬编码 plugin 名**,ADR-0004)。`material` 的 dataclass(SlotState)经 `dataclasses.asdict` 通用序列化,Path→str。
- `server.py` — stdio main(`python -m core_rpc.server`):**二进制帧**(`sys.stdin/stdout.buffer`,换行分隔)——**关键 Windows 坑**:text-mode stdout 会把 `\n`→`\r\n` 破坏帧,故只走 `.buffer`;reader 主线程 dispatch、**单 writer 线程 drain 队列**(§2.1 stdin 死锁教训:写必须 off-thread)、job 线程经同队列 emit;**stdout 仅 JSON-RPC,日志/traceback 全 stderr**;启动自 bootstrap `src/` 进 sys.path + `load_plugins()`。
- 测试 `tests/core_rpc/`(`pyproject` pythonpath 加 `"."` 让 sidecar 包可导入):`test_protocol`(7)+ `test_dispatch`(经 tmp_project 喂 dict 验响应/事件,15)+ `test_jobs`(progress/cancel/终态,3)+ **`test_server_subprocess`(真 `python -m` 子进程跑 stdio,4)**——后者是唯一覆盖 server.py 实帧+线程的;**CJK+emoji 经管道 byte-clean 验证**(Windows 帧坑实证关闭)。**32 测全绿。**

**✅ 已落地 — Electron 侧(typecheck 干净 + 72 测全绿)**:
- `desktop/electron/sidecar.ts` — `Sidecar` 管 python child:spawn `myenv/Scripts/python.exe -u -m core_rpc.server`(cwd=repo root,env 剥 `ELECTRON_RUN_AS_NODE` + 强制 `PYTHONUTF8`)、换行分帧、id 关联 request/response、notification→EventEmitter、`SidecarError` 携 code/data、stderr 转 console。
- `desktop/electron/main.ts` — whenReady 起 sidecar、before-quit dispose;`ipcMain.handle("vc:rpc")` 返**tagged reply**(`{ok,result}`|`{ok:false,code,message,data}`——因 ipc 抛错会丢 JSON-RPC code/data);notification 经 `webContents.send("vc:rpc:notification")` 广播全窗。
- `desktop/electron/preload.ts` — `window.vc.rpc.call(method,params)` + `.onNotification(cb)→unsubscribe`。
- `desktop/src/renderer/ipc/client.ts` — 类型化客户端:`rpcCall<T>` 拆 tagged reply→值 or 抛 `RpcError`;`rpc.{ping,echo,recentList,openProject,closeProject,currentProject,listMaterials,listCreations,slotReadiness,getArtifact,onNotification}` 方法桩 + `ProjectBrief`/`SlotState` 类型。`global.d.ts` 同步 `VcRpcApi`。
- `desktop/src/renderer/app.tsx` — 加 **sidecar 握手 smoke 面板**:mount 时 `rpc.ping()` + `rpc.recentList()`,顶部状态行显示 `✓ sidecar protocol 1 · N recent project(s)`(失败显红)——这是 renderer→main→sidecar→core 全链路的**启动即见**验证(spike harness 读数,非产品 UI)。

**验证状态**:Python transport 全链路**已实证**(in-process 28 测 + 真子进程 4 测 + 一次性 smoke 跑通 ping/echo-CJK/unknown/recent_list=10/demo_job 全过)。Electron IPC 胶水 **typecheck 干净 + 72 测**,但 renderer→sidecar **live 跑(肉眼验启动状态行)欠**——与 Bug 2 同类 human-in-loop(需 `env -u ELECTRON_RUN_AS_NODE pnpm dev` 启 GUI 看顶部绿条)。

**⚠️ 全部未提交**(在工作树):新增 `core_rpc/`(8 文件)+ `tests/core_rpc/`(6 文件)+ `pyproject.toml`(pythonpath 加 `.`);改 `desktop/electron/{main,preload}.ts` + 新 `desktop/electron/sidecar.ts` + `desktop/src/renderer/{global.d.ts,app.tsx}` + 新 `desktop/src/renderer/ipc/client.ts`。

**下一步**:① **肉眼验** sidecar live(启 Electron 看顶部绿条 `✓ sidecar protocol 1`);② 提交续 7 这批(基线 `0e76507` 之后);③ 继续轨①**写操作面**(`project.create`/`material.add_source_video`/`generate_subtitles`/`ai_fill_context` 等长任务,走 job + 事件 + 取消;§2.2 各域剩余方法)或转**轨②真 UI 壳**(Hub+sidebar 替 harness,消费现有只读 RPC);④ render/preview 域(`preview.compile` 留 Python JSON 翻译、`render.start` job)。foundation/migration doc 可升 ADR(数据模型 + 渲染引擎 + IPC 拓扑)。

**▶ 续 7 附(2026-05-30,同会话:Electron 33→42 foundation bump + Win11 26200 sandbox 兜底)**:
- 起因:用户拿来一条"Win11 Build 26200 sandbox 不兼容致 Electron 39-42 子进程崩(exit -2147483645)"的工单问是否命中。核查:**我们正在 Build 26200**,但脚手架 `package.json` 写死 `^33.3.1`(疑似抄 Phase 仓),装成 **33.4.11**——**已 EOL**(最新 42.3.0,Electron 只支持最新 3 大版本=40/41/42,我们落后 6 个),Chromium ≈130 vs 最新 ≈140,**WebGPU/WebCodecs 落后 ~10 代**(正是自建合成器命脉)。33 反而"躲过"了那 bug,但为躲临时上游事故锁死 EOL 版本 = 反模式([[feedback_early_stage_foundation]])。
- 决议(用户拍板)**升到最新 42**。已做:`package.json` `^33.3.1→^42.3.0` + `pnpm install`(装成 42.3.0);`main.ts` 加 **方案 B sandbox 兜底**——条件式,只在 `win32` + `render-process-gone`/`child-process-gone` 且 `exitCode===-2147483645 && reason==='crashed'` 时**带 `--no-sandbox` 自重启一次**(`--vc-no-sandbox-relaunch` 标志防无限循环);健康机器保留沙箱;注释标注"上游修复后移除"。与既有 `--disable-gpu-sandbox` 叠加。
- 验证:**typecheck 干净(对 42 自带 type defs)+ 72 测 + `pnpm build` 全过**(main/preload/52 renderer 模块均编译)。**⚠️ 未提交**(`desktop/package.json` + `pnpm-lock.yaml` + `desktop/electron/main.ts`)。
- **live 验进展(2026-05-30,这台 26200 实测)**:
  - ✅ **42 干净启动,没崩**:`pnpm dev` → main 起 + `[core_rpc] ready` + 无 `render-process-gone`/GPU 崩/`[sandbox]` relaunch。**方案 B 根本没触发** → 印证工单点名 39-41、**42 已修**;兜底留作保险。
  - ⚠️ **坑 1(已修):Electron 二进制没下载**。bump 后 `pnpm install` 装了 42 包但**没跑 electron postinstall**(下二进制),`pnpm dev` 报 `Error: Electron uninstall`。修:`node node_modules/.pnpm/electron@42.3.0/.../electron/install.js` 手动拉(226MB)。**根因 = pnpm `onlyBuiltDependencies` 的 build script 在纯版本 bump 时没自动跑;打包/CI 时注意。**
  - ⚠️ **坑 2(已修):`vc-media://` 跨域 fetch 被 CORS 拦**。Electron 42/Chromium ~140 收紧自定义 scheme 跨域 fetch:从 `http://localhost:5174`(dev origin)fetch `vc-media://` 被拦(`Cross origin requests are only supported for ... chrome/data/http/https`)。**33 不要求,42 强制**。修:`main.ts` 的 `registerSchemesAsPrivileged` privileges 加 **`corsEnabled: true`**。
  - ⏳ **欠**:三关 spike 在 Chromium ~140 的肉眼回归(Demo 画面 / Subtitle / Export)+ 顶部 sidecar 绿条——窗口在屏上,待用户确认。
  - 注:electron-vite 2.3 改 `main.ts` **不自动重启 electron**,得手动杀 `electron.exe` + 重跑 `pnpm dev`(memory 已记 HMR 不可信)。

## ▶ 续 8(2026-05-30,productization 轨②首切片:真 Hub UI 壳 — read-only RPC 端到端 live 验通)

续 7 sidecar 只读面建好后,选**轨②真 UI 壳**先行(而非轨①写操作面)——理由:写方法无 UI 消费者会"猜形状",先用真 UI 把已有只读面端到端跑通,反推 UI 真正需要的写方法。**首切片 = 项目 launcher + 素材 sidebar 树,纯只读,additive(不吞 harness)**。Python 一行未动。

**已落地(desktop 侧,typecheck 干净 + 72 测)**:
- `vc:pickFolder` IPC(`main.ts` + `preload.ts` + `global.d.ts`,镜像 `vc:pickVideo`)——launcher 选项目文件夹。
- `src/renderer/hub/Hub.tsx` — **首个真产品 UI**,全由只读 RPC 驱动:① launcher(`project.recent_list` 拉真实最近项目 / `project.open` / `project.current` 复用 sidecar 已开项目 / `pickFolder→open`);② 项目视图 sidebar(`project.list_materials`+`list_creations` 出树,每个 material 实例 `material.slot_readiness` 出 3 slot=源视频/新闻背景/字幕,`✓`绿/`✗`红/`🔒`锁 + summary,**零前端硬编码**)。
- `src/renderer/shell.tsx` — 顶部 **[Hub | Spike harness] 切换**,默认 Hub;harness 只在选中时 mount(WebGPU heavy init 不空跑)。**additive**([[feedback_flexibility_over_perfection]]:新 UI 不吞旧工具)。`main.tsx` 渲 `<Shell>`。
- **作用域刻意收窄**(migration §0.5:Electron 壳 = 框架+素材+创作,legacy menubar 工具全砍)——`docs/design/03-ui-hub.md` 的 26-工具菜单 Hub 是旧 Tk 版,**对 Electron 壳已 superseded**;workbench + tab-0 预览模型留后续切片。

**live 验通(这台 26200,用户肉眼)**:① Hub launcher 真实最近项目列表出来;② 点开项目 → 素材 sidebar 树 + slot 状态正确;③ 切 Spike harness WebGPU 画面还在(additive 没破坏);④ 无红字报错。**证明"瘦客户端 renderer + sidecar 单一所有者"架构在真实数据上成立。**

**⚠️ 未提交**(在工作树,基线 `c941196` 之后):`desktop/electron/{main,preload}.ts`、`desktop/src/renderer/{global.d.ts,main.tsx}`、新 `desktop/src/renderer/hub/Hub.tsx` + `shell.tsx` + task.md。

**下一步**:① 提交续 8(单 commit);② 继续轨②:把"创作实例单击 → 开工作台 tab"接上(clip 工作台首选,migration §4 试点)——这会**首次需要写操作面**(`creation.load_config`/`update_component` 等),轨①写方法**届时按 UI 真实需要补**(避免猜形状);③ 或先补 material 写长任务(`add_source_video`/`generate_subtitles`,job+事件+取消)。preview/render 域待 composition Python/TS 边界理顺。

## ▶ 续 9(2026-05-30,轨② 第二切片:creation 写操作面 — sidecar 首个写,live 验通)

续 8 只读 Hub 之后接上**创作工作台 + 写操作面**(下一步②那条)。**架构关键一环**:renderer 瘦客户端发意图 → sidecar 单一所有者写 → 落盘 + 广播,base 层零硬编码 plugin 名。

**已落地(Python,37 core_rpc 测 + clip arch 测不破)**:
- **creation 插件契约扩展**:`CreationType` 加 `config_owner_cls`(单一 config 所有者类;契约 = classmethod `load(path)` + 实例 `save(path)` + dataclass asdict-able + `components: list[dict]`)。clip `__init__` 注册 `ClipInstanceConfig`。**core_rpc base 层经注册表解析,绝不 import "clip"**(ADR-0004,与 material 的 `instance_factory` 同构)。
- `session.py` — `creation_owner(type,inst)→(owner,path)`:经注册表 `config_owner_cls.load()` 装载 + 缓存 = **单一内存所有者**([[project_creation_config_owner]]);set/close_project 清缓存。
- `methods/creation.py` — `creation.load_config`(asdict)/`list_components`/`update_component`(按 id 浅合并 patch → `owner.save(path)` → 广播 `event.creation.changed`;id/kind 结构字段防改写)。`load_plugins` 加 `import creations.clip`。
- `tests/core_rpc/test_creation.py`(5 测):load/list + **update 落盘验证(读回 config.json 确认 enabled 持久化)** + 未知 id/未知 type 错误 + id/kind 不可改写。

**已落地(desktop,typecheck + 72 测)**:
- `ipc/client.ts` — `Component` 类型(id/kind/enabled + 任意 style)+ `loadConfig`/`listComponents`/`updateComponent` 方法桩。
- `hub/Hub.tsx` — 创作实例行变**可点按钮** → 右侧 `<main>` 开**工作台**(sidebar | main 双栏布局重构);`Workbench` 列出组件(kind+id+`enabled` 勾选框),切换 → `updateComponent` 写盘 → 重读刷新。一次一个工作台(本切片)。

**live 验通(这台 26200,用户)**:开有 clip 创作的项目 → 创作区点 clip 实例 → 工作台组件列表出来 → 切 `enabled` **真写 config.json**(关掉重开状态保持=落盘确认),无报错。**写路径零旁路 dataclass owner。**

**⚠️ 未提交**(基线 `8d62037` 之后):Python `src/creations/__init__.py` + `src/creations/clip/__init__.py` + `core_rpc/session.py` + 新 `core_rpc/methods/creation.py` + `core_rpc/methods/__init__.py` + 新 `tests/core_rpc/test_creation.py`;desktop `ipc/client.ts` + `hub/Hub.tsx`;task.md。

**下一步**:① 提交续 9;② 工作台深化——组件**样式字段编辑**(不只 enabled 开关:`update_component` 已支持任意 patch,UI 补字段控件)+ 组件增删排序(`creation.add/remove_component`,需引 components spec=会拉 tkinter,得先把 spec 的 default_instance 与 tk 面板解耦)+ candidate/导出 tab;③ 或补 material 写长任务(`generate_subtitles` job 流);④ bind_material(快照,ADR-0003/0005)。

**✅ 续 9 续(2026-05-30,同会话:工作台通用属性编辑器 — 纯 TS,上面"下一步②"前半)**:`Hub.tsx` 的 `Workbench` 升级——点组件行展开(▸/▾)`PropertyPanel`,按**运行期值类型**自动选控件(boolean→checkbox / number→数字框 / string→文本框,`#RRGGBB` 加色块);文本/数字 **blur+回车提交**(不每字符写),走已有 `creation.update_component` 任意 patch → 落盘 + 重读 splice。`update_component` 的 arbitrary-patch 早支持,纯 UI 增量,**Python 一行未动**。typecheck + 72 测 + **live 验通**(改 fontsize_pct/color/bold 落盘,关掉重开保持)。剩余②后半(组件增删排序 = 需解耦 components spec 的 tk 面板)与 ③④ 未动。

**✅ 续 9 续 2(2026-05-30,工作台 inline 预览第一跳:源预览接通 GPU 引擎)**:`hub/WorkbenchPreview.tsx` 新增——经 RPC `load_config → bound_material → material.get_artifact("source")` 解析绑定素材的源视频,喂续 5 的 GPU 引擎(`Backend`+`MediaSource`+`ClipReader`+`resolveFrameAt`+`drawFrameSlice`)渲染,带 scrubber。**作用域:仅源、无叠加层**(标注;改组件这里暂不变)——证明 RPC→素材→GPU 用真实数据跑通。**修了一个 scrub 黑屏 bug**:预览只渲一次用非阻塞 `frameAt()` → 新 seek 解码未就绪返 null(黑)、下次返旧缓冲帧(图),严格交替;修=① 暂停单帧改 **exact 模式**(`frameAtExact` 阻塞等精确帧)② **latest-wins 合并**(拖动有飞行中渲染则记最新、完后接着渲)。typecheck + 72 测 + **live 验通**(连点不同位置稳定正确帧,不再交替黑屏)。**下一跳**:接 `buildClipTimeline`(候选+字幕+config)→ 预览反映编辑的叠加层。引擎渲染层 headless 覆盖不到,靠真 renderer 肉眼验(同 harness)。

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
