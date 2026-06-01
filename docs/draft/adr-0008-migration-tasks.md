# ADR-0008 迁移任务追踪（插件全 TS / Python = 能力网关）

> **持久任务清单**（跨会话防遗忘）。权威设计 = [`electron-migration-design.md`](electron-migration-design.md) 顶部「🚩 架构转向」节 + [`docs/adr/0008-...md`](../adr/0008-plugins-ts-python-capability-gateway.md)。本文件只追踪**进度 + 勾选状态**，不重复设计正文。
>
> 状态记号:`[x]` 完成 · `[~]` 进行中 · `[ ]` 未开始 · `⚠️GATE` 需先过人工真机验(headless 验不了,删 Tk/Python 前必过)。每步收口标准 = **build-green**(typecheck + vitest + pnpm build;改 Python 则 pytest)+ commit。
>
> **工作纪律**:per-port 取注入式 `Fs` 接口(`renderer/ipc/fs.ts`)供 vitest fake;`writeJson` 字节级复刻 Python `*.save()`;每步 build-green;**TS 替代测好前绝不删对应 Python**;忠实还原既存语义([[feedback_faithful_port_not_invent]])。

---

## ⚡ 导出速度（高优 deferred，迁移收尾后做）

**现象**(2026-06-01 用户报告):news_desk 全源导出慢——3 分钟视频 ~2 分钟导出,**用户判定无法接受**(按此 1 小时视频 ≈ 40 分钟,无 NLE 这么慢)。用户称「之前没这么慢」(疑回归)。

**分析**:逐帧 encode 循环 [`engine/export/encode.ts:214-243`](../../desktop/src/renderer/engine/export/encode.ts) **A4/A5 未碰**(纯 GPU/WebCodecs);clip 短窗口快=帧少,news_desk 全源把逐帧成本暴露。每帧三个重活:① `prepareFrame(slice, deps, exact=true)` 逐帧精确解码源帧;② `backend.renderOffscreenToBytes(...)` = GPU 画 + `copyTextureToBuffer` **GPU→CPU 读回**(每帧一次同步阻塞);③ `new VideoFrame(px.data)` 从 CPU 字节建帧 → encode。

**待办**(优先级高):
1. **先证伪/坐实回归**:`git stash` A4/A5 改动,同一视频对比导出时长(我判断 encode 路径未变、应无差,但尊重用户观察,先验)。
2. **真优化(最大那刀)**:**砍掉每帧 CPU 读回** —— `Backend.canvasElement` getter 注释已写 *"captured as a VideoFrame source during export"*,但 encode.ts 没用它、走的是 readback。改成 **`new VideoFrame(backend.canvasElement, {timestamp})`** 直接从 GPU canvas 抓帧(浏览器内部优化拷贝,免 copyTextureToBuffer+mapAsync 阻塞)= 半成品优化没接上。
3. **decode 顺序化**:`exact=true` 逐帧 seek 解码慢;导出是顺序前进,应顺序 demux/decode 而非逐帧 seek(task.md P4「导出域:逐帧精确 decode」)。
4. 可选:encoder 背压窗口调大、并行 readback 多 staging buffer(若不走方案 2)。

---

## 前提依赖

- [ ] **P2 — Tk 退役**(独立阶段;gate 住 A6/B5 —— clip Tk 仍 import `creations/clip/config.py` 等,删 Python 前必须先退 Tk)。详见设计文档「剩余工作计划」P2。
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

- [ ] **A6 — ⚠️GATE 退役创作 Python**(前提:P2 Tk clip 退役 + A4/A5 真机验过)
  - [ ] 删 `creations/{clip,news_desk}/{config,presets,component_defs,preview,export,publish,...}.py`
  - [ ] 清各 `__init__.py` provider 注册(留 `type_name/single_instance/description_*`)
  - [ ] 删 `core_rpc/methods/creation.py` 的 14 个 provider-delegating 方法 + `CreationType` provider 字段 + `Session.creation_owner/invalidate_creation`
  - [ ] 删 `tests/core_rpc/test_creation*.py`;清 `client.ts` 死 `creation.*` stub+类型

---

## Phase B — news_video 素材全 TS + 能力网关

- [~] **B1 — TS 素材模型** `materials/news_video/{schema,paths,model}.ts`(对 `Fs`)+ vitest
  - [x] `schema.ts`(port `schema.py`:5 字段 SourceBasicInfo + 15 字段 SourceContext + from/to dict + isEmpty + Fs-backed read/write context/basic_info/meta)+ `schema.test.ts`(3 测)。**deferred**:`context_prompt_block`(AI-prompt 注入)归 B2 能力网关,不在数据层;`paths.ts` 需 `material_instance_dir` 通用 RPC(对称 `creation_instance_dir`)——下次先加那个 RPC。typecheck + 168 vitest + build 全绿。
  - [ ] `paths.ts`(port `paths.py`,需新增 `project.material_instance_dir` RPC)+ `model.ts`(read/write context+basic_info、completion、list/read analyses、slotReadiness、getArtifact)
- [ ] **B2 — 能力网关**
  - [ ] `core_rpc/methods/capability.py`:路径式 job `acquire_source/asr/translate/analyze/ai_fill/probe/subtitle_check/subtitle_quick_fix/save_chapters`(复用 `_jobs_util.py`)
  - [ ] `core/subtitle_pipeline.py` 加 `run_asr_paths/run_translate_paths`(注入 path,消除 line 29-35 `TODO(ADR-0005)` 越界;留 `(project)` shim 至 Tk 退役)
  - [ ] `materials/news_video/ai_fill.extract` 移进 `core/`(dict-in/dict-out,不引 plugin schema)
  - [ ] `tests/core_rpc/test_capability.py`(AI/网络 monkeypatch)
- [ ] **B3 — 接线素材工作台** `workbenches/material/*` → TS model + 经 `runJob.ts` 调 `capability.*`;`client.ts` 换 `material.*`→`capability.*`
- [ ] **B4 — 创作改走 TS 素材路径**(收口 C7):`clip/hotclipsRepo.ts`、`news_desk/{imports,render}.ts` 读 `materials/news_video/{paths,model}.ts`,桥 RPC 退役
- [ ] **B5 — ⚠️GATE 退役素材 Python**:删 `materials/news_video/{model,schema,paths,ai_fill}.py`、去 `instance_factory`、删 `core_rpc/methods/material.py` + `Session.material_model`;删 `test_material.py`、vitest 补齐

---

## 收尾

- [ ] 文档:`electron-migration-design.md` ★实现进度删掉已退役的「Python 业务面」节(转向落地后,从考古转为删除);更新 `vc.fs.*`/`capability.*` 为已实现
- [ ] ADR-0008 状态确认 Active 落地;ADR-0004 provider 部分确认 Superseded
- [ ] 全套回归:`pytest tests/`(只剩 capability + 框架)+ desktop typecheck/vitest/build
