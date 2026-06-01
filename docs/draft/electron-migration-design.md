# Electron 迁移正式方案

> **状态**:草案 / 2026-05-29 · 承接 [`electron-migration-plan.md`](electron-migration-plan.md)(启动稿)
> **性质**:正式迁移方案。成熟后升级为 ADR(预定 **ADR-0008**;0007 已用于组件编辑 UI 元数据),并正式 supersede [`docs/design/01-architecture.md`](../design/01-architecture.md) 的"单进程 + Tab 嵌入 / 无需 IPC"决策。
> **读者**:接手迁移实施的后续会话 / 作者本人。
> **前置**:已读 ADR-0003/0005/0006、design 01/02/04/06、architecture-vision.md、project-restructure.md(对齐结论见 §0)。

---

## ★ 实现进度 / Implementation Status(2026-05-31,新会话从这读起)

> **🚩 2026-06-01 架构转向(权威,先读下方「架构转向」节):三个本体(clip / news_desk 创作 + news_video 素材)收敛为纯 TS 插件;Python 退成 plugin-agnostic 能力网关。** 这 supersede 本文档里"Python 留 per-plugin 业务面 + provider dispatch"的旧口径(ADR-0004 的 provider 部分退役)。下面凡标 ~~删除线/⛔已废口径~~ 的段落即被它取代。**实施前提 = 先完成 P2 Tk 退役**(clip Tk 仍依赖 `clip/config.py` 等)。
>
> **clip + news_desk 两个创作工作台均已在新架构(Electron renderer + 自建 GPU 合成器 + Python sidecar)端到端实现并真机验过**(均含导出渲染;news_desk 含 preset + 素材绑定 + 详情列表 + 章节属性编辑;Tk news_desk 已退役)。本节是后续工作的**接力入口**;实现细节集中在此(task.md 只保留接力指针 + 逐次进展「续 N」,不堆架构细节)。下面"实际实现"凡与本文档正文不同的,以本节为准(正文写于迁移启动期,部分已被实现推翻——另见 §0.5)。
>
> **✅ 素材(material)侧已迁新架构(2026-05-31,M0~M6 完整,见本节末「素材侧」)。** 新架构里现在能从零造出可用 news_video 素材(建实例 → 导源视频本地/yt-dlp → ASR/翻译/章节分析 job → 编辑 15 字段新闻背景 + AI 填充)。clip + news_desk + 素材三大本体均已迁 + renderer i18n(双语热切换)已实装;Tk 仍 ship clip 工作台 + 素材 sidebar(待退役)。**剩余工作有序计划见本节末「剩余工作计划」**(P0 真机验 → P1 框架服务/AI console → P2 Tk 退役 → P3 打包 → P4+ 打磨)。
>
> **✅ 统一组件编辑器(引擎独占 FieldSpec 元数据)已实装(2026-06-01,见下「统一组件编辑器」节 + ADR-0007)。** 落地 §4.5 的编辑 UI ①:clip+news_desk 共用一个元数据驱动 `<ComponentEditor>`,全组件(水印/字幕/卡片/chapter 嵌套)迁完,news_desk wire 单位归一,颜色控件升级 Sketch+吸管。`PropertyPanel`/`ImageWatermarkProperties`/`ChapterProperties` 已删。**当前唯一阻塞收口 = 真机肉眼验**(编辑控件 + 各工作台预览 + i18n 热切换 + AI console/模型/环境 P1 的 headless 盲区),验完即可进 P2 Tk 退役。
>
> 已提交基线:见 `git log`(clip 工作台系列 commit,最新含导出/预设/双语)。

### 🚩 架构转向(2026-06-01):插件全 TS,Python = 能力网关 —— 权威,预定 ADR-0008

> **问题**:迁移把三个本体(clip / news_desk 创作 + news_video 素材)做成了**双语插件**——每个横跨 Electron renderer(TS,≈1900 行/插件) 和 Python sidecar(per-plugin 业务面 ≈1200 行/插件),读懂一个插件要翻两种语言。**长期跨 Python+TS 的功能模块不可维护**(用户结论 2026-06-01)。这一节取代下面各「Python 业务面」节、§2-3 的 provider 口径、§0.5 的"Python 留 project/material/analysis/AI"口径。

**目标**:三个插件变成**纯 Electron/TS、零插件专属 Python**。Python 退成 **plugin-agnostic 能力网关**(按文件路径+参数调用的通用 job)+ 保留 *框架目录生命周期* + *管理 Python 自身运行时* 的服务(AI console / models / env / gpu,不动)。**Python 不再认识 clip/news_desk/news_video 是什么。**

**为什么能做**:探查证实 per-plugin 的 Python 几乎全是纯 JSON/dict/markdown 逻辑、**零重依赖**(config 所有者 / presets / component_defs / preview / export / import / publish);TS 侧**已有 ~85% 目标**(mapping / assemble / 组件库含默认值 / fieldSpec / 工作台 UI)。插件里唯一真正绑 Python 的是**能力**:ASR(faster-whisper)、翻译·分析·AI填充(LLM)、源获取(yt-dlp)、ffmpeg —— 这些无 JS 等价物,保留为能力网关。

**三项确认决策**:
1. **能力底线**:ASR/翻译/分析/AI填充/源获取/ffmpeg/字幕质检 留 Python,但改成**按路径**的通用 job。
2. **文件 I/O → Electron 主进程 Node fs**:所有项目/实例/数据文件读写(config.json / presets / context.json / SRT 快照 / analysis.json / 渲染 mp4)走 Electron main 的 Node fs(扩展现有 `vc:writeFile` / `vc-media://`)。Python 只在能力 job 内部碰文件。
3. **分阶段**:Phase A = 创作(clip+news_desk)先(~90% 已在 TS、无重能力);Phase B = news_video 素材后(含真正 Python 能力 + 最大工作量)。**实施前提 = P2 Tk 退役已完成**(clip Tk 仍依赖 `clip/config.py`)。

**跨阶段地基(C1–C7)**:
- **C1 通用路径受限 fs IPC**:`vc:writeFile` 泛化成 `window.vc.fs.{readJson,writeJson,readText,writeText,list,copy,remove,stat}`(handlers `electron/main.ts`、stubs `preload.ts`、类型化 `renderer/ipc/fs.ts`)。`writeJson` 原子(`.tmp`+`rename`、`mkdir -p`、`newline:"\n"`、indent 2)精确复刻 Python `*.save()`。**`assertInProject(absPath)`** 只放行 项目根 + `<userData>/presets`(拒 `..`/盘符逃逸,Windows 大小写不敏感);项目根从 `main.ts` 的 `vc:rpc` handler 嗅探代理过的 `project.open/close` 回复(单一真相源)。
- **C2 TS 内存 config 所有者** `creations/{clip,news_desk}/configOwner.ts`(共享 `creations/shared/configOwner.ts`):逐字段镜像 Python dataclass(`apply_patch` 字段白名单 + `clips_overrides_merge` None-删 deep-merge、组件 add/remove/move + id 唯一/repair、bindMaterial、addableKinds、rendered[]、preset_name)。住 renderer,工作台按实例生命周期持有,经 `vc.fs.writeJson` 持久化,写串行化。跨进程 `event.creation.changed` 不再需要(TS 独写)。
- **C3 组件默认值/FieldSpec 已在 TS**(`composition/components/*` + `fieldSpec.ts`)→ 删 `component_defs.py`。
- **C4 Presets 在 TS**(`{clip,news_desk}/presets.ts`):builtin 懒构造、list/get/upsert/delete、last_used、builtin 保护;store 仍 `<userData>/presets/*.json`。
- **C5 preview/render/publish/imports 在 TS**:`candidates.py`→`hotclipsRepo.ts`(copy-once 快照)、`export.py`→`render.ts`(`clip_NNN[_hook]` 命名 + override-wins + stale 清理 + rendered[])、`publish.py`+`core/markdown_fmt.py`→`publish.ts`+`shared/markdownFmt.ts`、`news_desk/imports.py`→`imports.ts`。每个 port 取注入式 `fs` 接口供 vitest 用内存 fake。
- **C6** publish 源语言取自 `project.current().meta`(renderer 已有)。
- **C7 创作访问素材**:Phase A 期间保留通用 `material.get_artifact/list_subtitle_languages/list_analyses/read_analysis` 作桥;Phase B 后改走 TS `materials/news_video/{paths,model}.ts`,桥 RPC 退役。

**Phase A(clip+news_desk 纯 TS,素材仍 Python,每步 build-green)**:A1 fs 地基 → A2 clip 所有者+presets+组件 → A3 clip preview/render/publish → A4 接线 clip 工作台(换掉所有 `rpc.{loadConfig,updateConfig,update/add/remove/moveComponent,*Preset,bindMaterial,previewData,*Render,*import}`)→ A5 news_desk 同上 → **A6 退役创作 Python**(删 `creations/{clip,news_desk}/{config,presets,component_defs,preview,export,publish,...}.py`、清 `__init__.py` provider 注册、删 `core_rpc/methods/creation.py` 的 14 个 provider-delegating 方法 + `CreationType` provider 字段 + `Session.creation_owner/invalidate_creation`、删 `test_creation*.py`)。创作侧 core_rpc 只剩 `project.{list_creations,list_creation_types,create_creation_instance,rename,delete}_instance`(框架目录操作)。

**Phase B(news_video 纯 TS + 能力网关)**:B1 TS 素材模型(`materials/news_video/{schema,paths,model}.ts` 对 `vc.fs.*`)→ **B2 能力网关** 新建 `core_rpc/methods/capability.py`(路径式 job:`acquire_source/asr/translate/analyze/ai_fill/probe/subtitle_check/subtitle_quick_fix/save_chapters`,复用 `_jobs_util.py` 桥;配套给 `core/subtitle_pipeline.py` 加 `run_asr_paths/run_translate_paths` 消除 line 29-35 `TODO(ADR-0005)` 的 `core/`→`materials.news_video` 越界,`ai_fill.extract` 移进 `core/` 成 dict-in/dict-out)→ B3 接线素材工作台经 `runJob.ts` 调 `capability.*` → B4 创作改走 TS 素材路径(收口 C7)→ **B5 退役素材 Python**(删 `materials/news_video/{model,schema,paths,ai_fill}.py`、去 `instance_factory`、删 `core_rpc/methods/material.py` + `Session.material_model`、删 `test_material.py` 加 `test_capability.py`)。

**Cutover**:Phase A 可独立 ship(素材仍 Python 经桥)。**TS 替代 wire+测好前,绝不删对应 Python 方法**;`vc-media://` 全程不动,`vc.fs.*` 是增量。

**ADR / 文档影响**:本节 = **预定 ADR-0008「插件逻辑入 TS;Python = 能力网关」** 的正文来源(数据模型已在 ADR-0006;0008 固化 渲染引擎 + IPC 拓扑 + 插件语言边界)。0008 **supersede** ADR-0004 的 provider-dispatch 部分 + `design/01-architecture.md`;ADR-0003/0005 保持 Active(快照"拷贝"移 TS,原则不变)。

**验证**:删 `test_creation*.py`/`test_material.py`,新 `test_capability.py` + 新 vitest(configOwner/presets/render/publish/hotclipsRepo/imports + 素材 schema/model/paths,对注入 fs fake,1:1 行为替换);手动 e2e(Phase A 真导出 clip+news_desk → mp4+sidecar+publish.md+index.md;Phase B `capability.asr/ai_fill/acquire_source`)。

> **下面「已实现(代码位置)」起的各节是转向前的现状记录**;凡涉及 per-plugin「Python 业务面」的描述均被本节取代(Phase A/B 落地后删),保留作迁移考古。

### 已实现(代码位置)

**进程/IPC**(对齐正文 §1-3,基本如设计):
- Python sidecar `core_rpc/`(JSON-RPC 2.0 over stdio,单一状态所有者,二进制帧 Windows 坑已处理);Electron `desktop/electron/{sidecar,main,preload}.ts` 转发 + 事件广播;renderer `desktop/src/renderer/ipc/client.ts` 类型化客户端。
- Electron IPC:`vc:rpc`(+notification)/`vc:pickVideo`/`vc:pickFolder`/`vc:writeFile`(写实例目录)/`vc:showInFolder`/`vc:openPath`/`vc-media://`(privileged + corsEnabled,Electron 42)。

**composition / 渲染**(整块在 TS renderer):
- OTIO IR + 公共组件库 + clip/news_desk 映射:`desktop/src/composition/`、`desktop/src/creations/{clip,news_desk}/`。`buildClipTimeline`(`creations/clip/assemble.ts`)= 候选+config→全多轨 OTIO。
- 自建 GPU 合成器:`desktop/src/renderer/engine/`(gpu/source/compositor/overlay/export)。`resolveFrameAt` 单解析器喂预览+导出(preview≡render)。
- **字幕单行适配**(移植缺口已补):`composition/subtitleWrap.ts` = `compute_subtitle_max_chars`+`split_subtitle` 的 TS 移植(长 cue 按时间轴切多条、每条 1 行、按内容自动判中英、maxChars=aspect·0.92/(fontsizePct·ratio) 分辨率无关);经 `CompileContext.frameAspect` 驱动 `subtitle.compile`。

**clip 工作台 UI**(per-plugin,`desktop/src/renderer/workbenches/clip/`):
- 三 tab 壳 `ClipWorkbench`(tab 首访挂载、之后只切 display 不卸载 → 不重开引擎);Hub 通用派发 `workbenches/index.tsx`。
- 样式 tab `StyleTab`:`CropPreview`(受控可拖裁剪框,引擎按 srcPath 开一次)+ 组件**增删排序**管理器(`+添加`/删除/↑↓,spec 由 `component_defs` 驱动)+ 属性面板 `propertyEditor`(类型驱动 + enum 下拉)+ 工具栏(比例/短边/模式/编码/预设)。
- 候选 tab `ClipsTab` + `ClipDetailPanel`:列表(行格式/score 着色/☑多选→selected_clip_indices/全选-全不选/计数/点行开详情)+ 详情(per-candidate 裁剪框、start/end ±0.5 微调+clamp、hook/outro/title/tags 覆盖、SRT cue 列表、恢复 AI 文本)。
- 导出 tab `ExportTab`:状态表 + 批量渲染(plan→encode→writeFile→commit)+ 进度/取消 + 行操作(播放/打开文件夹/重渲/删除/错误详情)。

**Python 业务面**(`src/creations/clip/`,均 headless 无 tkinter)— ⛔ **被「架构转向」节取代**(Phase A6 删,移成 TS configOwner/render/publish):
- `config.py ClipInstanceConfig` 单一所有者:`apply_patch`/组件 `add/remove/move_component`(+ load 去重历史冲突 id)/预设 `list/apply/save/delete_preset`/`addable_kinds`。
- `component_defs.py`(纯,新):addable kinds + default instances —— Tk specs(`components/*`,tkinter 耦合)的 new-arch 双胞胎,Tk 退役时合并。
- `export.py`(render_provider):`plan_render`(命名 `clip_NNN[_hook]`/out_idx/crop 默认/路径)/`commit_render`(sidecar JSON + stale 清理 + rendered[])/`delete_render`。
- `preview.py`(preview_provider):候选 + 快照 SRT(**全部字幕语言**,双语用)+ override。
- `presets.py` 改用 `component_defs`(去 tkinter)。

**RPC 面**(`core_rpc/methods/{creation,project,material,system}.py`,base 层经注册表/getattr,**零硬编码 plugin 名** ADR-0004):
`creation.`{load_config / list_components / update_component / update_config / list_addable_components / add_component / remove_component / move_component / preview_data / plan_render / commit_render / delete_render / list_presets / apply_preset / save_preset / delete_preset / **list_imports / import_resource**}；`project.`{recent_list / open / close / current / list_material* / list_materials / list_creations / **list_creation_types / create_creation_instance**}。后两组(import_provider + create-creation)随 news_desk 迁移补齐(见下)。

### news_desk 创作工作台(2026-05-31,第二个迁入新架构的创作)

news_desk 与 clip 走同一套契约,正面验证「公共组件库 + provider 模式覆盖多插件」。**关键差异:全源模型**——无候选切片、无 reframe 裁剪、单全源输出。真机逐项验过(画面 + 双语字幕 + 自适应宽度 + 文字/图片水印 + 章节条 + 章节卡 + 音画同步)。

**Python 业务面**(`src/creations/news_desk/`,headless)— ⛔ **被「架构转向」节取代**(Phase A6 删,移成 TS):
- `config.py NewsDeskInstanceConfig` 单一所有者:`apply_patch`(只 `preset_name`,全源无 reframe 几何)+ `add/remove/move_component`(+ load `_ensure_unique_ids` 修 Tk 时代无/重 id)+ `addable_kinds` + `rendered[]` 字段。
- `component_defs.py`(纯,新):addable kinds(chapter 单例 + subtitle/text_wm/image_wm 多例)+ default instances。**一处刻意偏离 Tk specs**:subtitle/text_wm 字号/描边发 canonical 分数形(`fontsize_pct`/`stroke_pct`),非 Tk 绝对 px,与已合并的 TS 层对齐;默认值=1080 基线换算。
- `preview.py`(preview_provider):全源 `mediaRef` + `durationSec`(读 source meta,**不跑 ffprobe**)+ 各 subtitle 组件 srt_path 的快照 SRT 绝对路径(`subtitlePaths`)。**章节不返回**——schedule 已快照进 config。
- `export.py`(render_provider):`plan_render`(单 `output.mp4`,out_idx 恒 1,src_idx 不用)/`commit_render`(写 `output.json` sidecar + `rendered[]` + **publish.md**)/`delete_render`(连 publish.md 一并清)。**publish.md 已恢复**(续 36):纯模板 `creations/news_desk/publish.py`(从 Tk 退役时删掉的版本捞回,与 clip 的 publish.py 同位)+ `commit_render` best-effort 调用(数据全从实例状态 + 绑定素材 context.json 取,ADR-0003;语言跟源不跟 UI)。**仍 deferred**(Tk 时代两个 opt-in 交付物):transcript.md + 按章节切 mp4(后者是 publish 侧 ffmpeg stream-copy,非 GPU 渲染)。
- `imports.py`(import_provider,**新 provider 类型**):`list_imports → {subtitleLangs, analyses}`;`import_resource(component_id, params)` **快照进组件**——`{kind:subtitle,lang}` 把素材 `<lang>.srt` 拷进 `<instance>/subtitles/<id>.srt` 设 srt_path;`{kind:chapters,filename}` 从 analysis.json 填 chapter schedule。**核对:快照非引用,符合 ADR-0003;经 registry 取素材零硬编码名。**
- `__init__.py`:注册 `config_owner_cls` + `preview_provider` + `render_provider` + `import_provider`。**注:`load_plugins` 必须 import news_desk**(`core_rpc/methods/__init__.py`)——曾漏致 sidecar 看不到它(真 bug,已修)。

**新增框架契约**:`CreationType.import_provider`(`src/creations/__init__.py`);`creation.list_imports`/`import_resource`(core_rpc,泛型派发 params 不透明);`project.list_creation_types`/`create_creation_instance`(create-creation 流程,Hub `[+]` 菜单依赖)。

**news_desk 工作台 UI**(`desktop/src/renderer/workbenches/news_desk/`):
- 壳 `NewsDeskWorkbench`:**两 tab**(样式/导出,无候选 tab——全源)。
- 样式 tab `StyleTab`:`NewsDeskPreview`(全源 canvas 预览,**无裁剪框**,复用引擎层 + `buildNewsDeskTimeline`,preview≡render,播放/拖动/音频主时钟)+ 组件增删排序 + `ImportRow`(字幕选语言 / 章节选 analysis 导入)+ 属性面板(字幕/水印用通用 `PropertyPanel`;**章节用专用 `ChapterProperties`**——嵌套 modes/style,`chapterPatch.ts` 出 shallow-merge 安全 patch)。
- 导出 tab `ExportTab`:**真渲染已实装**——`buildNewsDeskTimeline → exportTimelineToMp4(GPU/WebCodecs + 源音频混流)→ vc:writeFile → commit_render`,全源单输出;带进度%/取消/播放·打开·删除。
- `useNewsDeskPreview`:加载源 + 时长 + 各 srt_path 快照 cues(`cuesBySrtPath`);`reload()` **原地刷新**(不 blank,不重挂 GPU——blank 会让预览 unmount 重建 backend 黑屏)。
- 详情列表 `ComponentDetail`(`SubtitleCueList`/`ChapterScheduleList`,只读 + 点击 seek;`NewsDeskPreview` 经 `controlRef` 暴露 `seek`)。
- preset 工具栏(预设下拉 + 应用/另存为/覆盖/删除,builtin 防护;**另存为用内联输入**,`window.prompt` 在 Electron 渲染进程不支持)。
- 素材绑定 `MaterialBindingBar`(**常驻持久设置**,非一次性闸门):显示已绑素材 + 换绑,未绑定显示选择器;`creation.bind_material` RPC 写 `bound_material`(新架构 create 流程建的是未绑定实例)。
- 图片水印 `ImageWatermarkProperties`:**专用编辑器**——常驻「图片文件」行 + 浏览…(`vc:pickImage` 原生对话框)+ 清除(通用 `PropertyPanel` 只渲染存在的字段且无文件选择器)。
- Hub `[+]` 创建创作菜单(`hub/Hub.tsx`)+ ProjectView 已渲染选中创作工作台。

**chapter 图元绘制**(`engine/overlay/canvas2d.ts`):`drawTopicStrip`(顶部条带)+ `drawHeroCard`(侧栏卡,accent + 标题 + 正文 char-wrap)。几何镜像 `core/composition/primitives/{topic_strip,chapter_hero_card}.py`;字号 1080 基线绝对 px 按 h/1080 缩放。**坑:data-key 必须用组件真发的**(`topic_text`/`title`/`body`,非 `text`)。

**news_desk 已全部完成(2026-05-31,续29~续31 真机验过)**:① 详情列表 ✅ ② 快照约定核查 ✅(全链路只读实例快照,唯一 material 引用=源视频路径+时长 meta=输入媒介,正确)③ 导出真渲染 ✅ ④ preset RPC + 规范化 builtins(`component_defs` 成组件形单一源)✅ ⑤ Tk news_desk 退役 ✅(删 `news_desk_tool.py`+`components/*`+`publish.py`,VideoCraftHub 注销;clip 拿走共享组件框架 dataclass=clip-local,杀跨插件 import)⑥ 素材绑定 UI + bind RPC ✅。

**真机踩过并修的 bug(均已 land)**:`window.prompt` 崩(→内联输入)/ 应用预设黑屏两因(reload 重挂 GPU→原地刷新;mapping 对缺 schedule/image_path 抛错→`?? []`/`?? ""` + 装配器 per-component try/catch)/ 导入后字幕不显示(import 没刷 cues→`preview.reload()`)/ **导入切实例丢数据**(import provider 越过 session 缓存 owner 直写 config→缓存陈旧;修=`Session.invalidate_creation` 在 import/commit/delete_render 后调,re-sync 单一所有者)/ 导入下拉跨组件联动(`ImportRow` key by id)/ 图片水印无文件选择器(`vc:pickImage` + `ImageWatermarkProperties`)。

剩余非阻塞欠债:逐章 schedule 编辑(现只读+seek)、字幕双语并排 UI、外部文件导入(磁盘选 SRT)、transcript.md + per-chapter mp4 切分(publish 侧 ffmpeg,defer;**publish.md 已恢复=续 36**)。

### 素材(material)侧 —— 已迁新架构(2026-05-31,M0~M6 实现完整)

**第三个迁入新架构的产品本体**(继 clip + news_desk)。新架构里现在能**从零造出可用的 news_video 素材**:建实例 → 导源视频(本地/yt-dlp)→ ASR/翻译/章节分析(sidecar job)→ 编辑 15 字段新闻背景(+ AI 填充)。**用户决策:忠实照搬 project-level 单源行为**(不修 per-instance 地基;`subtitle_pipeline.run_asr/translate(project)` 仍走 `default_instance`;RPC 带 `instance` 参数前向兼容;`single_instance=True` 让 [+] 菜单「打开已有」不静默建坏 2nd 实例)。**Python 业务一行未重写**——薄 RPC + job 包既有 `NewsVideoModel`/`core.source_acquire`/`subtitle_pipeline`/`chapters_io`。

**Python 业务面/注册表** — ⛔ **被「架构转向」节取代**(Phase B5 删,移成 TS `materials/news_video/{schema,paths,model}.ts` + 路径式能力网关):
- `src/materials/__init__.py` `MaterialType` 扩 `single_instance`/`suggest_name`/`description_*` + 模块 `suggest_instance_name`(镜像 creations);`news_video/__init__.py` `single_instance=True` + `suggest_name`。
- `src/materials/news_video/model.py` 加 `write_context_dict`/`write_basic_info_dict`(sidecar 传 dict,base 层零插件名 ADR-0004)。**修了一处 dead-but-broken bug**:`ai_fill_context` 旧代码 `extract(..., progress_cb=...)` 但 `extract` 无该参数 → 必 TypeError;无 Tk 调用方(Tk 直接调 `extract`),改为不转发 progress_cb。

**RPC 面**(`core_rpc/methods/`):
- `project.py`:`list_material_types_info` + `create_material_instance`(镜像 `create_creation_instance`;建 instance.json + `source/`+`subtitles/` 骨架 + `event.materials.changed`)。
- `material.py`(扩既有 2 个只读):同步读写 `read/write_context`、`read/write_basic_info`、`context_completion`、`source_meta`、`list_subtitle_languages`、`list_analyses`、`analysis_summary`、`read_analysis`、`save_chapters`(经 `chapters_io.save_analysis_chapters_only` 归一化);长任务 job `set_source`(local+yt-dlp,AcquireError category 前缀进失败 `event.job`)、`run_asr`、`run_translate`、`run_analysis`、`ai_fill_context`(**不传 progress_cb**)。每写发 `event.material.changed`;每 job 成功末尾发 changed。
- `_jobs_util.py`(新):`AcquireCancelBridge`/`AiCancelBridge`(桥 `job.cancelled`→两种 CancelToken)+ `acquire_progress_to_job`/`pipeline_progress_to_job`(ProgressInfo→`job.progress`)。

**renderer**(`desktop/src/renderer/`):
- `ipc/runJob.ts`(新):**通用 sidecar-job 消费**(创作侧是 GPU-in-renderer,素材侧是 sidecar job)——**subscribe-first + 缓冲**防瞬时 job 抢跑;按 job_id 过滤 `progress.*`/`event.job`;配 React `useJob()`(running/progress/error + cancel)。
- `workbenches/material/`(新):`MaterialWorkbench`(三 tab 壳,slot 锁映射 source/subtitles/news_context)+ `SourceTab`(本地 pickVideo / yt-dlp URL / clip_range / category 恢复提示)+ `SubtitlesTab`(ASR/翻译/章节分析 + analysis 列表)+ `ChapterScheduleEditor`(改 start/title,refined/key_points 只读保留,服务端归一化)+ `ContextTab`(15 字段 commit-on-blur + 5 字段 basic_info seed + ✨AI 填充 job + 覆盖警告)。
- `workbenches/shared/fields.tsx`(新):`TextRow`/`TextAreaRow`/`NumRow`/`ColorRow`/`CheckRow`/`Section` 从 news_desk `ChapterProperties` 抽出共享(news_desk 改 import,去重)。
- `workbenches/index.tsx`:加 `MaterialWorkbench` dispatch(`materialWorkbenches` registry,对称 creations)。
- `hub/Hub.tsx`:素材实例行可点开工作台(`workbench` state 加 `kind:'creation'|'material'` 判别)+ 素材 `[+]` 菜单(`CreateMaterialMenu`,single_instance 已存在则「打开已有」)+ **订阅 `event.materials/material.changed` 实时刷新树**。
- `ipc/client.ts`:`MaterialTypeInfo`/`SourceContext`/`SourceBasicInfo`/`SourceMeta`/`AnalysisSummary`/`AcquireSource` 类型 + `rpc.{listMaterialTypes,createMaterialInstance,materialSourceMeta,read/writeContext,read/writeBasicInfo,listSubtitleLanguages,listAnalyses,analysisSummary,readAnalysis,saveChapters,startSetSource,startRunAsr,startRunTranslate,startRunAnalysis,startAiFillContext,cancelJob}`。

**检视/编辑增量(对照 Tk 补全的 4 个缺口,gap A~D)**:
- **A 源视频预览**:SourceTab `<video controls>` 走 `getArtifact("source")` → `vc-media://`(对齐 Tk source_preview_pane)。
- **B 字幕查看 + 质检/修复**:`SubtitleViewer`(SRT 文本 + `check_subtitle` 按 hard/fixable/advisory 分类 + `quick_fix_subtitle` 一键清残留);RPC `material.read_subtitle`/`check_subtitle`/`quick_fix_subtitle`(对齐 Tk srt_preview_pane / subtitles_dialogs)。
- **C 章节编辑器视频 seek**:`ChapterScheduleEditor` 加 `<video>` + 每行「跳转」(seek 到 start)/「取当前」(取播放秒写回 start),`getArtifact("source")` 供源(对齐 Tk chapter_editor)。
- **D 外部 SRT 导入 + 分析 kind**:`material.import_subtitle`(+ `vc:pickSubtitle` 原生 .srt 选择器)snapshot 外部 SRT;SubtitlesTab **生成菜单只 `analysis`+`hotclips`**(镜像 Tk `node_panes._show_analysis_menu` 的 `hidden={transcript,chapter_transcript}`——那俩只供 news_desk export/publish 内部用,引擎 registry 仍有但 UI 不放;续 33 修正,见 [[feedback_ui_menu_from_tk_not_engine]]);查看已有产物经 `list_analysis_artifacts`/`read_analysis_text` + `AnalysisTextViewer`(md/json 只读,analysis kind 走章节编辑器),不限 kind。

**续 33 真机复核三处修正(已落 `9aeb9bd`)**:
- **预置语言选择器**:ASR 源/翻译目标/导入语言从裸文本框换成 `LanguagePicker` 组合框 + `system.list_languages`(暴露 `core.lang_names.WHISPER_LANG_CHOICES` 99 语言;打字过滤预置、选中存 iso、ASR 带「自动检测」)——还原 Tk `ttk.Combobox` 的预置匹配。
- **ContextTab 用法澄清**:重构成显式三步(① 你的线索/AI 输入提示 → ② AI 填充 → ③ AI 生成 15 字段背景/下游唯一源/可校正)+ 各组来源标签,解决"分不清用户输入 vs AI 产出"。
- **分析 kind 精选**(见上 D)。

**测试**:`tests/core_rpc/test_material.py`(23,inline-job runner 同步跑 work 防 daemon 竞态;含 create / context round-trip / set_source local+失败category+cancel / asr / analysis / save_chapters 归一化 / ai_fill no-progress_cb 回归守 / read·check·quick_fix·import subtitle / list_analysis_artifacts+read_text / list_languages)。TS `pnpm typecheck` 干净 + `pnpm test` 130 全绿 + `pnpm build` 通过。

**⚠️ 已知限制 / 欠债**(均非阻塞):
- **单源 wart(决策性)**:2nd news_video 实例拿不到自己的源/ASR(读写实例#1);`single_instance=True` 在菜单层挡住,`subtitle_pipeline.py:29-34` 的 `TODO(ADR-0005)` 保留待后续真·per-instance 化。
- yt-dlp 需 sidecar 进程能找到 Node.js(JS 挑战);失败 category 已透传提示。AI job(ASR/translate/章节/ai_fill)经 `core.ai`,无 provider 配置则 job failed,各 tab 渲染 error 不崩。
- **真机肉眼验欠**(渲染/GUI 层 headless 覆盖不到,同 clip/news_desk):需 `env -u ELECTRON_RUN_AS_NODE pnpm dev` 跑一遍建实例→导源→ASR→质检→章节(seek)→context→AI 填充。
- ~~整个 Electron renderer 纯中文硬编码、无 i18n~~ → **已做(见下「renderer i18n」节)**。
- 字幕双语并排 UI = 后续打磨。

### renderer i18n(双语)—— 已实装(2026-06-01,§7.4 待决落地)

整个 renderer 之前纯中文硬编码、零 `tr()`(§7.4 待决问题)。本轮铺轻量自建 i18n(否决 i18next:重、renderer 字符串量中等),与 Tk `src/i18n.py` 心智一致。

- **基建**:`desktop/src/renderer/i18n/`——`tr.ts`(`tr(key, vars?)` + `getLang()`/`setLang()`,模块单例语言;fallback 链 当前→en→raw key;`{name}` 占位插值,与 Python `str.format` 对齐)+ `zh.json`/`en.json`(扁平点分 key,290 对,**zh/en 严格对称**)。两表静态 `import` 进 bundle,`tr()` 同步、任意组件可调,无需 Provider。`tsconfig` 加 `resolveJsonModule`。
- **语言来源 = 单一真相源**:新 RPC `system.get_locale` 返回 `i18n.get_current_lang()`(读同一 `user_data/settings.json`,与 Tk 锁步,默认 en)。`main.tsx` boot 时 `await rpc.getLocale()` → `setLang()` **早于首帧 render**(无闪烁、无需 context)。失败回落默认 locale 不阻塞启动。
- **热切换(区别于 Tk 重启制)**:renderer `tr()` 每帧求值,故切换是**热的**——`tr.ts` 加 reactive 层(`useSyncExternalStore`,`setLang` 通知订阅者),`Shell` 顶层 `useLang()` 订阅 → 整树重渲染(无 React.memo 边界拦截,工作台 state 不丢)。`i18n/LanguageToggle.tsx`(中/EN segmented control)放 Launcher 右上 + 项目顶栏;点击 `setLang()` 即时翻 + `rpc.setLocale()`(新 RPC `system.set_locale` → `i18n.set_current_lang()`)持久化回 settings.json,**best-effort**(UI 已先翻),下次启动 + Tk 侧跟随。
- **抽取**:Hub/workbenches(clip/news_desk/material)全部硬编码中文 → `tr("<域>.<key>")`,域前缀 `hub./clip./news_desk./material./common./workbench.`。静态数组(KIND_LABELS/TABS/GROUPS/CATEGORY_HINTS 等)改 key-map + render 时 `tr()` 求值。RPC 来的 `description_zh`/`description_en` 按 `getLang()` 选。**代码注释不动**(非用户可见;仍英文规约,与 i18n 正交)。
- **验证**:`pnpm typecheck` 干净 + 130 vitest + `pnpm build`(98 模块,JSON 入包)全过;`tests/core_rpc` 114 全绿(+`system.get_locale`/`set_locale` round-trip + reject;后者 monkeypatch `i18n.SETTINGS_FILE` 到 tmp 防污染真实配置)。脚本核对:字面 `tr()` key 全部命中 JSON;zh/en key 集合相等;残留中文仅 JSDoc 注释。
- **欠**:① 真机肉眼验热切换(点 中/EN 看整树即时翻 + 重启后保持;与渲染层同类 headless 盲区);② sidecar `RpcError.message`(Python 侧文案)双语化是单独决策,本轮只做 renderer 自有硬编码;③ Tk `src/i18n/{zh,en}.json` 806 key 与 renderer 表是两套(刻意,迁移期 renderer 自包含),将来可考虑合并/对齐。

### 统一组件编辑器(引擎独占 FieldSpec 元数据)—— 已实装(2026-06-01,落地 foundation §4.5 的 ①;权威 = ADR-0007）

迁移期一直缺奠基稿 §4.5「组件 = ① 编辑 UI + ② compile」的 ①,临时用通用 `PropertyPanel` 直接编辑各插件原始 wire dict——从值类型猜控件、从字段名 `/opacity/i` 猜步进(分数字段取到 0/1.0 就崩)、露 snake_case 内部名当标签。dogfood 连环踩雷(图片不显示真因是缺 picker;小数打不进;箭头 +1;position 是自由文本而非 anchor)后,落地 ① 并把两插件 wire 归一。

- **引擎层(纯数据,无 React)**:`composition/components/fieldSpec.ts`——`FieldSpec`(control/labelKey/step/min/max/options/optionLabelKeys/**path**(嵌套)/**section**/**visibleWhen**)+ `canonicalKind()`(去 `clip_` 前缀)+ `fieldsForKind()` 注册表。各组件导出 `*Fields`(watermark/subtitle/card/chapter)。**FieldSpec.key = 持久化 wire snake key**(编辑器编辑持久化 dict,经 `creation.update_component` 浅合并);camelCase canonical 仅供 compile,由 mapping 桥接。
- **renderer**:`workbenches/shared/ComponentEditor.tsx`(元数据驱动,clip+news_desk 共用,标签恒走 `tr()`)+ `fieldControls.tsx`(抽出的 number 步进/text/`ColorSwatchPicker`)+ `nestedPatch.ts`(嵌套 read/patch,整子对象重发抗浅合并,6 单测)。两 StyleTab 恒用 `<ComponentEditor>`。删 `PropertyPanel`/`ImageWatermarkProperties`/`ChapterProperties`/`chapterPatch`。
- **news_desk wire 归一**:`component_defs.py`/`types.ts`/`mapping.ts` 整数百分比→分数 + 规范名(`scale_pct→image_scale` 等);clamp 留 `mapping.ts`(ADR-0006 单点),FieldSpec min/max 仅 UX 提示。**顺带修潜在 bug**:news_desk 文字水印 mapping 读的是 Python 早已改名前的 stale key。
- **颜色控件**:`@uiw/react-color` Sketch(饱和度方块+色相条+HEX/RGB+预设)+ Chromium EyeDropper 屏幕吸管;关 alpha(不透明度是独立字段);关闭弹窗时提交(不每帧 RPC)。
- **显示单位 `FieldSpec.display`**(`{factor,step,decimals?,suffix?}`):存储恒规范,编辑器 UI 边界换算——字号/描边/卡片内边距显示 **px@1080**、边距/块边距/图片缩放显示 **%**、不透明度 %、时长 s。还原 Tk 直觉单位 + 统一观感(字幕分数 fontsize 与章节 px fontsize 都显示成 px)。clamp 仍只在 mapping,`display.min/max` 仅提示。
- **候选预览**:切候选/nudge 起止点时按 window-key 暂停+进度归零(防旧位置越界短 clip)。
- **文字水印 draw-key 修(潜在 bug)**:`drawOverlayClip` 原把所有非字幕文字按卡片 key 读(`color`/`size_pct`),但文字水印 emit `text_color`/`text_fontsize_pct`/`text_opacity` → 颜色/字号永远默认、透明度没生效、还误描边。改为按 kind 选 key + `text_opacity` 作 fill alpha + 不描边。
- **欠真机肉眼验**:各控件小数输入/步进/**显示单位(px/%)**/anchor 下拉/中文标签/chapter mode 门控+嵌套改值不丢兄弟/**取色器+吸管**/**文字水印颜色·字号·透明度生效**。

### 与本文档正文不同的关键实现决策

| 正文/设计 | 实际实现 | 原因 |
|---|---|---|
| §1/§2.2 Python sidecar 有 **Render 域**(render.start job) | **渲染在 renderer**(GPU/WebCodecs);Python 只 `plan/commit/delete_render`(路径/sidecar JSON/rendered[]);mp4 字节经 `vc:writeFile` 写盘**不走 RPC** | GPU 只在 renderer;大二进制不走 stdio |
| §4 渲染后端"留 ffmpeg" | 自建 GPU 合成器 + WebCodecs;ffmpeg 仅潜在 mux | 已被 foundation doc 取代(§0.5) |
| 预览"复用 .html 视觉" | TS 原生 compositor;裁剪框是编辑层(`<video>` 显整源 + 暗化+框,**不裁预览像素**),导出才按 crop_rect 偏移裁(shader UV 重映射 + mode 标志,fit 路径字节不变) | preview≡render,且裁剪是 NLE 编辑语义 |
| (未在正文)组件 spec | 新架构 spec 元数据/默认实例走 `component_defs`(headless);组件按 **id** 寻址(RPC),load() 去重 Tk 时代的固定 id | sidecar 必须 UI-free;id-based RPC |
| `CreationType` 契约 | 扩 `config_owner_cls` / `preview_provider` / `render_provider`(per-creation 提供者,base 层通用调用) | 保持 base 层 clip 无关 |
| (新增)双语 | 字幕**按组件 language** 烧;`preview_data` 返回**所有 SRT 语言**(`subtitleLangs`,区别于 hotclips 候选语言 `availableLangs`);字幕属性面板语言下拉 | 双语 = 多字幕组件,各绑一语言 |
| (删除)工具栏候选语言下拉 | **已删** | 冗余(同内容、文案可改)+ 切换会按下标错位毁勾选/覆盖(footgun);候选语言是创建期决定,`source_subtitle` 字段保留,`preview_data` 未设时自动取首个 hotclips 语言 |

### 已知坑 / 已修(避免重新踩)
- **React StrictMode dev 双挂载**毁 WebGPU canvas 单例 context → 黑屏:`CropPreview` 在 `new Backend()` 前 `if(disposed) return`,只存活挂载 configure canvas。
- **H.264 档撞分辨率上限**:`encode.ts` 用 `isConfigSupported` 从 High 5.2 往下挑(固定 L3.1 拒绝 1080×1920 → "closed codec")。
- **canvas 等比**:预览 canvas 用 `maxWidth+maxHeight+auto`(固定 height + maxWidth 会在窄容器里压扁画面+裁剪框)。
- **预览陈旧**:tab 保活下导出 tab 切到前台 `active` 时重 plan;失败行保留不被 reload 刷回。
- **环境**:agent shell 带 `ELECTRON_RUN_AS_NODE=1`,启动必 `env -u ELECTRON_RUN_AS_NODE pnpm dev`;改 Python 必整重启 sidecar(Ctrl+R 只重载 renderer);HMR 不可信,改 renderer 后清 `node_modules/.vite` 整重启;启动前 `taskkill electron.exe` + 杀 5174。

### 测试
TS:`pnpm typecheck` + `pnpm test`(132,含 ir/timemap/components/clip/news_desk/cropEditor/mapping/subtitleWrap/nestedPatch/chapterDraw)。Python:`pytest tests/core_rpc`(114,含 creation 全 RPC + render plan/commit/delete + 预设 + 双语 + import + bind + cache 失效回归 + material 全 RPC + `system.get_locale`/`set_locale`)。引擎渲染层 + i18n 热切换 headless 覆盖不到,靠真 renderer 肉眼验。全套 `pytest tests/` 仅 3 个 pre-existing failed(golden CRLF/tmp 路径 x2 + clip_config stale id),无新增。

### 剩余工作计划(2026-06-01 重排)

> 三大本体(clip / news_desk / 素材)+ renderer i18n 均已端到端实现。剩余工作按 **"先验真 → 让新壳能独立用 → 退役 Tk → 打包 → 打磨"** 排序。P0/P1 是退役 Tk 的前置;P2 之前新壳与 Tk 并存。

**P0 — 真机肉眼验收口 ✅ 已跑完(2026-06-01)**(渲染/GUI/热切换 headless 盲区,人肉过一遍):
- 素材侧 e2e(建实例 → 导源本地+yt-dlp → ASR → 质检 → 章节 seek → context → AI 填充)+ i18n 热切换(中/EN 整树即时翻 + 重启保持)均已真机跑过。
- (clip / news_desk / 音频端到端 此前已分别肉眼验过,见各节。)
- ⇒ 三大本体 + i18n 的"代码全绿但 headless 盲区"已全部人肉收口;**下一步进 P1**。

**P1 — 让新壳自给自足:框架服务(§0.5 已规划但未建)**。**当前最大功能缺口**:新壳只有 project/material/creation,**无 AI 配置入口**,sidecar 也无 `ai.*` 域 → ASR/翻译/章节分析/ai_fill 等所有 AI job 在新壳里配不了 provider/key,只能靠 Tk app 先配好。**退役 Tk 前必须补齐**:
- **AI console 迁新壳**:provider 路由(task-first)/ 内置 / 云 key / aistack / TTS / 统计(6-tab,**去 Prompts**;[[project_videocraft_ai_console]]);需新增 sidecar `ai.*` RPC 域。
  - **✅ P1-a 已落(2026-06-01,只读域)**:`core/ai/console_view.py`(UI-free 读模型——从 Tk console 提升 provider 分类 + key-status 逻辑,返回**结构化枚举**`deploy_tier`/`key_status.state` 而非 i18n 文案/颜色,渲染端本地化)+ `core_rpc/methods/ai.py`(`ai.snapshot` 全状态 / `ai.stats` 调用计数)。**未碰 Tk console**(读模型双方将来共用)。
  - **✅ P1-b 已落(2026-06-01,sync 写操作)**:`ai.set_key`(写 `keys/<file>`)/ `ai.set_provider_enabled` / `ai.set_routing`(tier radio)/ `ai.set_tier_pref`(dropdown sticky)/ `ai.set_aistack_gateway`,均经 router 持久化、返回 fresh snapshot 让 UI re-sync。`test_ai.py`(7)全绿(写测 monkeypatch `router._persist`/`keys_dir` 防污染真实 config),共 121 sidecar 测。
  - **✅ P1-b2 已落(2026-06-01,网络动作走 job)**:`ai.test_provider`(LLM 1 词探针)/ `ai.test_aistack`(/v1/models → bucket → 持久化 URL + 刷模型缓存,routing 的 aistack model 下拉随之填)/ `ai.refresh_models`(LLM 拉 API 模型列表,填进 Edit 的 models 框待保存),均 `ctx.jobs.start` 走 worker 线程,terminal `event.job` 带结果;renderer 经 `runJob` + 新 `useNetAction` hook 消费。console_view 加三网络 helper;`ai.py` 三 job 方法(非 LLM 的 test/refresh 直接 `INVALID_PARAMS` 拒)。`test_ai.py` 12 测(网络全 monkeypatch,不打实网),共 126 sidecar 测。
  - **✅ P1-c 已落(2026-06-01,renderer 6-tab 壳 + 活动栏)**:Shell 重构成 **VSCode 式左侧活动栏**(`app/ActivityBar.tsx`:项目/AI/模型/设置;Hub 常驻 display 切换保 workbench 态,框架视图按需挂载)。`aiconsole/AiConsole.tsx`——6 tab(Routing/Embedded/Cloud/aistack/TTS/Stats,**去 Prompts**),消费 `ai.snapshot`/`ai.stats` + 全部写操作(key 录入 / enable / 路由 tier radio + provider/model 下拉 / aistack url+enable);写返回 fresh snapshot re-sync。client.ts 加 `ai*` 类型 + stub;i18n 45 key zh/en 对称(335 对)。后续补:per-provider Edit 面板(key + Base URL + **模型选择器**[拉全量 API 列表→复选勾选启用 + 搜索 + 手动添加,还原 Tk picker,不是逗号文本框] + 设置,2026-06-01)+ 网络动作按钮(Test / Refresh models / Test&Refresh,P1-b2 已点亮)。**模型/设置 = 占位**(P1-d)。typecheck + 130 vitest + build(JSON 入包)全绿。**⚠️ 真机肉眼验欠**(UI headless 盲区:点🤖看 6 tab / 录 key / Edit base_url+模型 / Test 连接 / aistack Test&Refresh / 改路由;现有 keys 已配可 dogfood)。
- **本地模型管理 迁新壳**:模型下载/安装 catalog([[project_model_manager]]);不强制、可跳过([[feedback_no_forced_downloads]])。
  - **✅ P1-d 模型管理已落(2026-06-01,MVP + GPU + 目录 + 路由回填)**:`core_rpc/methods/models.py`(`models.catalog` 磁盘只读装机态 / `jobs` / `download` / `cancel` / `remove` / `root_dir` / `set_root_dir`)—— **复用现成 `core.models`**(catalog + range-resume downloader + DownloadManager),`manager.on_event(jobs)` 桥成 `event.models`(订阅一次,进程级)。**新 `gpu.*` 域**(`core_rpc/methods/gpu.py`:`gpu.status`/`install`/`uninstall` 全 job——`core.gpu.cuda_status()` nvidia-smi + `core.gpu_install` 的 nvidia-*-cu12 wheels;install 流式 pip log + 装后清 `_CUDA_PROBE_RESULT` 再测)。**路由回填**:`console_view._models_list` 改成对 `llama_cpp`(type)/`faster_whisper`(name)扫盘(`list_models()`)而非读静态 `cfg["models"]` → 模型管理装好后 AI console routing「内置」model 下拉**自动**出现(修安装→使用闭环;比 Tk LlamaCpp 静态还好)。renderer `models/ModelManager.tsx`:活动栏 📦,按 capability 分组 + 下载进度/取消 + 删除 + **GPU 卡(4 态 + 安装/卸载内联日志)** + **模型目录条(路径/打开/更改/刷新)** + 已装行 📂 打开文件夹;新 IPC `vc:openExternal` 之外复用 `showInFolder`/`pickFolder`。`test_gpu.py`(3)+`test_models.py`(7)+`test_ai.py` 扩(扫盘),共 **140 sidecar 测**;+35 i18n key(420 对)。**用户决定砍**一键下载档位;**defer**:下载前磁盘预检 / 强制刷新 HF 元数据。
- **preferences / about / File**:
  - **✅ P1-d Settings(⚙)已落(2026-06-01)**:`settings/Settings.tsx`——三段:**语言**(`LanguageToggle` 唯一归宿,已从 Hub launcher+顶栏删除——语言=set-once 偏好,活动栏 ⚙ 永远 1 click 可达含 launcher,不在每页留常驻控件)+ **运行环境**(`core_rpc/methods/env.py`:`env.components` 元数据 + `env.detect_all`/`env.detect`/`env.install` 走 job——检测跑 version 子进程、安装 shell 出 pip/Node 下载;install log 经 `progress.env.install` 流式)+ **about**。新 IPC `vc:openExternal`(http(s) 白名单,装指引外链)。换掉 `shell.settings_soon` 占位。`test_env.py`(3,检测/安装 monkeypatch),共 134 sidecar 测;+25 i18n key(399 对)。**defer**:GPU CUDA wheel dialog、change-models-dir、File 项目管理菜单。
  - ⇒ **活动栏 4 格(📁🤖📦⚙)全部落地**,新壳框架服务齐了(AI 配置 / 模型安装 / 环境依赖 / 语言均可在新壳内自助)。

**P2 — Tk 退役**(前提 = P0+P1 新壳功能对等):
- clip 工作台退役 → `creations/clip/component_defs` 与 `components/*` Tk specs 合并单一源(news_desk 已退)。
- 素材 Tk sidebar 退役;`src/ui/` tkinter 工作台/预览大幅瘦身删除。

**P2.5 — 插件全 TS / Python = 能力网关**(权威细节见顶部「🚩 架构转向」节;前提 = P2 已退役 Tk,因 clip Tk 仍依赖 `clip/config.py`):
- **Phase A**:clip+news_desk 创作的 per-plugin Python(config/presets/component_defs/preview/export/import/publish)全 port 成 TS;新增 `vc.fs.*` 主进程持久化;退役 `core_rpc/methods/creation.py` provider dispatch + `Session.creation_owner`。
- **Phase B**:news_video 素材模型 port 成 TS(`materials/news_video/{schema,paths,model}.ts`);新建路径式 `core_rpc/methods/capability.py`(asr/translate/analyze/ai_fill/acquire_source/probe/subtitle_check/save_chapters);顺手消除 `core/subtitle_pipeline.py:29-34` 的 `TODO(ADR-0005)` 越界(P4 那条 wart 在此一并解掉)。
- 产物:三插件零 Python;Python 仅剩框架目录生命周期 + 能力网关 + AI/models/env/gpu 框架服务。

**P3 — 打包 / 分发**(§7.3 待决,全未触及,目前纯 dev 模式无分发产物):
- sidecar:PyInstaller onedir(推荐)bundle `core_rpc.server` + myenv 依赖。
- Electron:electron-builder 出 Win 安装包;userData repo-local([[feedback_portable_data]]);Win11 26200 sandbox 兜底已在 `main.ts`。
- 二进制依赖:ffmpeg/ffprobe、yt-dlp 的 Node.js runtime 随包或引导。

**P4 — 打磨 / 补完**(非阻塞,按需):
- 素材:字幕双语并排 UI;决策性单源 wart 的真·per-instance 化(`subtitle_pipeline.py:29-34` TODO)。
- news_desk:逐章 schedule 编辑(现只读+seek)、transcript.md + per-chapter mp4 切分(publish.md 本体已恢复=续 36)、外部磁盘 SRT 导入。
- 导出域:逐帧精确 decode、剩余 overlay kind。
- i18n 余项:sidecar `RpcError.message`(Python 文案)双语化是单独决策;Tk 806-key 表与 renderer 表是否对齐/合并。

**P5 — 转场 + 录播自动剪辑**(地基已就位,真实需求驱动,暂缓):
- 转场(crossfade / dip_to_black):IR `Transition` + `resolveFrameAt` 重叠区双 active 已就位,缺 GPU per-layer alpha blend + 创作产出 + UI;用户决定暂不做(当前两形态语义上不需段间转场)。
- 录播自动剪辑(新创作形态;OTIO 多段装配的真实需求来源,[[project_recorded_autoedit]])——它会反过来驱动转场。

**P6 — 文档治理**:升 **ADR-0008「插件逻辑入 TS;Python = 能力网关」**(正文来源 = 顶部「🚩 架构转向」节;固化 渲染引擎 + IPC 拓扑 + 插件语言边界;数据模型已在 ADR-0006)。0008 supersede ADR-0004 的 provider-dispatch 部分 + `01-architecture.md`。**注:ADR-0007 已被「组件编辑 UI = FieldSpec 元数据」占用**(2026-06-01);foundation 大稿的数据模型部分已由 ADR-0006 承载,0008 聚焦 拓扑 + 插件边界这次转向。

---

## 0. 对齐结论(代码探查 + 文档复核已完成)

启动稿断言"引擎/UI 边界是设计时就有意铺好的"。**复核结果:成立,且比启动稿描述的更彻底。**

| 证据 | 来源 | 含义 |
|---|---|---|
| `core/composition/` 全层 **零 tkinter import**(20 文件 grep 验证) | 实测 | 引擎是纯函数库,直接 IPC-ready |
| `core/ai/` **零 tkinter**;严格三层,UI 禁 import `core.ai` | 实测 + [04-ai-router](../design/04-ai-router.md) | AI 能力天然是后端服务 |
| `materials/*/{model,schema,paths,ai_fill}.py`、`creations/*/{config,presets,composer,candidates,render_queue,publish}.py` **全部零 tkinter** | 实测 | 业务层已与 UI 分离 |
| `CompileContext` 注释明写 "pure data — no UI callbacks" | [ADR-0006](../adr/0006-composition-timeline-ir.md) | 编译器/编辑器接口 = timeline IR,跨进程无障碍 |
| `MaterialInstanceModel.subscribe(callback)` 已存在(`model.py:394`) | 实测 | 变更广播机制已有骨架 |
| 创作 config 单一内存所有者 + 素材经 Material Model | [creation-config-owner] / [ADR-0005] | 单一状态所有者原则已是现行铁律 |

**唯一需要 supersede 的旧决策**:`01-architecture.md` 明确写"放弃 subprocess、无需 IPC、AI Router 进程内单例、多工具共享进程内全局状态"。本方案反转它——但反转的只是**外壳进程模型**,业务/引擎代码一行不重写。

> 一句话:**这不是重写视频引擎,是给一个早已干净分离的引擎换前端。** 迁移成本 ≈ 重写素材/创作模块 UI + 框架外壳 + 一层 IPC(遗留 menubar 工具不迁,见 §0.5)。

---

## 0.5 范围(2026-05-29 收窄)

VideoCraft = Tier1 框架 + **素材模块** + **创作模块** 两条插件轴(见 [[project_ir_nle_standard]] / ADR-0004)。**Electron 只建支撑这个结构运行的部分**;现有 menubar 那一长串遗留独立工具不迁。产品本体(素材/创作)走 **sidebar**,不在 menubar。

**建(框架服务 + 产品本体)**:
- 框架外壳:启动器 → with-project Hub → sidebar(素材 + 创作两栏)+ 预览 tab
- 素材模块运行:源准备、分析 kind 运行、context 编辑、sidebar 面板
- 创作模块运行:各创作工作台(clip / news_desk / 字幕烧录 / 未来录播自动剪辑)+ 预览/渲染
- 依赖的框架服务:项目管理(File)、AI 路由/key/统计(AI console,**去 Prompts tab**)、本地模型管理、preferences/about

**不迁(遗留 menubar,逐项)**:
- Download / Speech / Translate —— 能力**重归素材**(源获取 = source-prep;ASR/翻译 = 分析 kind 插件,产 SRT 物件),不做独立工具
- Video 全部 8 项(split / concat / extract_mp3 / volume / extract_clip / auto_split / bitrate / word_subtitle)—— 纯砍
- Text2Video 全部(tts / srt_from_text / audio_video / daily_news / composer)—— 砍;将来要则重表达为创作模块
- AI → prompt_console —— prompt hub 已弃([[refactor_architecture]] 横幅)
- Publish(tiktok / youtube)—— **暂不做,用时再说**
- voice_picker —— 仅当素材/创作的 TTS 流程用到才保留(框架组件),否则砍

**⚠️ 本文多处已被后续决策取代,数据模型 + 渲染引擎 + 进程拓扑一律以 [`composition-otio-foundation.md`](composition-otio-foundation.md) 为准**:
- **§4"渲染后端留 ffmpeg"作废** → 自建 GPU 合成器走 OTIO + libass-wasm,预览=导出同源;
- **§2.3 dual-client 已删** → 磁盘即真相源,任一时刻只一个 app;
- **§1 拓扑图里 Python sidecar 的 "Render"、§2.2 的 "Render 域 / Preview 域" 作废** → **composition(IR + 组件库 + compositor + 预览 + 渲染)整块在 TS renderer**;Python sidecar 只剩 **project / material / analysis / AI**(ffmpeg 降为 mux,从 main 进程调)。composition 重构 ≡ 建 Electron renderer。
- §1 "Renderer:composition 预览(复用 .html 视觉)" 作废 → 不是复用旧 .html 近似预览,是 TS 原生 compositor。

---

## 1. 目标架构

```
┌─────────────────────────────────────────────────────────────┐
│  Electron 主进程 (Node/TS)                                    │
│   - 窗口生命周期 / 菜单 / 文件对话框                          │
│   - spawn Python core sidecar,持有其 stdio                   │
│   - 把 renderer 的 IPC 调用转发给 sidecar,反向广播事件        │
└───────────────┬─────────────────────────────┬───────────────┘
                │ JSON-RPC over stdio          │ Electron contextBridge
                ▼                              ▼
┌──────────────────────────┐      ┌───────────────────────────┐
│  Python core sidecar      │      │  Renderer (React/TS)        │
│  ★ 唯一状态所有者          │      │  - Hub / 工作台 UI          │
│  - Project / Material /   │      │  - composition 预览(原生    │
│    Creation / AI / Render │      │    canvas,复用 .html 视觉)  │
│  - 已有 core/* 代码        │      │  - <video> 直读 file://     │
│  - 0 行业务重写            │      │    (媒体字节不过 IPC)        │
└──────────────────────────┘      └───────────────────────────┘
```

**结构性承诺**:

1. **媒体字节不过 IPC**。现状 `composition_preview.html` 的 `<video>` 已经直接 `file:///` 读源视频;Electron renderer 同理。IPC 只传**结构化数据**(timeline JSON、config、进度数字)。这消除了"大 payload 过管道"的性能顾虑,也是当前 stdin 管道死锁 bug 的根除(那个 bug 长在"主线程同步写大 payload 到子进程 stdin")。
2. **不把 Electron 嵌进 Tk,也不把 Tk 嵌进 Electron**。迁移单位 = **整个窗口/工作台**。子面板级混合嵌入会重演 SetParent 之痛。
3. **状态是文件型的,任一时刻只开一个 app**。VideoCraft 全部状态落盘(`project.json` / `config.json` / `materials/` / `creations/`),**磁盘即真相源**。Tk 和 Electron 不同时运行,因此不需要运行时同步/事件广播层(早期草案设想的"同时双客户端 + `event.*` 广播"已删,属过度设计)。

### 1.1 为什么这个进程边界不会重演现在的 bug

最该警惕的反问是:"现在的痛就是跨进程,Electron 又引入 Python sidecar 跨进程,不是搬家吗?" **不是——是换了一个 bug 类别。**

| | 现状(Tk + 嵌入 WebView2) | Electron + Python sidecar |
|---|---|---|
| 谁画窗口 | **两个 UI 工具包合成进一个窗口**(Tk frame 里 SetParent 一个 WebView2) | Chromium **一家**渲染整窗 |
| 痛的来源 | reparent 后 GPU canvas 不呈现、AttachThreadInput 抢输入焦点、闪屏、stdin 桥死锁 | 无——无 SetParent / 无 AttachThreadInput / 无合成 |
| 进程边界性质 | **UI 合成边界**(两套渲染要假装是一个窗口) | **纯数据边界**(Python 什么都不画,只回 JSON) |

现在的 bug 全长在"让两套异构 UI 表现得像一个窗口"这件事上。Electron 模型里 Python sidecar **不渲染任何东西**,IPC 只是 JSON 一问一答,和任何 client/server 同级。那一类合成 bug **被消灭,不是被搬家**——这是选 Electron 的核心理由。

---

## 2. IPC 协议设计

### 2.1 传输层选型:stdio JSON-RPC 2.0(推荐)

| 候选 | 取舍 |
|---|---|
| **stdio JSON-RPC 2.0** ✅ | Electron 主进程 spawn python child,天然持有 stdin/stdout。单一双工通道,request/response + notification(服务端推送)都覆盖。无端口、无防火墙弹窗、无端口冲突。**推荐。** |
| localhost WebSocket | 也能推送,但要选端口、处理占用冲突、本机防火墙可能弹窗;多一层 socket 生命周期管理。仅在未来需要"core 服务多个外部客户端"时才值得。本期不需要。 |

**协议形态**:JSON-RPC 2.0。
- `request`(有 id):客户端发起的有返回值调用,如 `project.list_materials`。
- `notification`(无 id,服务端→客户端):事件广播 + 长任务进度,如 `event.material.changed`、`progress.render`。
- 长任务(ASR / 渲染 / AI 调用)走 **"立即返回 job_id + 后续 progress 通知 + 终态通知"** 模式,不阻塞通道。

> ⚠️ 当前 stdin 死锁的教训直接转化为协议约束:**写管道必须 off-thread + 消息队列**(已在 Tk 侧用 writer 线程修过,见 commit `392980e`)。Electron 主进程的 stdio 写默认异步,问题自然消失;但 Python sidecar 的读写循环要单独的 reader/writer 线程,不在请求处理线程里直接 write。

### 2.2 能力清单(RPC 方法面)

> ⛔ **creation/material 域被「架构转向」节取代**:这些 per-plugin RPC(load_config/update_component/plan_render/preview_data/material.* …)Phase A/B 后退役——创作/素材逻辑移入 TS,持久化走 `vc.fs.*`(Electron 主进程),Python 仅保留 *框架目录操作*(project.* 的 list/create/rename/delete instance)+ *路径式能力网关*(`capability.asr/translate/analyze/ai_fill/acquire_source/...`)。下表的 project/system/ai/models/env 域仍有效;creation/material 域作迁移考古。

按域组织。**每个方法都映射到已存在的 core API**——这张表同时是"迁移时哪些代码被 IPC 包一层"的清单。

#### Project 域(映射 `src/project.py` + `Project` 类)
| RPC | 映射 | 类型 |
|---|---|---|
| `project.recent_list` | `recent.json` 读 | 同步 |
| `project.create(source, name, parent_dir)` | 新建项目 + 源准备 | **长任务**(下载/拷贝有进度) |
| `project.open(folder)` / `project.close` | Project 加载 | 同步 |
| `project.list_material_types` / `list_material_instances` | `Project.list_material_*` | 同步 |
| `project.create_material_instance(type, name)` | 同名方法 | 同步 |
| `project.list_creations(type)` / `create_creation_instance` | creation ops | 同步 |

#### Material 域(映射 `MaterialInstanceModel` 协议 + `NewsVideoModel`)
| RPC | 映射 | 类型 |
|---|---|---|
| `material.slot_readiness(type, inst)` | `model.slot_readiness()` | 同步 |
| `material.get_artifact(type, inst, key)` | `model.get_artifact()` → 返回**路径字符串**(renderer 直读) | 同步 |
| `material.add_source_video(...)` | `NewsVideoModel.add_source_video` | **长任务** |
| `material.generate_subtitles(...)` | ASR 流程 | **长任务**(进度 + 可取消) |
| `material.ai_fill_context(...)` | `model.ai_fill_context(progress_cb, cancel_token)` | **长任务** |
| (事件) `event.material.changed{type,inst}` | `model.subscribe()` 回调转广播 | notification |

> `subscribe(callback)` 已存在——迁移时把回调实现改成"向所有 IPC 客户端 emit `event.material.changed`"即可,Model 内部零改动。

#### Creation 域(映射 `creations/*/config.py` 单一所有者 dataclass)
| RPC | 映射 | 类型 |
|---|---|---|
| `creation.load_config(type, inst)` | config dataclass 加载 | 同步 |
| `creation.update_config(type, inst, patch)` | 单一所有者写 + 广播 | 同步 + 事件 |
| `creation.bind_material(type, inst, material_ref)` | `bound_material` + 快照(ADR-0003/0005) | **可能长任务**(快照拷字幕) |
| `creation.list_components` / `add` / `remove` / `update_component` | 组件 CRUD | 同步 + 事件 |
| (事件) `event.creation.changed{type,inst}` | config 变更广播 | notification |

#### AI 域(映射 `core.ai` facade,**沿用现有 facade,不重写**)
| RPC | 映射 | 类型 |
|---|---|---|
| `ai.complete` / `complete_json` | facade | **长任务**(可取消) |
| `ai.describe(task,tier)` / `list_models(provider)` | facade | 同步 / 长任务 |
| `ai.get_routing` / `set_task_routing` | `router.set_task_routing()` | 同步 |
| `ai.list_providers` / `update_provider` / `test_provider` | router 配置 | 同步 / 长任务 |
| (事件) `event.ai.stats` | `stats.py` 计数变更 | notification(节流) |

> AI 域是最干净的——`core.ai` 本就是"UI 不许碰"的基础设施层,IPC 化等于把 facade 的函数签名直接转成 RPC schema。

#### Render 域(映射 `render_composition` + `render_queue.py`)
| RPC | 映射 | 类型 |
|---|---|---|
| `render.start(request_or_batch)` → `job_id` | `RenderQueue.start(jobs)` 逻辑搬后端 | **长任务** |
| `render.cancel(job_id)` | `RenderQueue.cancel()` | 同步 |
| (事件) `progress.render{job_id,done,total,out_idx,pct}` | `on_progress` 回调 → 通知 | notification |
| (事件) `event.render.job{job_id, out_idx, status, error?}` | `on_succeeded`/`on_failed`/`on_all_done` | notification |

> `render_queue.py` 的回调契约(`on_progress/on_succeeded/on_failed/on_all_done`)**原样保留**;唯一改动是 `_post` 从 `master.after(0,...)`(Tk marshal)换成"emit notification"。`render_composition(req, on_progress, cancel_check)` 一字不改。

#### Preview 域(映射 `compile_timeline` + `preview.py` 的 JSON 翻译)
| RPC | 映射 | 类型 |
|---|---|---|
| `preview.compile(type, inst, clip_range)` → timeline payload | `compile_timeline()` + `preview.set_timeline` 内的 JSON 翻译逻辑 | 同步 |
| (renderer 本地) `<video>` 直读源 + canvas 画 overlay | 复用 `composition_preview.html` 视觉逻辑,移植成 React 组件 | 不过 IPC |

> **关键**:`preview.set_timeline()` 现在做的事 = 把 timeline IR 翻译成 `setOverlays/setCues/setExtraWatermarks/setClipMeta` 一串 JS 调用。迁移时:**JSON 翻译逻辑留 Python**(它依赖 `wrap_subtitle_elements` / `wrap_hook_outro` 等引擎纯函数,绝不能在 JS 重抄——见 ADR-0006 不变量 #6);**翻译结果(payload)经 `preview.compile` RPC 一次性返回给 renderer**;renderer 的 canvas 消费这些 payload。`web_preview.py` / `web_preview_host.py` 的 SetParent + AttachThreadInput + stdin 桥 **整体删除**。

### 2.3 状态所有权:磁盘即真相源(单 app 运行)

> ⛔ **「★ 内存所有者在 sidecar」被「架构转向」节取代**:Tk 退役后只剩 Electron 一个客户端,creation/material 的单一内存所有者**移到 renderer(TS)**,经 `vc.fs.*`(Electron 主进程)独写落盘;Python 不再持创作/素材内存态(`Session.creation_owner/material_model` 退役)。"磁盘即真相源 + 单 app" 的核心原则不变,仅所有者换进程。

**不引入运行时同步/广播层。** VideoCraft 状态全部落盘,任一时刻只运行一个 app(Tk 或 Electron,见 §1 承诺 3)。因此:

```
   单个 app 进程内:
   ┌──────────────────────────────────────────┐
   │  Electron renderer  ──RPC──▶  core sidecar │
   │      (瘦客户端)              ★ 内存所有者    │
   │                              - Project       │
   │                              - Material Model │
   │                              - Creation config│
   │                              ▼ 写盘            │
   │                          project/config.json  │ ← 真相源
   └──────────────────────────────────────────┘
```

**规则**:
1. **一个 app 内**:renderer 是瘦客户端,所有写走 RPC 进 core;core 是该进程内的单一内存所有者(沿用 [creation-config-owner] 现行铁律),写成功后落盘。
2. **app 内的视图刷新**仍可用轻量 `event.*` notification(如长任务进度、`event.creation.changed` 让同窗口多个面板同步)——这是**进程内 UI 刷新**,不是跨 app 同步。
3. **过渡期 Tk 与 Electron 不并发**:用户开哪个就用哪个,关掉再开另一个时从磁盘重新加载。无需任何跨进程状态协调——这正是省掉双倍工作量的关键(见 §5 决策记录)。
4. 事件粒度 = 实例级(`{type, instance}`);不做字段级 diff(YAGNI)。

---

## 3. Electron 工程骨架 + Python sidecar 打包

### 3.1 工程结构(新增,不动 `src/`)

```
<repo>/
├── src/                      # 现有 Python(core 引擎 + 过渡期 Tk UI)
├── desktop/                  # 新增:Electron 前端
│   ├── package.json
│   ├── electron/
│   │   ├── main.ts           # 主进程:spawn sidecar、窗口、菜单
│   │   ├── preload.ts        # contextBridge 暴露 ipc.call/ipc.on
│   │   └── sidecar.ts        # 管理 python child + JSON-RPC 收发
│   ├── src/                  # React renderer
│   │   ├── hub/              # Hub 外壳 + sidebar + tab 区
│   │   ├── workbenches/
│   │   │   └── clip/         # ★ 首个试点
│   │   ├── preview/          # composition canvas(移植自 .html)
│   │   └── ipc/              # 类型化 RPC client(对应 §2.2 能力清单)
│   └── vite.config.ts
└── core_rpc/                 # 新增:Python sidecar 入口
    └── server.py             # JSON-RPC dispatch → 调 src/core/* 与业务层
```

`core_rpc/server.py` 是**薄 dispatch 层**:读 stdin JSON-RPC → 查方法表 → 调已有 core/业务函数 → 写 stdout。长任务包一个 job 注册表 + 进度回调转 notification。**它不含业务逻辑。**

### 3.2 打包方案

| 组件 | 方案 |
|---|---|
| Python sidecar | **PyInstaller onedir**(非 onefile,避免每次启动解压到 temp)。打进 Electron `resources/`。用现有 `myenv/`(uv 管理)冻结依赖。 |
| Electron app | electron-builder,产 Windows 安装包 / 便携包。Windows-first(对齐 architecture-vision §3:跨平台延后)。 |
| ffmpeg / ffprobe | bundle 进 resources(现已经是外部组件,`core/env` 检测)。 |
| libass / 字体 | libass 随 ffmpeg;字体走系统 `C:/Windows/Fonts`(现状,见第一轮 dogfood commit `9dce838`)。 |
| AI 模型 / Node runtime | **不 bundle**,运行时按需下载到 `user_data/`(铁律:[no-forced-downloads] + [portable-data])。 |
| 用户数据 | 全部 `<repo or install>/user_data/`,绝不写 %APPDATA%([portable-data])。 |

### 3.3 体积评估(粗估)

| 项 | 体积 |
|---|---|
| Electron runtime | ~80–120 MB |
| Python(PyInstaller onedir,含 numpy/Pillow/ASR 客户端等) | ~150–300 MB(取决于是否含 faster-whisper 等重依赖;若内嵌 AI 重依赖延后下载可压到 ~120 MB) |
| ffmpeg + ffprobe | ~80–120 MB |
| **基线安装包(不含模型)** | **~300–500 MB** |
| 模型(可选,运行时下载) | faster-whisper / Qwen 各数百 MB ~ 数 GB,落 user_data |

对比现状(Python + Tk + WebView2 复用系统 Edge):Electron 多扛 ~100 MB runtime + ~150 MB python 冻结。对一个本就要 bundle ffmpeg + 按需下载 GB 级模型的工具,这个增量可接受。**WebView2 依赖消失**(不再需要系统 Edge runtime),反而少一个外部前置。

---

## 4. 试点工作台:clip 端到端切片计划

选 clip 作首个 Electron 工作台(启动稿铁律 3:最痛、最 web-native、含预览,验证 IPC + 预览 + 渲染全链路)。

**clip 涉及的 RPC 子集**(验证面足够全):
- Project/Material:`get_artifact`(取字幕/源)、`bind_material`
- Creation:`load_config` / `update_component`(样式 tab)/ `list_components`
- Preview:`preview.compile` → canvas(crop 拖拽 = renderer 本地交互 + `event` 回 config)
- Render:`render.start` 批量切片 + `progress.render` + `event.render.job`(验证长任务 + 取消)
- AI:候选 tab 若调 hotclips,走 `ai.complete_json`

**端到端切片(每片可独立验证、Tk 仍可跑)**:

| 切片 | 内容 | 验证标志 |
|---|---|---|
| **E0** | `core_rpc/server.py` 骨架 + stdio JSON-RPC 收发 + reader/writer 线程 + 1 个 echo 方法 | Electron spawn sidecar,echo 往返通 |
| **E1** | Project/Material 只读 RPC(recent/open/list/get_artifact)+ Electron Hub 外壳 + sidebar 列表(只读) | Electron 能开项目、列素材/创作,数据来自 core |
| **E2** | Preview 域:`preview.compile` + canvas 组件移植(`composition_preview.html` 视觉逻辑 → React)+ `<video>` file:// 直读 | clip 预览在 Electron 里出画面,布局与 Tk 一致(肉眼对) |
| **E3** | Creation 域:样式 tab 双向绑定(`update_component` + `event.creation.changed` 回灌预览) | 改样式 → 预览实时变;关掉再开状态持久 |
| **E4** | Render 域:批量切片 `render.start` + 进度流 + 取消 + 终态 | Electron 里跑通导出,产物与 Tk 路径 byte 等价 |
| **E5** | 闭环:用 Electron clip 跑完"开项目→选素材→调样式→预览→导出",关掉重开状态从磁盘恢复 | clip 工作台在 Electron 里**独立可用**,体验无闪屏/卡顿 |

E5 通过 = **IPC + 预览 canvas + 渲染长任务 + 磁盘真相源全部验证**,可放心铺第二个工作台。(无需"双客户端同时跑"验证——§2.3 已决定不做并发。)

---

## 5. 迁移顺序 / 里程碑 / 回退点

```
M0  core/IPC 解耦(无悔第一步,与 Electron 进度无关)
     ├── core_rpc/server.py + JSON-RPC + job 注册表
     ├── 把 render_queue 的 _post、material 的 subscribe 回调
     │   抽象成"emit"接口(Tk 侧暂时仍 master.after 实现)
     └── 写一批 RPC 契约测试(server 侧,不依赖任何 UI)
     ★ 回退点:M0 即使 Electron 永不做也独立有价值——状态只有一个家。

M1  Electron 骨架 + clip 试点(§4 的 E0~E5)
     ★ 回退点:Electron clip 不达标 → 停在此,Tk 继续主用,无损失。

M2  第二、三个工作台迁 Electron(news_desk → ai_console)
     按 clip 验证过的模式复制,新旧并存。

M3  Material sidebar + Hub 主壳全量迁 Electron;新建项目/派生对话框迁过去
     Electron Hub 能独立 spawn 工作台窗口(启动稿:Hub 按需 spawn)。

M4  Tk 退役:删 src/ui/web_preview*.py、video_preview_pane.py、
     composition_preview.html 的 Tk 宿主、所有 Tk UI 模块。
     core + core_rpc + desktop 成为唯一形态。
     ★ supersede 01-architecture.md → 写 ADR-0008(0007 已用于组件编辑 UI 元数据)。
```

**铁律落实**(启动稿 §六):
1. ✅ M0 先做 core/IPC 解耦,无悔第一步。
2. ✅ 增量,新旧并存(M1~M3 双客户端共存),无大爆炸。
3. ✅ clip 第一个试点(M1)。
4. ✅ 单一所有者贯穿(§2.3),core 单进程。

**每个 M 的回退成本**:M0 纯增量;M1~M3 期间 Tk 始终可独立跑(in-process,零改动);只有 M4 删 Tk 是不可逆的,且只在 Electron 全量验证后执行。

### 5.1 功能冻结的真实范围(澄清成本)

迁移期的"冻结"**只冻 Tk-UI 侧功能**,不是冻结整个产品:

- **照常推进**:`architecture-vision.md` roadmap 的主体——composition v0.2(karaoke / smart-crop / hook 卡模板)、AI router 增强、plugin 化、prompt 工程——**几乎全是引擎/后端活**(`core/composition`、`core/ai`、`core/prompts`),不在 UI 层。引擎被 Tk 和 Electron **共用**,迁移期照常做,两个前端都受益。
- **冻结**:已开始迁移的那个工作台,不再往 Tk 版加新交互(避免给"将要删的代码"投资)。未迁的工作台仍可改。
- **结论**:没有"python 功能写两遍"。真实增量 = `Electron UI(任何迁移躲不掉)+ 薄 IPC dispatch(core_rpc)+ 一个小回调抽象(render/ASR 进度从 master.after 改成可 emit)`。core 业务/引擎代码零重写。

### 5.2 决策记录(2026-05-29 会话)

- 否决"继续堆 Tk"(A):预览的卡顿/闪屏/异构 bug 是 **Tk 托不住 web/视频表面**的结构性问题,堆功能只增技术债。
- 否决"只换预览机制"(B):预览嵌在工作台内,Tk 无原生浏览器组件 → 富预览必须把异构窗口合成进 Tk → 换汤不换药。
- 采纳"便宜版 Electron 全迁"(C):砍同时双客户端、磁盘做真相源、只冻 Tk-UI、引擎主线继续。

---

## 6. 范围红线(承自启动稿 §八)

- ❌ core 业务逻辑**不重写**,只 IPC 包一层。
- ❌ 不做 timeline 逐帧编辑(那是 Phase)。
- ❌ 不碰 aistack repo。
- ❌ 不做跨平台(Windows-first)。
- ❌ 预览的渲染前数据变换(wrap 等)**绝不在 JS/renderer 重抄**——必须经 `preview.compile` 由 Python 引擎纯函数算好(ADR-0006 不变量 #6,违反 = preview≠render 静默分裂)。

---

## 7. 待决问题(实施前确认)

1. ~~**renderer 技术栈**~~ **✅ 已落**:React 19 + TS strict;**裸 inline CSS**(无 UI 组件库)。体积/开发速度均可接受。
2. ~~**canvas 移植粒度**~~ **✅ 已落**:未复用旧 `.html`,直接建 TS 原生 compositor(`engine/`),preview≡render 结构性保证。
3. **PyInstaller vs 嵌入式 Python(打包)= 仍待决,未触及**:目前全 dev 模式跑(`pnpm dev` + `myenv/Scripts/python.exe -m core_rpc.server`),**尚无分发产物**。onedir PyInstaller(推荐)vs bundle embeddable python + myenv。见下「剩余工作计划」P3。
4. ~~**i18n**~~ **✅ 已定/已落(2026-06-01)**:renderer 自建轻量 `tr()`(非 i18next)+ 独立 `desktop/src/renderer/i18n/{zh,en}.json`(自包含,不复用 Tk 806 key);语言读写同一 `user_data/settings.json`(`system.get_locale`/`set_locale`),中/EN 热切换。详见顶部「renderer i18n」节。
