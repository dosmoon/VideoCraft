# ADR-0008 迁移任务追踪（插件全 TS / Python = 能力网关）

> **持久任务清单**（跨会话防遗忘）。权威设计 = [`electron-migration-design.md`](electron-migration-design.md) 顶部「🚩 架构转向」节 + [`docs/adr/0008-...md`](../adr/0008-plugins-ts-python-capability-gateway.md)。本文件只追踪**进度 + 勾选状态**，不重复设计正文。
>
> 状态记号:`[x]` 完成 · `[~]` 进行中 · `[ ]` 未开始 · `⚠️GATE` 需先过人工真机验(headless 验不了,删 Tk/Python 前必过)。每步收口标准 = **build-green**(typecheck + vitest + pnpm build;改 Python 则 pytest)+ commit。
>
> **工作纪律**:per-port 取注入式 `Fs` 接口(`renderer/ipc/fs.ts`)供 vitest fake;`writeJson` 字节级复刻 Python `*.save()`;每步 build-green;**TS 替代测好前绝不删对应 Python**;忠实还原既存语义([[feedback_faithful_port_not_invent]])。

---

## ⚡ 导出速度

### 已落地(2026-06-03,commit `ddf64cf`,已 push)= ~4.5x
news_desk 全源导出原 ~30fps(30 分钟视频要 ~30 分钟)。两刀已修(WebCodecs 路径):
- **砍每帧 GPU→CPU 读回**:`renderOffscreenToBytes`(copyTextureToBuffer + `mapAsync` 同步阻塞 + CPU 重建帧 + 编码器再上传)→ 改 `new VideoFrame(backend.canvasElement)` 直接抓 GPU canvas(浏览器保持 GPU 侧)。**真机验过画面正常**。
- **mp4 流式写盘**:原 `ArrayBufferTarget` + `fastStart:"in-memory"` 把整文件攒内存再整份过 IPC(长视频 >2GB → "Array buffer allocation failed")→ `StreamTarget` 16MiB 块经新 `vc:writeStream:*` 定位写 `.part`(原子 rename)。**修了长视频 OOM 崩溃**。
- 附:`dequeue` 事件背压(替 setTimeout(0) 的 4ms 钳制)、`latencyMode:"realtime"`、AudioReader 去整文件多余拷贝。

**结果**:1080p 现 ~135fps(encoder-bound)。30 分钟视频 ~7 分钟。

### 诊断结论(确凿,别重复踩)
逐帧拆分实测:`decode/overlay/render/io` 全 <1ms,**90% 时间是 encoder**(`encWait ~7ms`,队列贴满)。深挖编码器并行全部无效:
- 单编码器 / 4 个同 realm 编码器 / **4 个 worker 线程编码器** / `prefer-hardware` / `prefer-software` —— **全部 ~135fps**(WebCodecs 软件 H.264 在本 Chromium 是**进程级单线程**,并行打不破;worker 代码已删)。
- **硬件编码不可用**:`getGPUInfo` 实测 Chromium 跑在 NVIDIA 4060 上(active vendor=0x10de)但 `videoEncodeAcceleratorSupportedProfile=[]`(**0 个硬件编码档位**);`getGPUFeatureStatus().video_encode=disabled_software`;`ignore-gpu-blocklist`/`enable-features`/flag 全无效。Chromium Windows 桌面 WebCodecs **不暴露 NVENC**(已知老问题)。
- ⇒ **浏览器内编码永久封顶 ~135fps@1080p**。要更快只能绕开 Chromium。

### 导出设置框架 + 可选引擎(已落地 2026-06-03,commit `551c1d2`→Phase5)
按 NLE 习惯加了**每创作持久化的导出设置**(引擎/分辨率/帧率/码率,存 config.json):
- 架构:`encode.ts` 拆成共享 `runRenderLoop` + 可插拔 `EncodeSink`(`types.ts`);`webcodecsSink.ts`(现状搬移)/ `ffmpegSink.ts`(新)。两引擎复用同一 GPU 渲染循环 → preview≡render 不破。
- `exportSettings.ts`(纯模型 + 归一化 + `resolveBitrate`/`downscaleToShortEdge`);`ExportSettingsBar.tsx`(两 tab 共用);clip 分辨率复用 `output_short_edge`,news_desk 用 `export_resolution` 降采样。
- 主进程 `electron/ffmpeg.ts` + `vc:ffmpegEncode:*`(spawn/stdin 背压/`.part`→rename/probe;`-f mp4` 显式 muxer;退出即 reject 防假死);`h264_nvenc` 探测用 `testsrc` 256²(`nullsrc`/小尺寸会 init 失败)。
- 198 vitest + typecheck + build 绿。

### ⚠️ ffmpeg+NVENC 引擎:能跑通但**搬运税**慢于 WebCodecs —— **已暂缓(2026-06-03 用户拍板),未来处理**
**实测**(news_desk 全源 1080p,真机):ffmpeg+NVENC 路 **~27fps**,反而比 WebCodecs(135fps)慢。逐帧拆分:
- `readback 15ms`(GPU 渲染+`mapAsync` 同步读回)+ `write 21ms`(8MB/帧经 contextBridge 克隆 + IPC 拷贝到主进程)= **36ms/帧全串行**;NVENC 本身 ~3ms 不是瓶颈。
- **根本矛盾**:WebCodecs 在渲染进程内直接编码(无读回、无 IPC);ffmpeg 是独立进程,每帧 8MB 必须 GPU→CPU→IPC 搬过去,这笔搬运税 > 硬件编码省下的时间。**本 GPU-合成-在-渲染器 架构下,ffmpeg 难超 WebCodecs。**
- **决策**:暂缓 ffmpeg 提速;**auto 默认引擎 = WebCodecs**(`defaultEngine` 恒 chromium);ffmpeg 引擎选项保留(能跑、硬件编码、画面/音画已通,只是慢),UI 仍可显式选。

**未来要让 ffmpeg 真正发挥(目标 ~150-300fps)= 三级流水线**(目前全串行):
1. **读回流水线化**:`Backend` 加 N(=3) staging buffer 环,submit(N)/map(N-2) overlap,藏 `mapAsync` 阻塞 → readback 15ms→~2ms(`renderOffscreenToBytes` 故意保留作基础)。
2. **写不串行**:`ffmpegSink.consume` 发完帧不 await,bounded in-flight,overlap 读回与 IPC。
3. **IPC 零拷贝**:`vc:ffmpegEncode:writeFrame` 改用 **MessagePort + transfer ArrayBuffer**(绕开 contextBridge 8MB 克隆)→ write 21ms→~3ms。
- 三者 + 三级 overlap → 瓶颈降到单级 ~3ms。风险:GPU buffer 复用竞态、MessagePort 背压、打包后 ffmpeg 路径、clip `-ss` 音频对齐(均未深验)。
- **保留物**:`encode.ts`/`ffmpegSink.ts`/`electron/ffmpeg.ts` 全部留着(能跑);`renderOffscreenToBytes` 留作读回基础。捡起时从「三级流水线」三步做起。

---

## 前提依赖

- [x] **P2 — 整个 Tk app 退役**(2026-06-03,用户拍板「整个 Tk app 退」+「信任既有验证直接删」)。**删掉**:`launcher.py`/`VideoCraftHub.py`/`operations.py` + `src/tools/`(全部遗留独立工具:下载/语音/翻译/视频/text2video/发布/preferences/ai_console/prompt_console/model_manager,§0.5「砍了」落地)+ `src/ui/`(全部 Tk 对话框/预览)+ clip Tk(`clip_tool`/`clip_editor`/`style_panel`/`composer`/`render_queue`/`components/`)+ `creations/material_binding.py` + 素材 Tk(`materials/news_video/sidebar.py` + `ui/`)+ **dead `core/composition/`**(老 Python 合成引擎,只被 Tk 消费,TS catalog 已复用词汇)+ Tk 打包(`build_portable.py`/`RunVideoCraft.bat`/`.github/workflows/build-portable.yml`)。**de-register**:`materials/news_video/__init__.py` 去 `sidebar_renderer`/`create_handler`。**测试**:删 `tests/composition/` + clip-component/composer/render_queue/subtitle 测 + `test_arch_clip.py`;`test_arch_{materials,news_desk}` + `test_registration` + `test_clip_presets` 裁到存活的 headless/sidecar 不变量。**验证**:sidecar 三插件 import 干净;`pytest tests/` 仅剩 1 个 pre-existing(`test_clip_config::test_load_full_roundtrip` stale-id,[[project_pytest_preexisting_failures]];composition golden-CRLF 两个随删测消失)。**未碰 desktop TS。** ⇒ **A6/B5 解锁**(clip 不再有 Tk 兄弟 import 那些 keep 文件)。
- [ ] **P0/P1 真机肉眼验新壳功能对等**(gate 住 A4 起的接线/删除;headless 验不了)。

---

## Phase A — clip + news_desk 创作全 TS（素材仍 Python 经桥）

- [x] **A1 — `vc.fs.*` 文件 I/O 地基**(commit `ad1352d`)
  - [x] `electron/main.ts`:`vc:fs:{readJson,writeJson,readText,writeText,list,copy,remove,stat}` + `assertInProject` + 项目根嗅探
  - [x] `preload.ts` fs 命名空间 + `global.d.ts` 镜像 + `renderer/ipc/fs.ts`(`Fs` 注入 seam + `realFs`)
  - [x] build-green(typecheck + build + 132 vitest)

- [x] **A2 — clip 所有者 + presets + 组件**(commit pending below)
  - [x] `creations/clip/componentDefs.ts`:**新增**(port `component_defs.py`)。**纠正 C3**:per-plugin **wire** 默认(snake_case `clip_subtitle` dicts + ADDABLE)只在 `component_defs.py`,TS 没有——`composition/components/*` 的 camelCase 默认是另一层(canonical,喂 compile)。所以 clip 港要带这个文件。
  - [x] `creations/clip/configOwner.ts`:镜像 `clip/config.py`(applyPatch 白名单 + `clips_overrides_merge` None-删 deep-merge + 空-drop、add/remove/move + id 唯一/repair、bindMaterial、addableKinds、rendered[]、preset_name);持 `Fs`+path,`save()`/preset 方法经 `Fs`
  - [x] `creations/clip/presets.ts`:镜像 `clip/presets.py`(builtin 懒构造、list/get/upsert/delete、last_used、builtin 保护);经 `Fs` 写 `<presetsDir>/clip_preset.json`(新增 `vc.fs.presetsDir()`)
  - [x] vitest `configOwner.test.ts`(10 测,内存 Fs fake:load/save round-trip、stale-id 修复、applyPatch 白名单 + overrides None-删/空-drop、CRUD+id 唯一+语言继承、bind、presets 排序/apply/save/delete/builtin 保护)
  - **deviation**:`creations/shared/{configOwner 基类,markdownFmt}` **推迟到 A5**(news_desk 给第二个数据点再抽,避免从单例造抽象);`markdownFmt` 归 A3(publish 才用)。

- [x] **A3 — clip preview/render/publish**
  - [x] **A3a**(纯,无素材依赖):`shared/markdownFmt.ts`(port `markdown_fmt.py`)+ `clip/publish.ts`(`renderClipPublish/Index` 纯 + `collectClipSidecars` Fs-backed)+ `publish.test.ts`(8 测)。commit `484df31`
  - [x] **A3b**:`clip/hotclipsRepo.ts`(port `candidates.py`,copy-once 快照,经注入式 `MaterialBridge`——Phase-A 桥 RPC 形状推到 A4 接线再定,**不预先钉 ADR-0004 边界**)+ `clip/render.ts`(port `export.py`:`clip_NNN[_hook]` 命名 + `_eff_*` override-wins + stale 清理 + rendered[] + publish.md/index.md 接线)+ 两个 test(hotclipsRepo 5 含"上游变更不影响快照";render 5:plan override-wins / commit sidecar+docs+persist / stale 清理 / delete 重建 index)
  - **deviation 记录**:`MaterialBridge` 接口注入(`subtitlesDir()`)——Phase A 桥 RPC 选型(ADR-0004 合规)留到 **A4 接线**;render 函数收 `(owner, fs, candidates, projectTitle, langIso)`,候选由工作台经 repo 解析后传入。

- [x] **A4 — 接线 clip 工作台**(✅ 代码 + 真机 GUI 对等验均完成)
  - [x] **A4.1 foundation**(commit `916a4ae`):**决策 Option C** —— Phase A 保留 Python `creation.preview_data` 拿候选(`render.ts` 收候选入参,不依赖 hotclipsRepo),故 **A4 零素材 bridge RPC**;`hotclipsRepo`/`MaterialBridge` 推到 Phase B。新增**唯一**通用框架 RPC `project.creation_instance_dir`(plugin-agnostic,ADR-0004 合规)+ client.ts + pytest。
  - [x] **A4.2 代码已落**(commit 见下;**比原计划低风险**):没有重写 6 个 .tsx,而是**在 `client.ts` 按 `type==="clip"` 分发到 TS owner 后端**(`creations/clip/clientBackend.ts`)。tabs **零改动**(字节不变),只是 config/preset/render 不再走 Python sidecar 而走 `ClipConfigOwner` + `render.ts`,经 `vc.fs` 落盘。news_desk 仍走 Python(A5)。后端**无状态 load-mutate-save**(每次 op 从盘加载→改→存,disk 即真相,无内存缓存一致性问题);候选/源仍来自 Python `creation.preview_data`/`material.get_artifact`(Phase A 桥)。`ClipConfigOwner` 加 `updateComponent`(shallow-merge)。typecheck + 160 vitest + build 全绿。
  - [x] **✅ 真机 GUI 对等验通过**(2026-06-01,用户确认"正常"):clip 工作台样式/候选/导出全部与现状一致;news_desk 不受影响。**A4 完成——clip 是第一个端到端迁到纯 TS 路径并验证的插件。**
  - **保留 Python**(A6 删):config/presets/component_defs/export/publish；**`preview.py` 留到 B4**(候选解析依赖素材模型)。

- [x] **A5 — news_desk 同 A2–A4**(✅ 代码 + 功能验证完成;导出速度遗留见下「⚡ 导出速度」)
  - [x] port:`creations/news_desk/{componentDefs,presets,configOwner,publish,render,clientBackend}.ts`(config/preset/render 全 TS;presets 含 builtin 模板 + project-content 剥离;render 单全源输出 + publish.md 读 context 经 `material.read_context` 桥 + 章节详情转写经 fs 读 SRT 解析)+ `newsDesk.test.ts`(5 测)。client.ts 加 `type==="news_desk"` 分发。typecheck + 165 vitest + build 全绿。
  - **保留 Python(Phase A)**:`preview_data`(媒体/SRT)+ **`imports.py`**(import_resource 快照素材 SRT/章节,需素材文件访问 → 跟 clip hotclipsRepo 一样 defer 到 Phase B);故 `imports.ts` 暂不做。
  - [x] **✅ news_desk 功能验过**(2026-06-01):导出能产出全源 mp4 + output.json + publish.md,功能正常。**A5 完成**(第二个迁到纯 TS 路径的插件)。**唯一遗留 = 导出速度,见下「⚡ 导出速度」(高优 deferred,用户拍板先干完迁移再优化)。**

- [x] **A6 — 退役创作 Python**(2026-06-03,commit `57e102b`;前提 P2 Tk 退役 + A4/A5 验过均满足)
  - [x] 删 `creations/{clip,news_desk}/{config,presets,component_defs,preview,export,publish}.py` + clip `candidates.py` + news_desk `imports.py`
  - [x] 清各 `__init__.py` provider 注册(留 `type_name/single_instance/description_*` 等元数据)
  - [x] 删 `core_rpc/methods/creation.py`(整文件,18 个 provider-delegating 方法)+ `CreationType` provider 字段 + `Session.creation_owner/invalidate_creation` + `_creations` 缓存
  - [x] 删 `tests/core_rpc/test_creation*.py` + `tests/creations/test_{clip,news_desk}_*.py`;裁 `test_arch_news_desk`(去 provider-wiring + imports.py 断言)
  - [~] `client.ts` 死 `creation.*` fallback arm 清理**延后**(永不命中;`noUnusedParameters` 下干净移除需改签名,不成比例)

---

## Phase B — news_video 素材全 TS + 能力网关

- [x] **B1 — TS 素材模型** `materials/news_video/{schema,paths,model}.ts`(对 `Fs`)+ vitest
  - [x] `schema.ts`(port `schema.py`:5 字段 SourceBasicInfo + 15 字段 SourceContext + from/to dict + isEmpty + Fs-backed read/write context/basic_info/meta)+ `schema.test.ts`(3 测)。**deferred**:`context_prompt_block`(AI-prompt 注入)归 B2 能力网关,不在数据层。typecheck + 168 vitest + build 全绿。
  - [x] **`project.material_instance_dir` RPC**(对称 `creation_instance_dir`,plugin-agnostic 框架目录解析,ADR-0004/0008)+ `client.materialInstanceDir` + pytest(`test_material_instance_dir_rpc`)。commit `2cd600a`。
  - [x] `paths.ts`(port `paths.py`:纯路径 helper 接 resolved instanceDir + Fs-backed `sourceStatus`;Python 的 `default_instance`/`instance_dir(project,…)` 不港——TS 里 instance id 总显式,经 RPC 解析)+ `paths.test.ts`(2 测)。commit `2cd600a`。
  - [x] `model.ts`(port `model.py` 数据层子集:paths getters / hasSourceVideo / read·writeContextDict·writeBasicInfoDict / contextCompletion / listSubtitleLanguages / subtitlePath·hasSubtitle / listAnalyses·readAnalysis·analysisSummary / analysisPath / slotReadiness / getArtifact)+ `model.test.ts`(7 测)。typecheck + 177 vitest + build 全绿。
    - **deviation([[feedback_i18n_symmetry]])**:`slotReadiness` 返**结构化事实**(filled/total、langs[]、source 描述符),**不发明** Python 的中文 summary 串——UI 文案在 renderer 走 `tr()`(B3 接线时),数据层不产 user-facing 串。
    - **不港(归 B2 能力网关)**:business actions(commit_source / ai_fill_context / run_asr / run_translate / run_analysis / import_subtitle / quick_fix_subtitle / check_subtitle)+ project-meta accessors(source_language / translated_languages,renderer 经 project.current 已有)。
    - analysis kind→suffix 表内联进 model(port `core.subtitle_analysis.ANALYSIS_TYPES` 仅 suffix 子集;display 元数据留 analysis UI 层)。
- [~] **B2 — 能力网关**(核心已落;ai_fill 决策见下)
  - [x] `core/subtitle_pipeline.py` 加 `run_asr_paths/run_translate_paths`(注入 path + 调用方更新 meta,plugin-free;`(project)` shim 保留至 Tk 退役,`_nv_paths` import 移进 shim 内 → 消除 module-level `TODO(ADR-0005)` 越界)+ `tests/test_subtitle_pipeline_paths.py`(5 测)。commit `7aebcf5`。
  - [x] `core_rpc/methods/capability.py`:路径式 job `acquire_source/asr/translate/analyze` + sync `subtitle_check/subtitle_quick_fix/save_chapters` + 通用 `llm_extract`(复用 `_jobs_util.py` cancel/progress bridge;`_in_project` 路径守卫;**不发 domain 事件**,renderer 在 job 完成时刷新)+ `tests/core_rpc/test_capability.py`(11 测,AI/网络/acquire monkeypatch + sync 真跑)。注册进 `methods/__init__.py`。
    - **🚩 ai_fill 决策(用户拍板 2026-06-01)= 纯通用**:capability **不碰新闻语义**,只暴露通用 `llm_extract({prompt, schema, task})` → `ai.complete_json`。新闻 prompt 模板 + 15 字段 schema + 读 basic_info/platform 拼 prompt **全移到 TS 插件侧**(归 B3/B4 接线,B2 不做)。故 **`ai_fill.extract` 不移进 core**(该子项作废);现有 `materials/news_video/ai_fill.py` 留给 Tk 旧路径至 A6/B5。core 零领域知识,对齐 ADR-0008 终态。
    - **deferred**:`capability.probe`(底层只有私有 `source_acquire._ffprobe`,且 `acquire` 已返回 duration/w/h,主流程不需要独立 probe;真要时再加公开 probe)。
  - [x] ~~`materials/news_video/ai_fill.extract` 移进 `core/`~~ — **作废**(见上 ai_fill 决策:改 TS 侧拼 prompt + 通用 llm_extract)。
  - **欠(B3/B4)**:news prompt 模板 + 15 字段 schema 移到 TS;`capability.asr` 后调用方持久化 `project.meta.language.source`(需 project meta 写 RPC,B3 加)。
- [~] **B3 — 接线素材工作台** `workbenches/material/*` → TS model + 经 `runJob.ts` 调 `capability.*`;`client.ts` 换 `material.*`→`capability.*`
  - [x] **B3.1 news prompt 移 TS**(commit `c532c0b`):`materials/news_video/aiFill.ts`(`NEWS_CONTEXT_SCHEMA` 15 字段 + `NEWS_CONTEXT_TASK` + `buildContextPrompt` 港 ai_fill.py prompt 拼装;prompt 中文原文保留=领域数据非 UI)+ `aiFill.test.ts`(4)。纯逻辑,未接 live 工作台。
  - [x] **B3.2a 读路径接线**(commit `2c0838a`):`materials/news_video/clientBackend.ts`(`materialBackend`)+ `@materials` alias(tsconfig/vite/vitest)。`client.ts` 按 `type==="news_video"` 把**纯读**方法分发到 `NewsVideoModel`(readContext/contextCompletion/listSubtitleLanguages/readSubtitle/getArtifact/listAnalyses/analysisSummary/readAnalysis/readAnalysisText);analysisSummary 映回 snake-case 保 tab 零改动;读同一份磁盘文件=与 Python 写一致。typecheck+181 vitest+build green。**⚠️ glue 无法单测,读路径对等需真机验。**
  - [x] **B3.2b mutation/job/ai_fill 接线**(commits `2431caa`/`c204618`/`89081a5`;**真机验 gated**)。**变更通知机制**:client.ts `emitLocal` 本地总线 + `onNotification` 合并 server+local 流(Hub 零改动收到);**单一刷新路径** = `MaterialWorkbench.onChanged` 既 bump refreshKey(工作台)又 `emitLocal("event.material.changed")`(Hub 侧栏),异步 job 也覆盖。
    - writes:writeContext/writeBasicInfo→`model.write*Dict`。sync QC:checkSubtitle/quickFixSubtitle/saveChapters→`capability.*`(check 的 reference=源语言 SRT 从 project.current 取)。
    - jobs:startSetSource→`capability.acquire_source`、RunAsr→`asr`、RunTranslate→`translate`、RunAnalysis→`analyze`(薄转发,返 job_id,runJob 不变)。**capability 不 stamp meta** → tab 在 job 成功后经 **project meta 写 RPC**(`commit_source`/`set_source_language`/`add_translated_language`,已加+pytest)持久化:SourceTab.commitSource、SubtitlesTab setSourceLanguage/addTranslatedLanguage。
    - **ai_fill 重组**:startAiFillContext→插件 `buildContextPrompt`(basic_info+platform)→通用 `capability.llm_extract`(返 raw 15 字段 dict,不写 context.json)→ContextTab 经 writeContext 持久化(替换语义)。全部 TS 分支 `type==="news_video"` 守卫,其余类型留 Python job。
  - [x] **B3.2c 只读尾巴 + import**(commit `9980d91` + B4 `cc15d95`):source_meta/listAnalysisArtifacts/importSubtitle/slotReadinessStructured 全 TS;slotReadiness/readBasicInfo 在 B4 翻 TS dispatch(`cc15d95`)。`material.*` 读/写/job/import 全在 TS。
- [x] **B4 — 创作改走 TS 素材路径**(2026-06-03,commit `cc15d95`,收口 C7):clip preview(`clip/preview.ts` + `hotclipsRepo.ts` 喂真实 `model.subtitlesDir`)、news_desk preview(`news_desk/preview.ts`)、news_desk imports(`news_desk/imports.ts`)全读 TS `materials/news_video/{model,resolve}.ts`;`materials/news_video/resolve.ts` = 共享 `loadNewsVideoModel`。`creation.preview_data`/`list_imports`/`import_resource` + `material.slot_readiness`/`read_basic_info` 桥 RPC 退役(已无调用方)。真机验过。
- [x] **B5 — 退役素材 Python**(2026-06-03,commit `ea08bd4`):删 `materials/news_video/{model,schema,paths,ai_fill}.py`、去 `instance_factory` + `MaterialType.instance_factory` 字段、删 `core_rpc/methods/material.py` + `Session.material_model`、删 `subtitle_pipeline` 的 `(project)` shim(core/ 零 material import)、删 `test_material.py`+`test_{model,paths,schema}.py`、裁 `test_registration`/`test_arch_materials`/`test_dispatch`。
  - **pre-step(分析 context 解耦)**:`subtitle_analysis_runners` + `capability.analyze` 改收注入式 `context_block`;新闻 block 插件侧 `aiFill.ts buildContextBlock`(port `context_prompt_block`)构建,经 `startRunAnalysis` 注入;news_desk publish 读 context 改走 TS model。
  - news_desk publish context bridge(`material.read_context`)= B5 抓出的最后一个活跨调用,已 port 到 TS model。真机验过(分析含 context + publish.md + 素材侧)。

---

## 收尾

> **🎉 ADR-0008 终态达成(2026-06-03,commit `cc15d95`→`57e102b`→`ea08bd4`):clip + news_desk + news_video 三插件零插件专属 Python。** Python 现仅剩:plugin-agnostic 能力网关(`capability.*`)+ 框架目录生命周期(`project.*`)+ AI/models/env/gpu 框架服务。

- [x] 全套回归:`pytest tests/`(全绿,无 pre-existing 失败)+ desktop typecheck + 212 vitest + build。
- [ ] **client.ts 死 fallback 清理(延后)**:`material.*`/`creation.*` 的 rpcCall fallback arm 已无对应 Python,但永不命中(三类型穷尽且全走 TS)。干净移除受 `noUnusedParameters` 限制(material 侧删 fallback 留 unused `type` → 需改方法签名 + 全部 renderer caller)。低价值、需独立小重构,单独做。
- [ ] 文档:`electron-migration-design.md` ★实现进度删掉已退役的「Python 业务面」节(从考古转为删除);更新 `vc.fs.*`/`capability.*` 为已实现。
- [ ] ADR-0008 状态确认 Active 落地;ADR-0004 provider 部分确认 Superseded(正文已标 superseded,确认 ADR 文件状态字段)。
