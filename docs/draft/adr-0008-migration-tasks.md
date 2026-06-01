# ADR-0008 迁移任务追踪（插件全 TS / Python = 能力网关）

> **持久任务清单**（跨会话防遗忘）。权威设计 = [`electron-migration-design.md`](electron-migration-design.md) 顶部「🚩 架构转向」节 + [`docs/adr/0008-...md`](../adr/0008-plugins-ts-python-capability-gateway.md)。本文件只追踪**进度 + 勾选状态**，不重复设计正文。
>
> 状态记号:`[x]` 完成 · `[~]` 进行中 · `[ ]` 未开始 · `⚠️GATE` 需先过人工真机验(headless 验不了,删 Tk/Python 前必过)。每步收口标准 = **build-green**(typecheck + vitest + pnpm build;改 Python 则 pytest)+ commit。
>
> **工作纪律**:per-port 取注入式 `Fs` 接口(`renderer/ipc/fs.ts`)供 vitest fake;`writeJson` 字节级复刻 Python `*.save()`;每步 build-green;**TS 替代测好前绝不删对应 Python**;忠实还原既存语义([[feedback_faithful_port_not_invent]])。

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

- [ ] **A3 — clip preview/render/publish**
  - [ ] `creations/clip/hotclipsRepo.ts`:镜像 `candidates.py`(copy-once 快照 via `fs.copy`+`fs.stat`)
  - [ ] `creations/clip/render.ts`:镜像 `export.py`(`clip_NNN[_hook]` 命名 + `_sanitizeFilenamePart` + `_eff_*` override-wins + stale 清理 + rendered[])
  - [ ] `creations/clip/publish.ts`:镜像 `publish.py`(render_clip_publish/index + collect_sidecars,用 `shared/markdownFmt`)
  - [ ] vitest(含"上游变更不影响已快照实例")

- [ ] **A4 — ⚠️GATE 接线 clip 工作台**(前提:P0/P1 真机验)
  - [ ] `workbenches/clip/*` 把所有 `rpc.{loadConfig,updateConfig,update/add/remove/moveComponent,*Preset,bindMaterial,previewData,*Render,*import}` 换成本地 TS owner
  - [ ] 真机:clip 端到端导出一次(mp4 + sidecar + publish.md + index.md,override-wins 命名 + 源语言本地化)

- [ ] **A5 — news_desk 同 A2–A4**(+ `imports.ts` 镜像 `news_desk/imports.py`;⚠️GATE 接线同 A4)

- [ ] **A6 — ⚠️GATE 退役创作 Python**(前提:P2 Tk clip 退役 + A4/A5 真机验过)
  - [ ] 删 `creations/{clip,news_desk}/{config,presets,component_defs,preview,export,publish,...}.py`
  - [ ] 清各 `__init__.py` provider 注册(留 `type_name/single_instance/description_*`)
  - [ ] 删 `core_rpc/methods/creation.py` 的 14 个 provider-delegating 方法 + `CreationType` provider 字段 + `Session.creation_owner/invalidate_creation`
  - [ ] 删 `tests/core_rpc/test_creation*.py`;清 `client.ts` 死 `creation.*` stub+类型

---

## Phase B — news_video 素材全 TS + 能力网关

- [ ] **B1 — TS 素材模型** `materials/news_video/{schema,paths,model}.ts`(对 `Fs`;read/write context+basic_info、completion、list/read analyses、slotReadiness、getArtifact)+ vitest
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
