# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。**实现细节不放这里**——放到对应设计文档。

---

## ▶▶ 新会话从这读起(2026-06-01 更新,接力点)

> **🚩 重大架构转向进行中 = 三个本体收敛为纯 TS 插件,Python 退成 plugin-agnostic 能力网关(ADR-0008,已立)。** 起因:为 news_desk 恢复 publish.md(续 36)暴露"双语插件不可维护"。**权威设计 = `docs/draft/electron-migration-design.md` 顶部「🚩 架构转向」节 + `docs/adr/0008-plugins-ts-python-capability-gateway.md`。** **▶ 持久任务追踪(跨会话防遗忘,勾选进度看这个)= [`docs/draft/adr-0008-migration-tasks.md`](draft/adr-0008-migration-tasks.md)。** 进度:**Phase A 完成——clip + news_desk 两个创作都迁到纯 TS 路径并验过**(2026-06-01)。两者 config/preset/render 走 TS owner + `render.ts`、经 `vc.fs` 落盘;`client.ts` 按 `type==="clip"|"news_desk"` 分发到各自 `clientBackend.ts`(工作台 tabs **零改动**);`preview_data`/`get_artifact`/news_desk `imports` 仍走 Python(Phase A 桥,defer 到 Phase B)。commit `ad1352d`→`9077cfd`,**165 vitest 全绿**,clip+news_desk GUI 均验过(news_desk 导出能产出 mp4+publish.md)。
> **⚡ 遗留高优(用户拍板:迁移收尾后做)= 导出速度**:news_desk 全源 3 分钟视频导出 ~2 分钟,无法接受。**非 A4/A5 回归**(encode 逐帧循环未碰),瓶颈=每帧 GPU→CPU 读回 + exact 逐帧解码;**最大优化线索 = `Backend.canvasElement` 直接建 VideoFrame 免读回(半成品没接上)**。详见 `adr-0008-migration-tasks.md` 顶「⚡ 导出速度」。**下一步先验是否回归(git stash 对比)再优化。**

**下一步(迁移)**:**Phase B1 + B2 + B3.1 + B3.2(读+写+job+ai_fill)已完成**(2026-06-01/02,commit `b1ea0ad`→`13e9ef1`)。**B1**=TS 素材数据层。**B2**=能力网关 `capability.py`(路径式 job + 通用 `llm_extract`;`subtitle_pipeline` 加 plugin-free `*_paths`)。**B3.1**=news prompt+schema 移 TS(`aiFill.ts`)。**B3.2**=素材工作台接线:`client.ts` 按 `type==="news_video"` 把读/写/job 全分发到 `materials/news_video/clientBackend.ts`(走 `NewsVideoModel` + `capability.*`);变更通知用 `emitLocal`(client.ts 本地总线,`onNotification` 合并 server+local,Hub 零改动);job 完成后 tab 经新 `project.*` meta RPC(commit_source/set_source_language/add_translated_language)持久化 source/语言;ai_fill = 插件拼 prompt → `capability.llm_extract` → ContextTab 写回。**🚩 ai_fill=纯通用**(capability 零领域知识)。
> **⚠️ ASR 死锁排查(本会话大坑,已修+已记忆 [[reference_sidecar_native_import_deadlock]])**:真机验 B3.2 时发现 ASR 永远卡「正在加载本地模型」。根因=**daemon 线程首次 import ctranslate2(faster-whisper)C 扩展 + 有线程 park 在 stdin 阻塞读 = 死锁**(跟 GPU/模型/路径/迁移代码无关)。修=`core/ai/warmup.py` 启动时主线程预热原生 import(`674b5c3`)。**实测证伪**:挪 stdin、env 变量(OMP/ORT)都无效,预热是唯一解。详见记忆。
**接力下一步 = B3.2c 只读尾巴**(source_meta 走 project.current;slotReadiness 结构化 reshape + Hub SlotRow 走 tr() + i18n;listAnalysisArtifacts 需先把 analysis 注册表移 TS;importSubtitle)+ **整链真机验**(取源→ASR→翻译→章节→新闻背景)。**或** A6 退役创作 Python(仍卡 **P2 Tk 退役**)。进度勾选权威 = [`adr-0008-migration-tasks.md`](draft/adr-0008-migration-tasks.md)。

> **续 36(本节下方):news_desk + clip 导出恢复 publish.md/index.md,已 commit(`b3f2cb1`+`69ded12`,未 push)。**

> **续 35(本节下方):统一组件编辑器(引擎独占 FieldSpec 元数据)已落地 + push。** 全组件迁完、news_desk 单位归一、颜色控件升级、ADR-0007 已立。**当前唯一阻塞 = 真机肉眼验**(编辑控件 / 各工作台预览 / i18n 热切换 / AI console·模型·环境 P1 的 headless 盲区);验完即进 **P2 Tk 退役**。先读 `docs/draft/electron-migration-design.md` 顶部「★ 实现进度」(含「统一组件编辑器」节 + 「剩余工作计划」P0~P6)+ `docs/adr/0007-component-edit-ui-metadata.md`。

**clip + news_desk + 素材(material)侧均已在新架构(Electron renderer + 自建 GPU 合成器 + Python sidecar)端到端实现;Tk news_desk 已退役。** 续29~31 收口 news_desk;**续 32 把素材侧整块迁过来(M0~M6 + gap A~D)**,**续 33 真机复核后修了三处**(预置语言选择器 / 新闻背景页用法澄清 / 分析 kind 精选)。**两笔已落 `main`:`fd2cffb`(素材迁移)+ `9aeb9bd`(三处修正),均未 push。**

**✅ renderer 双语(i18n)改造 + 热切换已完成(续 34,已落 main `a3b53af` 并 push)。** 整个 renderer(Hub + clip/news_desk/material 工作台)硬编码中文已抽成 `tr()` key;轻量自建 i18n(`desktop/src/renderer/i18n/` + 新 RPC `system.get_locale`/`set_locale` 读写同一 `user_data/settings.json`,与 Tk 锁步),zh/en 290 对严格对称。**中/EN 切换是热的**(`tr()` 每帧求值 + `useSyncExternalStore` reactive,`LanguageToggle` 放 Launcher + 项目顶栏,点即翻 + 持久化回 settings.json);区别于 Tk 重启制。typecheck + 130 vitest + build(98 模块)+ 114 sidecar 测全绿。细节见 `electron-migration-design.md`「renderer i18n」节。

**✅ P0 真机肉眼验已跑完(2026-06-01):** 素材侧 e2e(建实例→导源本地+yt-dlp→ASR→质检→章节 seek→context→AI 填充)+ i18n 热切换(中/EN 整树即时翻+重启保持)均已真机过。三大本体 + i18n 的 headless 盲区全部人肉收口。

**✅ P1 框架服务基本完成(2026-06-01,新壳自给自足)。** 活动栏改 VSCode 式左侧导航,4 格全落地:**📁项目 / 🤖AI / 📦模型 / ⚙设置**。新壳现在能自助配 AI(provider/key/路由/aistack/Edit base_url·模型/Test 连接)、装嵌入式模型(下载/进度/删除)、查装环境依赖(ffmpeg/Node/yt-dlp 检测+安装)、切语言——不再依赖 Tk app。
- 新增 sidecar 域:`ai.*`(read+write+网络 job)、`models.*`(catalog+下载 job)、`env.*`(检测+安装 job);读模型 `core/ai/console_view.py`(UI-free,从 Tk 提升);renderer `aiconsole/` `models/` `settings/` `app/ActivityBar.tsx`。新 IPC `vc:openExternal`。语言开关搬进 Settings(Hub 两处已删,语言=set-once,⚙ 永远可达)。
- 验证:typecheck + 130 vitest + build + **134 sidecar 测**全绿(ai 12 + models 5 + env 3,网络/下载/子进程全 monkeypatch)。细节见 `electron-migration-design.md` P1 各节。
- **defer(P1 剩余,非阻塞)**:aistack「Test&Refresh」已做但 LLM Test 是 1 词探针;GPU CUDA wheel dialog;change-models-dir;tier 批量下载;File 项目菜单;装好的 faster_whisper/llama_cpp 模型回填路由下拉;TTS 音色 browse/catalog。

**▶ 下一大任务 = 真机肉眼验 P1(headless 盲区)** + 然后 **P2 Tk 退役**。**先 `desktop/dev.ps1` 完整重启**(本轮加了 3 个新 Python 域 + 新 IPC,Ctrl+R 不够),逐项验:🤖 6 tab 数据/录 key/Edit base_url+模型/Test 连接/aistack Test&Refresh/改路由 · 📦 下载一个模型看进度+删除 · ⚙ 环境检测/装一个(如 Node)/语言在 Settings 切。验完进 P2(clip 工作台 + 素材 Tk sidebar 退役)。完整 P0~P6 计划见 `electron-migration-design.md`「剩余工作计划」节。

- **新会话先读**:`docs/draft/electron-migration-design.md` 顶部「★ 实现进度」(含 clip + news_desk + 素材侧 全部实现状态、代码位置、坑)+ 奠基稿 `composition-otio-foundation.md`(数据模型/渲染/拓扑权威)。
- 工作纪律:忠实还原既存 Tk UI 交互,不发明/不简化([[feedback_faithful_port_not_invent]]);**用户菜单/选项列表照搬 Tk 实际菜单构造,别从引擎 registry 重建**([[feedback_ui_menu_from_tk_not_engine]],续 33 踩过:分析 kind 多列了 2 个);改 Python 必整重启 sidecar(`desktop/dev.ps1`,Ctrl+R 只重载 renderer);素材数据经 Material Model([[feedback_material_via_model_only]]);config 单一所有者([[project_creation_config_owner]]);**改 i18n 必 zh/en 双语同步、UI 新字符串走 tr()**([[feedback_i18n_symmetry]])。
- 历史进展见下「续 N」;news_desk 迁移 = 续19~31;素材侧 = 续 32~33。

---

## ▶ 续 32(2026-05-31,素材(material)侧迁新架构 M0~M6 + gap A~D — 已落 main `fd2cffb`)

用户决策:**忠实照搬 project-level 单源行为**(不修 per-instance 地基)、**整个素材侧一次做完**、**源获取本地+yt-dlp 都做**。第三个迁入新架构的产品本体。**Python 业务一行未重写**——薄 RPC + job 包既有 `NewsVideoModel`/`source_acquire`/`subtitle_pipeline`/`chapters_io`。细节(代码位置 / 已知限制 / 单源 wart)全在 `electron-migration-design.md` ★实现进度 末「素材(material)侧」节。

- **20 RPC**:`project.{create_material_instance,list_material_types_info}` + `material.*`(context/basic_info 读写、source_meta、字幕/分析读、save_chapters + 5 个 job:set_source/run_asr/run_translate/run_analysis/ai_fill_context)。
- **renderer**:`ipc/runJob.ts`(通用 sidecar-job 消费,subscribe-first 防竞态 + `useJob`)、`workbenches/material/*`(三 tab 壳 + Source/Subtitles/Context tab + ChapterScheduleEditor)、`workbenches/shared/fields.tsx`(字段行从 news_desk 抽出共享)、Hub 素材 [+] + 可点行 + 事件实时刷新。
- **修了一处 dead-broken bug**:`model.ai_fill_context` 旧代码向无该参数的 `extract` 转发 `progress_cb` → 必 TypeError(无 Tk 调用方,Tk 直调 extract);改为不转发。
- **gap A~D 补全(对照 Tk 检视/编辑层)**:A 源视频预览(SourceTab `<video>` + vc-media://)/ B 字幕查看+质检(`SubtitleViewer` + `check_subtitle`/`quick_fix_subtitle`)/ C 章节编辑器视频 seek(跳转+取当前)/ D 外部 SRT 导入(`import_subtitle`+`vc:pickSubtitle`)+ 分析产物查看(`list_analysis_artifacts`/`read_analysis_text`/`AnalysisTextViewer`)。material RPC 共 24 个。
- **验证**:`tests/core_rpc/test_material.py`(inline-job runner 防 daemon 竞态);TS typecheck + 130 vitest + `pnpm build` 全过;全套 `pytest tests/` 仅 3 个 pre-existing 失败(golden CRLF x2 + clip_config stale id),无新增。
- **单源 wart**(`single_instance=True` 挡 2nd 实例)+ 字幕双语并排 = 后续打磨。

---

## ▶ 续 33(2026-06-01,真机复核三处修正 — 已落 main `9aeb9bd`)

`fd2cffb` 真机过了一遍,用户当场抓出三处,逐个修:
- **预置语言选择器**:ASR 源/翻译目标/导入语言原本是裸文本框,丢了 Tk `ttk.Combobox` 的预置匹配。加 `system.list_languages`(暴露 `core.lang_names.WHISPER_LANG_CHOICES` 99 语言)+ 新 `LanguagePicker` 组合框(打字过滤预置、选中存 iso、ASR 带「自动检测」)。
- **新闻背景页用法**:看不出哪些是用户输入、哪些是 AI 产出(5 字段线索默认折叠藏了)。重构成显式三步(① 你的线索/AI 输入 → ② AI 填充 → ③ AI 生成的 15 字段背景/下游唯一源/可校正)+ 各组来源标签。
- **分析 kind 多列**:"生成分析"按钮列了全 4 种(从引擎 `subtitle_analysis.ANALYSIS_TYPES`/`RUNNERS` 取),但 Tk 只给 2 种——`node_panes._show_analysis_menu` 里 `hidden={transcript, chapter_transcript}`(那俩只供 news_desk export/publish 内部用)。改成只 `analysis`+`hotclips`,镜像 Tk hidden 过滤;查看已有产物仍不限 kind(Tk 也只精选"生成")。**教训存记忆 [[feedback_ui_menu_from_tk_not_engine]]:用户菜单照搬 Tk 实际菜单,别拿引擎能力全集当菜单。**
- **验证**:`test_material.py` 23 测(+`system.list_languages`)+ TS typecheck + 130 vitest + build 全过。

---

## ▶ 续 34(2026-06-01,Electron renderer 双语 i18n 改造 — ✅ 已完成,已落 main `a3b53af`+push)

**做法**:轻量自建 i18n(否决 i18next)。`desktop/src/renderer/i18n/{tr.ts,zh.json,en.json,LanguageToggle.tsx}`——`tr(key, vars?)`(fallback 链 当前→en→raw;`{name}` 插值)+ `getLang/setLang/useLang`;zh/en 290 对**严格对称**。语言来源 = 新 RPC `system.get_locale`/`set_locale` 读写同一 `user_data/settings.json`(与 Tk 锁步,默认 en);`main.tsx` boot `await getLocale` 后 `setLang` 早于首帧。Hub + 三工作台全部硬编码中文 → `tr("<域>.<key>")`(域前缀 hub/clip/news_desk/material/common/workbench);静态数组改 key-map + render 时求值;RPC 的 description_zh/en 按 getLang 选。**代码注释不动**。三工作台抽取经并行子代理完成,JSON 由脚本核对(字面 key 全命中、zh/en 对称、残留中文仅 JSDoc)。**热切换**:`tr()` 每帧求值 + `tr.ts` reactive(`useSyncExternalStore`,`setLang` 通知);`Shell` 顶层 `useLang()` 订阅 → 整树重渲染(无 memo 边界,工作台 state 不丢);`LanguageToggle`(中/EN)放 Launcher 右上 + 项目顶栏,点即翻 + `rpc.setLocale` 持久化(best-effort)。**验证**:typecheck 干净 + 130 vitest + build(98 模块,JSON 入包)+ 114 sidecar 测(+`get_locale`/`set_locale` round-trip + reject,monkeypatch SETTINGS_FILE 防污染)全绿。细节见 `electron-migration-design.md`「renderer i18n」节。**欠**:真机肉眼验热切换;sidecar `RpcError.message`(Python 文案)双语化是单独决策(本轮只做 renderer 自有硬编码)。

<details><summary>（原任务规划,已落地,留档）</summary>

**现状**:整个 `desktop/src/renderer/`(clip / news_desk / Hub / 素材 工作台)**纯中文硬编码、零 `tr()`**(grep `desktop/src/renderer/` 无任何 `i18next`/`useTranslation`/`tr(`)。Tk 侧有完整双语(`src/i18n/{zh,en}.json` 806 key + `tr()`),但 Electron renderer 迁移时一直没接 i18n——见迁移设计文档 §7 待决问题第 4 条。这是用户明确要求恢复的缺口(创作侧迁移时就欠下,不是这次砍的)。

**目标**:给 renderer 铺一层轻量 i18n,把所有硬编码中文抽成 key,补齐 en,zh/en 同步([[feedback_i18n_symmetry]])。

**范围**(全前端,一次做全,别只做素材造成半中半 key 的不一致):
- `desktop/src/renderer/hub/Hub.tsx`(素材/创作 sidebar、launcher、菜单)
- `desktop/src/renderer/workbenches/clip/*`、`workbenches/news_desk/*`、`workbenches/material/*`、`workbenches/shared/*`
- 文案分两类:① UI label/按钮/section → 走 tr();② 错误信息(很多来自 sidecar `RpcError.message`,那是 Python 侧文案)——sidecar 错误文案是否也要双语化是单独决策,**先只做 renderer 自有的硬编码中文**。

**起手步骤建议**:
1. 选方案:i18next(成熟、重)vs 自建轻量 `tr(key, vars?)`(读 locale + zh/en JSON,~30 行)。renderer 是新栈、字符串量中等,**倾向自建轻量**,与 Tk 的 `tr()` 心智一致;key 命名可复用/对齐 Tk 的 `src/i18n/{zh,en}.json` 结构。
2. 建 `desktop/src/renderer/i18n/`(`zh.json`/`en.json` + `tr.ts` + locale 来源:先固定跟随系统或加个开关,后续再接 preferences)。
3. **逐文件抽**:grep 中文字符串 → 起 key → 替换成 `tr("...")` → 同步写 zh/en。建议从 Hub + shared/fields 开始(共享面最大),再 clip/news_desk/material 各工作台。
4. 每抽一批 `pnpm typecheck` + `pnpm test`(快照/逻辑测不应受影响)+ 真机扫一眼。

**工作纪律**:UI 新字符串必须走 tr()、zh/en 双语同步([[feedback_i18n_symmetry]]);core/sidecar 层不引 renderer 的 tr;改 UI 布局/模块前 grep `docs/`([[feedback_check_design_docs]]);UI 文案不准用代码内部名([[feedback_user_facing_naming]])。

</details>

---

## ▶ 续 35(2026-06-01,统一组件编辑器 = 引擎独占 FieldSpec 元数据 — 已落 main)

dogfood 抓出图片水印属性面板一连串病(小数打不进、上下箭头 +1、position 是自由文本而非 anchor、标签露内部名),根因 = 迁移期一直用通用 `PropertyPanel` 直接编辑各插件原始 wire dict、从值/字段名猜控件与步进。落地奠基稿 §4.5 早已拍板、只是没建的**组件编辑 UI ①**:引擎独占的 `FieldSpec[]` 元数据驱动单一 `<ComponentEditor>`,clip + news_desk **共用**;并把 news_desk wire 单位/字段名**归一**到与 clip 一致(全分数 + 规范名)。**全部组件(水印/字幕/卡片/chapter 嵌套)迁完**,`PropertyPanel`/`ImageWatermarkProperties`/`ChapterProperties`/`chapterPatch` 已删。**权威决策 = `docs/adr/0007-component-edit-ui-metadata.md`**(FieldSpec.key=wire snake / clamp 仅在 mapping / kind 前缀解析 / 嵌套 path 重发)。

- 代码:`composition/components/fieldSpec.ts`(+ 各组件 `*Fields`);`renderer/workbenches/shared/{ComponentEditor,fieldControls,nestedPatch}.tsx`;两 StyleTab 恒用 ComponentEditor;`news_desk/{component_defs.py,types.ts,mapping.ts}` 归一。**顺带修一个潜在 bug**:news_desk 文字水印 mapping 读的是 Python 早已改名前的 stale key。
- 验证:typecheck + **132 vitest**(+nestedPatch 6 测)+ build + news_desk pytest 全绿;唯一失败 `test_clip_config` stale-id 是 baseline 既有([[project_pytest_preexisting_failures]])。**欠真机肉眼验**:canvas 绘制 + 各控件 headless 测不到——需启 desktop 验小数输入/步进/anchor 下拉/中文标签/chapter mode 门控+嵌套改值不丢兄弟。
- **续35 后续修复(均已 push)**:取色器升级 `@uiw/react-color` Sketch + 屏幕吸管;`FieldSpec.display` 显示单位(字号 px@1080 / 边距·缩放 % / 不透明 %,存储仍规范,统一字幕·章节字号都显示 px);候选切换/nudge 进度归零;**文字水印 draw-key 修**(canvas2d 原按卡片 key 读 → 文字水印颜色/字号/透明度失效,改按 kind 选 key + alpha + 不描边)。这些都是 canvas/控件 headless 盲区,真机验时一并看(取色器+吸管 / px·% 显示 / 文字水印颜色·字号·透明度)。**ADR-0007 已含 display 单位约定。**
- **⚠️ 旧数据(pre-normalization)需重建**:归一前创建的 news_desk 预设/实例带旧 wire key(`scale_pct`/`opacity`/`fontsize`/整数 margin,非 `image_scale`/`text_*`/分数);新编辑器按"实例实际字段"渲染会少行(缩放/不透明/图片文件不显示)、mapping 读规范 key=undefined → 水印渲染坏。**已清空 `user_data/presets/news_desk.json` 两个旧用户预设(备份 `.bak`)**;从旧预设套出的 news_desk 实例需在 app 内重建组件/实例(新建从 `component_defs` 出=规范 schema)。clip 侧 fraction-native 无此问题。**不写迁移器**([[feedback_pre_alpha_no_legacy]],用户拍板重建)。
- **接力下一步 = 真机验上述 + 之前积压的 P1 headless 盲区**(见下方旧接力点)。

---

## ▶ 续 37(2026-06-01,架构转向:插件全 TS / Python 能力网关 — ADR-0008 立 + Phase A1 落,已 push)

续 36 恢复 publish.md 时,用户追问"这东西是 Python 还是 TS 形态、合理吗",顺藤摸到根因:**三个本体(clip/news_desk 创作 + news_video 素材)是双语插件**(每个 TS≈1900 行 + per-plugin Python≈1200 行),**长期不可维护**。深挖探查(3 个 Explore + 1 Plan agent)确认:per-plugin Python 几乎全是纯 JSON/dict/markdown 逻辑、零重依赖;TS 侧已有 ~85% 目标;唯一真绑 Python 的是能力(ASR/LLM/yt-dlp/ffmpeg)。

- **决定**(用户拍板):三插件变纯 Electron/TS、零插件专属 Python;Python 退成 **plugin-agnostic 能力网关**(按路径调用的通用 job)+ 框架目录生命周期 + AI/models/env/gpu 框架服务。**文件 I/O 走 Electron 主进程 Node fs**(扩展 `vc:writeFile`→`vc.fs.*`)。**分阶段**:Phase A 创作先、Phase B 素材后;**前提 = P2 Tk 退役**。
- **已落**(全 push):① 方案并入 `electron-migration-design.md`「🚩 架构转向」节 + supersede 标记(3 个「Python 业务面」节 ⛔ / §2.2 / §2.3 / 工作计划 P2.5 / P6)`6d61e83` · ② **ADR-0008** 立 + README 索引 + ADR-0004 provider 部分标 superseded `88d5c62` · ③ **Phase A1** = `vc.fs.*` 通用文件 I/O 地基(main.ts handlers + assertInProject + 项目根嗅探 + preload/global.d.ts/`renderer/ipc/fs.ts` 注入 seam)`ad1352d`,build-green(typecheck + build + 132 vitest)。
- **▶ 持久任务追踪 = [`docs/draft/adr-0008-migration-tasks.md`](draft/adr-0008-migration-tasks.md)**(跨会话防遗忘,每步勾选)。**接力下一步 = A2**(`creations/clip/configOwner.ts` + `presets.ts` + shared,带 vitest)。**⚠️门**:A4/A6/B5 删 Tk/Python 前必过人工真机验。**工作纪律**:per-port 取注入式 `Fs` 接口供 vitest;每步 build-green、TS 替代测好前绝不删对应 Python;`writeJson` 原子复刻 Python `*.save()` 保 golden;`assertInProject` 守路径安全([[feedback_portable_data]])。

---

## ▶ 续 36(2026-06-01,news_desk 导出恢复 publish.md — 已 commit `b3f2cb1`+`69ded12`,未 push)

dogfood 抓出 news_desk 在新架构导出时 **publish.md 机制丢失**。根因 = Tk news_desk 退役(续 31)时删了 `creations/news_desk/publish.py`,而新架构 `export.py` 的 `commit_render` 只写 `output.json` sidecar、把 publish.md **显式 DEFERRED**(docstring 里写明)。导出时不再生成发布稿(YouTube 描述 / 章节块 / 节目概况 / 候选标题 / 字幕引用 / 逐章详情+文字稿)。

- **恢复**:① 纯模板 `creations/news_desk/publish.py`(从 dist 冻结版 `render_news_desk_publish` 捞回,纯函数、与 clip 的 publish.py 同位;import `core.markdown_fmt.t`);② `export.py` `commit_render` 末尾 best-effort 调 `_write_publish_md`(数据全从实例状态 + 绑定素材 `context.json` 取,ADR-0003 快照原则;**语言跟源不跟 UI** [[project_publish_sidecar]]——subtitle.is_chinese→zh/en,无字幕回退 `project.meta.language.source`);③ `delete_render` 连 publish.md 一并清。renderer **零改动**(commit_render 本就在 `exportTimelineToMp4 → vc:writeFile → commit_render` 末尾被调)。
- **仍 deferred**(Tk 时代两个 default-off opt-in):transcript.md + 按章节切 mp4(后者是 publish 侧 ffmpeg stream-copy,非 GPU 渲染)。Tk 的导出选项对话框(publish/transcript/chapter_videos 三勾)也没还原——publish.md 按 Tk default(恒开)生成。
- **clip 同病一并修**(commit 2):新架构 clip `export.py` `commit_render` 也只写了 JSON sidecar、丢了 `clip_NNN[_hook].md`(X/TikTok caption 复制)+ `index.md`(全切片总览表)——只 Tk `clip_tool.py` 在写。接 `render_clip_publish`/`render_clip_index`/`collect_clip_sidecars` 进 clip 的 `commit_render`(每候选写自己的 .md + rescan 全 sidecar 重建 index.md)+ `delete_render` 删后重建 index.md(stale-cleanup 的 keep set 早含 `.md`,本就预留)。
- **顺手修 2 个 stale 测试**(commit 2):`test_add_component_appends_and_persists`(`scale_pct`→`image_scale==0.15`)、`test_added_subtitle_...`(`block_margin_pct` 整数 9→分数 0.09)——续 35 归一化漏更新,与 publish 无关但同文件,一并对齐。
- **验证**:news_desk +3 测、clip +2 测(commit 写 .md/index + 内容断言、delete 重建 index)全过;**`tests/core_rpc/` 全套 146 测全绿**(原 2 个 stale 失败已消)。
- **欠**:真机各导出一次确认 publish.md / clip_NNN.md+index.md 落盘(commit_render 本体已被单测覆盖,真机只是确认渲染流程真能走到它)。

---

## ▶ 接力入口(2026-05-30 更新)

**clip 创作工作台已在新架构(Electron renderer + 自建 GPU 合成器 + Python sidecar)端到端实现完整、真机肉眼验过。**

> **2026-05-30/31 续:音频端到端补齐 + compositing 复核完整 — 真机肉眼验通过(预览有声 + 进度条可拖 + 导出 mp4 有声同步)。** 详见本文件末「续 15」+ 奠基稿 `composition-otio-foundation.md` 末「音频 + compositing 实现状态」节。要点:demux/decode/导出 AAC mux/预览音频主时钟全落地,118 测 + typecheck + build 全绿;转场按用户决定暂不做。
>
> **⚠️ 排查教训(见 [[feedback_restored_files_lost_edits]]):** 早先一次 git-checkout 清理后,音频编辑只重做回了一部分。**三处** land 漏掉、从未提交,逐个在 live 调试中才发现:① clip 装配器音轨(`0d09738`)② `encode.ts` 整个导出混流 + ③ `draw.ts` 音轨跳过(`936de6f`)。下次跨 sibling 文件重做编辑后,先 `grep` 全部 sibling 确认对齐,别靠 typecheck/测试(它们当时全绿)。

- **新会话先读**:[`docs/draft/electron-migration-design.md`](draft/electron-migration-design.md) 顶部「★ 实现进度」——那里有完整实现状态、代码位置、与设计文档不同的决策、已知坑、测试、下一步。**clip 工作台的细节都在那,不在本文件。**
- 数据模型/渲染/进程拓扑权威 = [`composition-otio-foundation.md`](draft/composition-otio-foundation.md)。
- **下一步**:clip dogfood 打磨 → news_desk 迁同套组件库 → Tk clip 退役(`component_defs` 合并 Tk specs)。详见上述文档「下一步」。
- 工作纪律(踩过 3 次):忠实还原既存 UI 交互,不发明、不简化;只改重构文档已决议的(ffmpeg→GPU / composition Python→TS / 单进程→sidecar)。见 [[feedback_faithful_port_not_invent]]。

> 下面 续1~续7 是 sidecar/IPC/substrate 地基的历史记录(已落地);clip 工作台的 续8~续14 细节已迁入设计文档,本文件仅留此入口。

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

## ▶ 续 8~14 已迁入设计文档(2026-05-30)

clip 工作台新架构实现的全部细节(Hub 壳 / creation 写操作面 / Inc2 三 tab + 组件增删排序 / Inc3 候选 tab + 详情 / Part A 导出管线 / Part B 工具栏+预设 / 双语 / 删候选语言下拉,及一路踩过的坑与修复),已整理进
[`docs/draft/electron-migration-design.md`](draft/electron-migration-design.md) 顶部「★ 实现进度」。**本文件不再保留这些细节**——见顶部「接力入口」。

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

---

## ▶ 续 15(2026-05-30,音频端到端 + compositing 复核 — 已提交 `d0f8b00`)

用户指出新架构 GPU 引擎是**纯视频**的:OTIO IR 有 audio 轨/clip 类型(含 `gainDb`),但引擎从未解码/播放/混流音频,导出无声、预览无音画同步。本轮把音频做到端到端,并复核 compositing。**Python 一行未动**(纯 `desktop/` TS/renderer)。

**已落地(代码位置 + 细节都在奠基稿末「音频 + compositing 实现状态」节,本文件只留指针)**:
- 解码:`engine/source/{Demuxer,MediaSource,AudioReader}.ts` + `sample-types.ts` + 新 `webcodecs-audiodata.d.ts`(补 lib 缺的 `AudioData` ambient 类型)。
- 装配:`creations/{clip,news_desk}/assemble.ts` 各产一条 audio Track;`engine/compositor/draw.ts` 显式跳过 audio 轨(非视觉)。
- 纯逻辑:`composition/compositor/resolveAudio.ts`(+测 7)+ `engine/export/audioMix.ts`(+测 8)——预览/导出同一解析,preview≡render 延伸到音频。
- 导出:`engine/export/encode.ts` 加 muxer AAC 轨 + `AudioEncoder`(48k/`mp4a.40.2`),`ExportTab.tsx` 解码源音频喂入。
- 预览:`engine/playback/AudioPlayback.ts`(Web Audio,音频主时钟)+ `CropPreview.tsx` 播放/暂停按钮 + rAF 循环。
- **118 测全绿 + typecheck 干净**(`cd desktop && env -u ELECTRON_RUN_AS_NODE pnpm test / pnpm typecheck`)。

**承重决策**:① 预览音画同步=音频主时钟(NLE 标准);② 导出=decode→mix(PCM)→AAC re-encode,不做压缩域 passthrough(clip 任意点切 + gainDb + 未来多轨混音都需 PCM 域);③ 音频解析独立于 `resolveFrameAt`(视觉 FrameSlice)。

**Compositing 复核结论**:多 overlay 轨 alpha 叠加 + `image_watermark`(`overlay/canvas2d.ts` 已实装,非 TODO)+ 视频 fit/crop 全在用 = **已完整**。唯一缺口=转场(crossfade/dip),**用户本轮决定暂不做**;地基已就位(IR `Transition` + resolver 重叠区返双 clip),真实需求来自未来录播自动剪辑(多段装配)。

**live 肉眼验已通过**(2026-05-31,见续 16)。已知潜在打磨点(留 dogfood):多源/多音轨混音、音量 UI、转场 = 未来。

---

## ▶ 续 16(2026-05-31,音频真机验通过 + 三处 lost-edit 修复 + harness 退役 — 已推 origin,HEAD `6413f37`)

续 15 的音频代码 typecheck/测试全绿,但**真机一验全是哑的**——预览无声、导出无声。逐个 live 调试才发现:续 15 那批音频编辑**只重做回了一部分**,三处关键 land 漏掉、从未提交(早先一次 git-checkout 清理后没补全;typecheck + 118 测当时全绿,完全没挡住)。逐个揪出并修复:

| 现象 | 真因 | 修复 commit |
|---|---|---|
| 预览无声 | `creations/clip/assemble.ts` 根本没产音频轨(只有 news_desk 产了);clip timeline 无 audio track → `resolveAudioSegments`=空 | `0d09738` |
| 进度条拖不动(顺带) | rAF 每帧 `setT` 覆盖受控 slider 值 | `78aa018`(slider onPointerDown=pause) |
| 导出无声 | `engine/export/encode.ts` **整个音频混流路径不存在**(`AudioEncoder`/`planAudio`/`encodeAudioTrack`/muxer 音轨全没),但 `ExportTab` 一直在传 `audioSources` 被静默忽略;且 `draw.ts` 没跳音频轨(audio clip 是 media kind,会被当视频画) | `936de6f` |

中间还做了几个合理但非病根的修(`cf23adb` 去 mp4box gate、`c4421ff` await ctx.resume、`78aa018` 改用 `decodeAudioData`)——这些都保留(本身是对的加固),病根是装配/导出层 lost-edit。

**教训(已存 memory [[feedback_restored_files_lost_edits]])**:跨 sibling 文件重做编辑后,**grep 全部 sibling 确认对齐**,别信 typecheck/测试(它们当时全绿)。装配器音频轨现在仍**无契约测试**——`clip.test`/`news_desk.test` 只绕开音频轨没断言它存在;补一条 `resolveAudioSegments(tl).length===1` 的断言能挡住复发(用户已知,未做,低成本可随时补)。

**最终验证状态(真机肉眼)**:✅ clip 预览播放有声 + 音画同步 + 进度条可拖;✅ 导出 mp4 有声 + 与画面同步。音频端到端**真正打通**。

**顺手退役 spike harness**(`5e7046f`+`6413f37`):删 `app.tsx` + Shell 的 Hub/harness 切换(Shell 直渲 Hub)+ 窗口/页面标题去 "substrate spike"。**保留** `src/renderer/harness/*.ts`(headless 测试夹具,`subtitle.test.ts` 在用)。未清(可选,非必须):`electron/main.ts` 的 `vc-media://spike/` scheme + `spike-assets/` 合成片生成脚本——只服务已退役 harness 演示,测试夹具不依赖真实媒体,要彻底无残留可一并删。

**下一步(下轮可选,均非阻塞)**:
1. ~~补装配器音频契约测试(防 lost-edit 复发,低成本)。~~ ✅ 续 17 已做。
2. 清 `spike` scheme + `spike-assets/`(彻底去 harness 残留)。
3. 音频打磨:音量 UI / 多音轨混音 / 转场(用户暂缓)。
4. 回主线"substrate → 产品化":sidecar 写操作面 / 真 UI 壳深化(见续 7 末四轨)。

---

## ▶ 续 17(2026-05-31,装配器音频契约测试 — 防 lost-edit 复发)

续 16 末点名的「装配器音频轨无契约测试」补上。两条 OTIO 装配器(`creations/clip/assemble.ts` + `creations/news_desk/assemble.ts`)各加一条断言:timeline 必须含 audio 轨(`tracks[1].kind==='audio'`)+ `resolveAudioSegments(tl)` 恰好 1 段、mediaRef/输出窗/源 in-point/gain 全对。这正面钉死了续 16 三次 lost-edit 的病根——此前测试只**绕开**音频轨(注释 `[video, audio, ...overlays]` 直接取 `tracks[2]`),从不断言它存在,所以哑掉也全绿。

- clip 测 10→12,news_desk 测 7→8;**全套 120 测全绿 + typecheck 干净**(`cd desktop && env -u ELECTRON_RUN_AS_NODE pnpm exec vitest run / tsc --noEmit`)。
- **下一步**=续 16 剩余非阻塞项(清 spike 残留 / 音频打磨 / 回主线产品化)。

---

## ▶ 续 18(2026-05-31,清 spike harness 残留 — 纯死代码清除)

续 16 退役了 spike harness(Shell 直渲 Hub),但脚手架还留着。本轮纯死代码清除(零行为变更):
- `spike-assets/`(合成测试片生成器 + mp4)+ `main.ts` 的 `vc-media://spike/` 分支 + `spikeAssetsDir`。
- `spikeMediaUrl()`(preload + global.d.ts,无调用方)。
- `vc:writeExport` / `exportDir`(Spike C 导出 sink,已被走 `vc:writeFile` 的真导出路径取代,见 `ExportTab.tsx`)。
- `harness/multiSegment.ts`(孤儿 Spike A 夹具,无导入方);**保留** `demoTimeline.ts` + `subtitle.test.ts`(活夹具)。
- `.gitignore` 的 spike-media 段;顺手刷新 main.ts/preload.ts 两处已失真的 header(还写着"无 sidecar/IPC")。

验证:**120 测全绿 + 两 typecheck rc=0 + `electron-vite build` 成功**(main/preload/73 renderer 模块)。

**下一步**=续 16 剩余:音频打磨(音量 UI / 多音轨 / 转场,用户暂缓)/ 回主线"substrate → 产品化"(sidecar 写操作面 / 真 UI 壳,见续 7 末四轨)。

---

## ▶ 续 19(2026-05-31,回主线产品化:news_desk 迁新架构 — 第 1 步 Python 业务面)

回主线「substrate → 产品化」。下一大块 = **news_desk 工作台迁新架构**(镜像已完成的 clip),证明公共组件库 + 新架构 RPC 面覆盖多插件。先做**最底、纯可单测、无 GUI 的 Python 业务面**(clip 的完整模板见 `src/creations/clip/{config,component_defs,preview,export,presets}.py`):

**已落地(Python only,零 TS / 零引擎改动)**:
- `creations/news_desk/config.py` — `NewsDeskInstanceConfig` 补齐单一所有者的 mutation 面(镜像 clip):`_ensure_unique_ids`(load 时修 Tk 时代无 id / 重复 id)+ `apply_patch`(news_desk 只 `preset_name` 可 patch——全源渲染无 reframe 几何)+ `addable_kinds` + `add/remove/move_component`。
- `creations/news_desk/component_defs.py`(**新,纯 headless**)— addable kinds(chapter 单例 + subtitle/text_wm/image_wm 多例,镜像 components/__init__ 注册序)+ default instances。**一处刻意偏离 Tk specs**:subtitle/text_wm 的字号/描边发 canonical 分数形(`fontsize_pct`/`stroke_pct`,非 Tk 的绝对 px `fontsize:28`),与已合并的 TS 层(`creations/news_desk/types.ts` + `mapping.ts`)对齐;默认值是 1080p 基线换算(28/1080≈0.026),视觉不变。Python 渲染路径不读这些视觉字段(GPU 合成器在 renderer 读),故此形变对 sidecar 透明。
- `creations/news_desk/__init__.py` — 注册 `config_owner_cls=NewsDeskInstanceConfig`(`preview_provider`/`render_provider` 暂不接,见下)。base RPC 层 ADR-0004 泛型解析,**零硬编码 plugin 名**,所以 component/config 全 RPC 面立即可用。
- `tests/core_rpc/test_creation_news_desk.py`(**新,13 测**)— load/id 修复/add(canonical 形)/unique id/update/remove/move/addable(chapter 单例)/update_config(preset_name)/**deferred 显式钉死**(presets + preview provider 未接 → 优雅 error 非崩)。

验证:**core_rpc 83 测全绿(含 news_desk RPC 16);news_desk 业务面 25 测(config 9 + creation RPC 16)standalone 全绿**。全套 `pytest tests/ -p no:cacheprovider` = **401 passed / 5 failed**(406 collected);那 5 个失败**全是先于本改动即存在的**(worktree 比对 HEAD~1 同样 5 failed,`FFFFF.`),与 news_desk 无关:`test_golden_text_watermark_drawtext` + `test_golden_hook_outro_drawtext`(golden CRLF/本环境 tmp `claude/` 路径)、`test_pr4_timeline_render_e2e` 两条(stale `set_timeline` bridge 调用名)、`test_clip_config::test_load_full_roundtrip`(clip 自己的 stale id 期望)。本改动 **0 新失败**。详见 [[project_pytest_preexisting_failures]]。

> **⚠️ 自查教训(本轮踩坑,两次)**:① 首次提交(`9ca48a0`)是**假绿**——测试 fixture 调 `methods.load_plugins()` 期待注册 news_desk,但 `load_plugins()` 当时只 import `clip`+`news_video`,**漏 import news_desk**;测试单跑时 news_desk 根本没注册(10/12 fail),只因全套里别的测试先 import 进 `sys.modules` 才偶然过。**这是真生产 bug**:sidecar 永远看不到 news_desk。修 = `core_rpc/methods/__init__.py::load_plugins` 补 `import creations.news_desk`(`344dcc4`)。② 多次在没读到完整 summary 尾行时就报数(误报过 "525"/"520"/"524 passed / 1 failed"),真值是 **401 passed / 5 failed**(406 collected)。教训:新测试文件必须**单独**跑(`pytest <file>`)确认不靠 suite 污染;声称通过前必须读到字面 `N passed, M failed` 尾行。

**下一步(news_desk 迁移剩余,按依赖序)**:
1. **preview/render providers**(`preview.py` + `export.py`)——news_desk 是**per-chapter**(clip 是 per-candidate);章节来自 source 的 `analysis.json`(见 [[project_chapters_architecture]]),全源渲染无 reframe。接上后 `preview_data`/`plan_render`/`commit_render`/`delete_render` RPC 立即通。
2. **preset RPC**——`presets.py` 已存在但 builtins 仍是 legacy 绝对-px 形(`fontsize:28`);要么 canonicalise builtins 成分数形,要么 apply 时转。**当前刻意 deferred**(测试已钉死会 error)。
3. **TS workbench**(`desktop/src/renderer/workbenches/news_desk/`)——克隆 clip 工作台结构,但:无 per-candidate 裁剪(全源)、加章节编辑 tab、per-chapter 导出;注册进 `workbenches/index.tsx`(现 fallback「尚未迁移」)。
4. Tk news_desk 退役 → `component_defs.py` 与 `components/*` Tk specs 合并为单一源。

> **续 19 第 1 项(preview/render providers)已于续 20 完成**,见下。

---

## ▶ 续 20(2026-05-31,news_desk 迁移第 2 步:preview + render providers)

接续 19,把 news_desk 的 **preview_provider + render_provider** 补上(镜像 clip 的 `preview.py`/`export.py`,但适配 news_desk 的**全源**模型——无候选切片)。**Python only,零 TS/引擎改动。**

**已落地**:
- `creations/news_desk/preview.py`(新)——`preview_data(project, instance_id)`:经 `materials` 注册表 `instance_factory` 解析绑定素材(零硬编码名 ADR-0004),返回 `{mediaRef(源视频路径), durationSec(来自 source meta,headless 不跑 ffprobe), subtitlePaths(各 subtitle 组件快照 SRT 的绝对路径,以组件自身 srt_path 为 key,即 TS `cuesBySrtPath` 的 key;只发磁盘上真存在的)}`。**章节不返回**——chapter 组件的 `schedule` 创建期已快照进 config,随 load_config 走。
- `creations/news_desk/export.py`(新)——provider 三连 `plan_render`/`commit_render`/`delete_render`。news_desk 渲**单个全源输出**(out_idx 恒 1,src_idx 不用),区别于 clip 的逐候选列表;`plan_render` 返回单个 `output.mp4` 的 mediaRef+路径+时长;`commit_render` 写 `output.json` sidecar + 记 `rendered[]`;`delete_render` 删文件清 `rendered[]`。
- `creations/news_desk/config.py`——加 `rendered: list[dict]` 字段(load+save),持久化单输出渲染态。
- `__init__.py`——接上 `preview_provider` + `render_provider`。
- 测试 `tests/core_rpc/test_creation_news_desk.py`——加 preview(绑定→media+快照 SRT / 未绑定→空)+ render(plan 单输出 / commit sidecar+rendered+事件 / delete 删文件清空)5 条。

**刻意 deferred(写在 export.py docstring)**:legacy Tk 的「渲完按章节切 mp4 + 写 publish sidecar/transcript」是 **publish 侧 ffmpeg 产物(非 GPU 渲染)**,归 `tools/news_desk/publish.py`,不进 core render-state owner。

验证(读字面 summary 行):**news_desk RPC 16 测 standalone 全绿;news_desk config 13 测全绿;core_rpc 72 测全绿**。已提交 `7f97d12`(preview)+ `9c9bf7a`(render),均已推 origin。

**下一步(news_desk 迁移剩余)**:① TS workbench(`desktop/src/renderer/workbenches/news_desk/`,注册进 `workbenches/index.tsx`)② preset RPC(presets.py builtins 绝对-px→分数形)③ Tk news_desk 退役。其中 TS workbench 是用户能看见的下一块。

---

## ▶ 续 21(2026-05-31,news_desk 迁移第 3 步:TS workbench — Style + Export tab)

接续 20,补 renderer 侧工作台,使 Hub 对 news_desk 不再显示「尚未迁移」、点开即真编辑器。仿 Tk `news_desk_tool.py`,但**两 tab**(非 clip 的三 tab)——news_desk 渲全源无候选,故无「候选」tab,只 样式 / 导出。

**已落地**(`desktop/src/renderer/workbenches/news_desk/`):
- `NewsDeskWorkbench.tsx` —— 壳:持组件列表 + `update_component` patch 路径,镜像 ClipWorkbench(tab 首访挂载、保活)。
- `StyleTab.tsx` —— 组件管理器([+ 添加]/删除/↑↓,chapter 单例 gating)+ 复用 clip 的通用 `PropertyPanel`(组件无关)。全程走 `creation.*` RPC(base 层 creation-agnostic, ADR-0004)。友好 kind 文案,不露内部名([[feedback_user_facing_naming]])。
- `ExportTab.tsx` —— 只读渲染计划(单 `output.mp4` + 时长)+ config 的 `rendered[]`,tab 激活时刷新。
- `index.tsx` —— 注册 `news_desk → NewsDeskWorkbench`。

**刻意 deferred(写进文件 header)**:① 实时 GPU 源预览 ② 真渲染触发(`buildNewsDeskTimeline → engine → encode → vc:writeFile → commit_render`)③ chapter 嵌套排期/样式编辑。这些只能真机跑验,故与验证一起落,不作未测 UI 先塞。

验证:**两 typecheck rc=0;120 TS 测全绿;`electron-vite build` 成功(76 模块,原 73)**。已提交 `9069e94`,推 origin。**真机工作台交互待人验**(`env -u ELECTRON_RUN_AS_NODE pnpm dev`,开 news_desk 创作)。

**下一步**:① **真机验** news_desk 工作台(组件增删改、Export 计划显示)② 真渲染管线(整源合成→编码→写盘,镜像 clip ExportTab)③ preset RPC(presets.py builtins 绝对-px→分数形)④ Tk news_desk 退役。

---

## ▶ 续 23(2026-05-31,补「新建创作」入口 — sidecar 只读缺写操作)

真机验时用户反馈「没有地方新建或者打开」创作。**续 22 我误诊**(以为 Hub 没渲染工作台)——其实 Hub 一直渲染工作台、也把已有创作实例列成可点按钮,**「打开」本就能用**。真因:新架构 sidecar 只暴露**只读** project RPC,**没有 `create_creation_instance`**,故全新项目「创作」区只显示「无创作」、无可点项,也无处新建。

修(端到端):
- **后端** `core_rpc/methods/project.py`:`project.list_creation_types`(返回注册类型 + 用户向描述,不露 type_name [[feedback_user_facing_naming]])+ `project.create_creation_instance(type, name?)`(name 省略=自动编号 `suggest_instance_name`;写空 config.json,单一所有者首次编辑时填;发 `event.creations.changed`;经 registry 解析零硬编码名 ADR-0004)。
- **前端** `ipc/client.ts` 加两个 stub + `CreationTypeInfo`;`hub/Hub.tsx` 在「创作」标题旁加 `[+]` 菜单(按描述列类型,选中即建+开工作台),空态改「无创作 — 用「+」新建」。
- **测试** `tests/core_rpc/test_dispatch.py` +5(列类型/自动命名+事件/显式名写 config/未知类型/重名)。

验证:test_dispatch standalone **21 passed**;core_rpc **77 passed**;app+node typecheck rc=0;120 TS 测;`electron-vite build` 77 模块。**真机点击流程仍待用户验**。

**真机重验步骤**:重启 dev(`desktop/dev.ps1`)→ 开项目 → 「创作」标题旁点 `[+]` → 选「新闻/演讲/发布会成片…」→ 应建出 news-1 并自动打开两-tab 工作台 → 测组件增删改 + 导出计划显示。

---

## ▶ 续 24(2026-05-31,news_desk 样式 tab 实时预览 — 全源,无裁剪框)

用户真机反馈「界面功能残缺不全,没有预览」。补样式 tab 的实时合成预览(全源模型,clip CropPreview 的精简版——同引擎编排,无裁剪框)。

- `useNewsDeskPreview.ts`(新)——加载源路径(`material.get_artifact "source"`)+ 时长 + 各 srt_path 快照 SRT(`creation.preview_data`),解析成以组件 srt_path 为 key 的 cues。镜像 clip useClipPreview 的无候选/无裁剪版。
- `NewsDeskPreview.tsx`(新)——全源 canvas 预览,复用引擎层(Backend + ClipReader + AudioReader/AudioPlayback + canvas2D overlay + resolveFrameAt)+ `buildNewsDeskTimeline`,preview≡render 单 compositor。overlay 铺满整帧(无 reframe 裁剪);transport=播放/暂停+拖动,音频主时钟(wall-clock fallback)。源按 srcPath 开一次,组件实时编辑只 rebuild timeline 不重起 WebGPU。StrictMode 双挂载防护同 CropPreview。
- `StyleTab.tsx`——预览放在组件管理器上方,loading/nobind/nosrc/error 状态同 clip。

验证:app+node typecheck rc=0;120 TS 测;`electron-vite build` 80 模块(原 76)。**真机画面 + 播放待用户验**(GPU 预览 headless 覆盖不到)。已提交 `6960c4a`。

**下一步**:① 真机验预览(画面/字幕/章节条/播放有声)② 导出渲染按钮(整源合成→编码→writeFile→commit_render,镜像 clip ExportTab,用户选「先预览后导出」)③ preset RPC ④ Tk 退役。

---

## ▶ 续 25(2026-05-31,news_desk 真机反馈三修:字幕导入 + 章节导入 + 字幕自适应宽度)

用户真机验:画面/字幕/水印有,但三处缺:① 字幕组件要能选字幕导入 ② 章节组件要能选章节导入 ③ 字幕自适应宽度没做。

**问题3(自适应宽度,commit `3bb44c4`)**:`subtitle.compile` 仅当 `ctx.frameAspect` 有值才单行 fit;`buildNewsDeskTimeline` 从没传 → news_desk 字幕不换行。修:装配器加可选 `frameAspect`(全源=源宽高比),`NewsDeskPreview` 传 `srcW/srcH`。

**问题1+2(导入,与本节同提交 `059127d`——独立 feat 提交因 cwd bug 取消,见下「过程坑」;用户选「只从素材选」)**:新增 **import_provider**(沿用 preview/render provider 模式,base 层 ADR-0004 泛型派发):
- `CreationType.import_provider` 字段;`creations/news_desk/imports.py`:`list_imports → {subtitleLangs, analyses}`;`import_resource(component_id, params)` 快照进组件 + 单一所有者持久化。`{kind:subtitle,lang}` 把素材 `<lang>.srt` 拷进 `<instance>/subtitles/<id>.srt` 设 srt_path;`{kind:chapters,filename}` 从 analysis.json 填 chapter schedule。忠实 Tk `_import_srt`/`_import_from_analysis`,经 registry 取素材零硬编码名。
- `core_rpc/methods/creation.py`:`creation.list_imports` + `creation.import_resource`。
- `ipc/client.ts` 两 stub;`StyleTab.tsx` 在属性面板上方加 `ImportRow`(字幕→语言选择器;章节→分析文件选择器;带已导入/未导入/已导入 N 章状态 + 空态提示)。

验证:news_desk RPC **21 测** standalone;core_rpc **85 测**;app+node typecheck rc=0;**120 TS 测**;build 80 模块。**真机导入点击 + 字幕换行待用户验**。

> **过程坑(本会话第 N 次)**:第一次提交导入功能时,shell 工作目录黏在 `desktop/` 致 `git add` 路径翻倍失败、**整批被取消**——`imports.py` 等文件根本没写成,只有问题3 的两文件落地。我一度起草了「24/85 passed、含导入功能」的 commit message(假的,幸亏被取消)。后重建全部导入代码并真验。教训:① git 操作从 repo 根用绝对/明确路径,别靠 shell cwd;② 提交前 `git status` 核对实际 staged 文件,别凭记忆写 message。

**外部文件导入**(磁盘选 SRT)本轮刻意未做。**下一步**:① 真机验(导入字幕→预览出字幕;导入分析→章节条/卡出现;长字幕单行不溢出)② 导出渲染按钮 ③ preset RPC ④ Tk 退役。

---

## ▶ 续 26(2026-05-31,修章节不显示 — data-key + 几何不匹配)

用户:字幕双语 + 自适应宽度正常,章节导入成功(已导入 3 章)却**预览不显示**。**真因不是 kind 缺失**(`topic_strip`/`chapter_hero_card` 早在 `OVERLAY_KINDS` 里)——是 **data-key + 几何不匹配**:`drawOverlayClip` 读 `clip.data["text"]` 且空则 bail,但 chapter 组件发的是 `data.topic_text`(条)和 `data.title`/`data.body`(卡),且需要顶部条带/侧栏面板而非通用居中文本路径。

修(commit `3d8f254`):
- `canvas2d.ts`:专用 `drawTopicStrip` + `drawHeroCard`,在通用文本路径前派发。条=整宽顶部条带(height_pct)+ `data.topic_text` 左缩进标题;卡=左锚半透明面板 + 屏缘 accent 条 + 标题 + 正文,按面板宽 char-wrap(CJK 安全)。几何常量镜像 `core/composition/primitives/{topic_strip,chapter_hero_card}.py`;章节字号是 1080 基线绝对 px(组件保留 legacy 绝对值),故按 h/1080 缩放保 preview≡export。**单一 overlay 路径,导出也会画章节。**
- `chapterDraw.test.ts`(新,4 测):kind 认识 / 条从 topic_text 画 / 卡从 title+body 画 / 空条+卡跳过。**起草时第一版用错 data key(text/refined/keyPoints)致 2 测失败,已改为组件真发的 key。**

验证:app+node typecheck rc=0;**124 TS 测**;build 81 模块。**真机章节条/卡待用户验**。

> 过程:首次 Edit canvas2d.ts 没匹配上(我臆想了文件结构,实际它已有 OVERLAY_KINDS 且 drawOverlayClip 单函数),silently 失败 → 测试反而帮我暴露真因(data-key 不匹配)。

**下一步**:① 真机验章节条/卡 ② 导出渲染按钮 ③ preset RPC ④ Tk 退役。

---

## ▶ 续 27(2026-05-31,章节属性编辑器 — 嵌套 modes + style)

用户:章节条/卡都显示了,但**章节属性面板只有 name**,真正设置看不到。真因:章节 config 是嵌套(`modes`/`style.top_strip`/`style.start_card`/`schedule`),通用 `PropertyPanel` 只渲染 primitive 字段,全跳过了。

修(commit `a9f7c79`):
- `ChapterProperties.tsx`(新)——专用编辑器:两层开关(顶部章节条/起始大卡片)+ 各启用层的样式字段(条:背景/文字色 + 字号;卡:标题/正文色+字号、背景色+不透明度、强调色、持续秒数)。中文标签,不露内部名。
- `chapterPatch.ts`(+测 4)——纯 patch 构造器。`update_component` 是 shallow-merge,故编辑一个嵌套字段要**重发整个嵌套对象**(`patchStrip` 保 start_card、`patchCard` 保 top_strip、`patchMode` 保另一 mode);partial/空 style 用默认补全。钉死 shallow-merge 丢 sibling 陷阱。
- `StyleTab.tsx`:章节渲 `ChapterProperties`,其它组件仍用 `PropertyPanel`。

排期(逐章 rows)仍来自 analysis.json 导入(ImportRow);逐章编辑待后续。

验证:app typecheck rc=0;**128 TS 测**(124+4);build 83 模块。**真机编辑待用户验**。

**下一步**:① 真机验章节属性编辑(开关层、改色/字号→预览实时变)② 导出渲染按钮 ③ preset RPC ④ Tk 退役。

---

## ▶ 续 28(2026-05-31,news_desk 迁移进展盘点 + 三项待办)

news_desk 迁新架构(Electron renderer + sidecar)已走通**绝大部分**,真机逐项验过。本节盘点已完成 + 用户指出的剩余缺口,作为接力点。

### 已完成并真机验过(续19~续27)
- **Python 业务面**:config 单一所有者(增删改组件 + `_ensure_unique_ids`)、`component_defs.py`(headless 默认实例)、注册 `config_owner_cls`。修了真 bug:`load_plugins` 漏 import news_desk(续19,`344dcc4`)。
- **providers**:`preview.py`(全源 media + 时长 + 各 srt_path 快照 SRT)、`export.py`(plan/commit/delete,单全源输出)、`imports.py`(import_provider:字幕/章节从素材导入)。
- **create-creation 流程**:`project.list_creation_types` + `create_creation_instance` + Hub `[+]` 菜单(续23,`5089c56`)——之前新架构根本没法新建创作。同轮发现 **Hub 一直能渲染工作台**(续22 误诊已纠正)。
- **TS 工作台**:两 tab(样式/导出)、组件增删改排序、注册进 Hub。
- **实时预览**:`NewsDeskPreview`(全源 canvas,复用引擎层 + `buildNewsDeskTimeline`,preview≡render;播放/拖动/音频主时钟)。**真机验:画面+双语字幕+水印+章节条+章节卡全部显示正常。**
- **字幕自适应宽度**:装配器传 `frameAspect`,长字幕单行自动切多条(续25,真机验过)。
- **导入(快照,非引用)**:字幕 `shutil.copyfile` 进 `<instance>/subtitles/<id>.srt`;章节 `read_analysis` 把行拷进 `schedule`。**已核对:两者都是快照、数据落进 creation 自己目录/config,符合 ADR-0003 快照约定,非引用上游。**
- **章节图元绘制**:canvas2d 加 `drawTopicStrip`/`drawHeroCard`,真因是 data-key 不匹配(`topic_text`/`title`/`body` vs `text`)(续26,真机验过条+卡)。
- **章节属性编辑器**:`ChapterProperties`(嵌套 modes/style 编辑,shallow-merge 安全 patch 构造器)(续27)。
- 测试:core_rpc 85+;TS 128。每步 typecheck/test/build 三绿。

### ⚠️ 用户指出的三项剩余缺口(下一轮做)
1. **详情列表缺失**(功能不完善):
   - **字幕详情列表**:legacy Tk subtitle 属性面板底部有只读 cue 列表(start/end/text Treeview,点击 seek 预览)。新架构 StyleTab 字幕组件**没有**。需:`preview_data` 已返回 SRT 路径,host 已 parse cues(`useNewsDeskPreview` 的 `cuesBySrtPath`),把对应组件的 cues 列出来即可(参考 clip ClipDetailPanel 的 cue 列表)。
   - **章节详情列表**:章节的 `schedule`(逐章 start/end/title/refined/key_points)目前只能整体导入,**面板里看不到也不能逐章编辑**。需:列出 schedule 行(至少只读 + 点击 seek;编辑是更后)。
2. **快照 vs 引用约定核查**:本轮已核对 news_desk 导入路径=快照(见上「导入」条),**符合约定**。但用户要求系统性检查——**待办**:确认 preview.py / export.py / 渲染路径全程只读 instance 内快照,不回头引用素材(preview.py 看着是对的:从 `inst_dir` 解析 srt_path;但需通读一遍 export 渲染链确认无 material 直引)。
3. **导出功能未实现**:导出 tab 目前**只读显示渲染计划 + rendered[]**,**没有真渲染按钮**。需:镜像 clip ExportTab 的渲染循环(`buildNewsDeskTimeline → GPU 引擎逐帧 encode → vc:writeFile 写 output.mp4 → commit_render`),全源单输出。后端 `plan/commit/delete_render` 已就绪,缺 renderer 侧的编码触发 + 进度/取消 UI。

### 其它已知欠债(非阻塞)
- preset RPC 未接(presets.py builtins 仍 legacy 绝对-px 形)。
- Tk news_desk 未退役(`component_defs.py` 与 Tk `components/*` 双源待合并)。
- 字幕组件属性仍用通用 PropertyPanel(扁平字段 OK);若要双语并排/语言切换等可后续。
- `imports.py:91` 一行死注释待清。
- 外部文件导入(磁盘选 SRT,非素材)未做。

**下一轮建议顺序**:① 字幕+章节详情列表(功能完整性,ROI 高)→ ② 导出渲染按钮(端到端可用)→ ③ 系统核查快照约定 → ④ preset / Tk 退役。

> **续29 已做完 ①②③**,见下。

---

## ▶ 续 29(2026-05-31,续28 三项缺口 ①②③ 一次性收口)

接续 28 推荐序,把用户指出的三项缺口前三个做完(Python 零改动,纯 `desktop/` renderer + 一处 hook)。

**① 字幕 + 章节详情列表(commit `21c5aa3`)**:Style tab 通用 `PropertyPanel` 渲不了 legacy Tk 的 cue 列表 / 章节 schedule。新增 `ComponentDetail.tsx`(`SubtitleCueList` + `ChapterScheduleList`)——选中字幕组件显示其快照 SRT 的 cue(start·text,key 取自 live 预览的 `cuesBySrtPath`);选中章节显示导入的 schedule 行(start·title)。两者**点击行 seek 预览**:news_desk 全源(identity time map),cue/章节的源时间起点≡输出时间位置,直接 seek 即对。`NewsDeskPreview` 经 `useImperativeHandle` + 可选 `controlRef` prop 暴露 `seek(sec)`(保留 plain function 形,不引 forwardRef 致全 body 重缩进)。逐章编辑仍 deferred(续28 只要求只读+seek)。

**② 全源导出真渲染(commit `25f48af`)**:导出 tab 之前只读(plan + rendered[])。镜像 clip ExportTab 渲染循环,但单全源输出:`plan_render → 开源+Backend/ClipReader → buildNewsDeskTimeline → exportTimelineToMp4(GPU/WebCodecs + 源音频混流)→ vc:writeFile → commit_render`。target=源尺寸(取偶)、无 reframe 裁剪、out_idx 恒 1。与 Style tab 预览**同一 compositor**(buildNewsDeskTimeline→resolveFrameAt),导出 mp4≡预览。带进度%/取消/单输出 播放·打开文件夹·删除。`useNewsDeskPreview` 加 `reload()`(全量重取)让导出 tab 在 Style tab 导入后刷新源+快照 cue;`NewsDeskWorkbench` 现把 live `components` 传给导出 tab。

**③ 快照 vs 引用约定系统核查(无代码改动,结论:全合规)**:通读 `imports.py` / `preview.py` / `export.py` / renderer `ExportTab` 全链路——
- `imports.py`:字幕 `shutil.copyfile` 进 `<inst>/subtitles/<id>.srt` 设相对 `srt_path`;章节 `read_analysis` 一次性拷进 `component["schedule"]`。**均快照,无回引**。
- `preview.py` / `export.py`:**唯二的 material 引用 = 源视频路径(`model.source_video_path`)+ 源时长 meta**——这是**输入媒介**(不是可快照的决策,多 GB 视频本就不入快照),正确保留为引用。字幕走 inst_dir 相对解析(快照),章节 schedule 随 config(快照),无决策性数据在渲染期回引素材。
- renderer `ExportTab`:`srcPath` 经 `material.get_artifact("source")`(源媒介引用)、`cuesBySrtPath` 经 `creation.preview_data`(实例快照 SRT)、`components` 来自 config(快照)。timeline 全在 renderer 建,无 material 直引决策。
- **结论:符合 ADR-0003 / [[project_snapshot_principle]]——决策性上游创建期快照,原始媒介保持引用。零违规,无需修。**

验证(每步):**两 typecheck rc=0;128 TS 测;`electron-vite build` 成功(83 模块)**。

**真机验待用户**(GPU 预览 seek + 真导出 mp4,headless 覆盖不到):
- 续 29-①:选字幕组件→底部出 cue 列表;选章节→出 schedule 列表;点行→预览跳到该时间。
- 续 29-②:导出 tab 点「渲染整源」→进度走完→`output.mp4` 落 instance 目录、有画面+字幕+章节+音频、与预览一致;播放/打开文件夹/删除可用;取消能中断。

**下一步(续28 剩余)= ④ preset RPC(presets.py builtins 绝对-px→分数形)+ Tk news_desk 退役(`component_defs.py` 与 Tk `components/*` 合并单源);非阻塞欠债:字幕双语并排 UI、外部文件导入、`imports.py` 死注释清理(行号已随改动漂移,核查时未见明显死注释)。**

> **续30 已做完 ④(preset RPC + Tk news_desk 退役)**,见下。

---

## ▶ 续 30(2026-05-31,task ④:Tk news_desk 退役 + preset RPC — 用户拍板「现在就退 Tk」)

续28 的 ④ 两半(preset 规范化 + Tk 退役)**强耦合**:presets.py builtins 是 legacy 绝对-px 形**正因为 Tk ffmpeg 渲染路径要它**,直接规范化会炸还在 ship 的 Tk news_desk。用户决策(AskUserQuestion)= **现在就退 Tk news_desk**(最干净 end-state,pre-alpha no-legacy)。分 4 个提交:

**Commit 1 `21c5aa3`...** — 见续29(本节是续30,提交从下面起)。

**Commit `<decouple>`:clip 拿走 Tk 组件框架(解 clip→news_desk 跨插件耦合)** — 共享 Tk-era 框架(`ComponentSpec`/`ImportSource`/`ProjectContext`)原住 `news_desk/components/__init__.py`,被 clip Tk(`style_panel` + `components/{hook_outro,subtitle,watermark}` + `components/__init__`)跨插件 import。news_desk 新架构根本不用它们 → clip(唯一存活 Tk 消费者)本地定义之。纯 dataclass 平移(零行为变更);留 clip 不进 core(Tk 脚手架,随 clip Tk 一起死)。

**Commit `<retire>`:删 Tk news_desk** — 删 `news_desk_tool.py`(NewsDeskApp)+ `components/*` Tk specs + `publish.py`(Tk 期 md 渲染器;新架构 publish 已 defer 到 `tools/news_desk/publish.py`);从 VideoCraftHub 注销 news-desk(TOOL_MAP + 注册 import + project_only);**`component_defs.py` 成为 addable kinds + 默认实例的单一源**(解「双源」债)。退役 legacy Tk-render-path 测试(`test_news_desk_compile`/`test_pr4_timeline_render_e2e`——测已删的 compile→overlay 路径,pr4 本就是 pre-existing 失败)。重写 `test_arch_news_desk`:删 Tk-tool/component-spec/publish 检查,保留存活不变量(注册/新架构 providers 接上/headless-无-tkinter/解耦/core 不 import news_desk),新增「news_desk 全程零 tkinter」强不变量。`test_clip_components` 改用 clip-local 框架。

**Commit `<presets>`:preset RPC + 规范化 builtins** — `_*_component` 工厂改为从 `component_defs.default_instance(kind)` + 样式覆写构建(preset 永不漂离 live 组件形;字号/描边走 canonical 分数 `fontsize_pct`/`stroke_pct`/`text_fontsize_pct`,非绝对 px)。`NewsDeskInstanceConfig` 加 `list/apply/save/delete_preset`(单一所有者;base RPC 泛型解析 ADR-0004;news_desk 无 output 几何 → preset 纯组件列表,apply 整列替换 + kind-based 重 unique id)。core_rpc deferred 测试翻成真覆盖(list/apply/unknown/save+delete 含 builtin 保护,store 重定向 tmp)。

**Commit `<ui>`:StyleTab preset 工具栏** — 镜像 clip preset 工具栏(去掉 output 几何控件):预设下拉 + 应用/另存为/覆盖/删除,builtin 防覆写/删除。apply 替换组件列表 + 清选择 + `preview.reload()`(preset 清 srt_path,缓存 cue 要刷)。

**验证**:Python 全套 `pytest tests/` = **375 passed / 3 failed**(3 全 pre-existing:2 golden CRLF/tmp `claude/` 路径 + `test_clip_config::test_load_full_roundtrip` stale id;**0 新失败**;且退役 dead 测试顺带消掉了 2 个 pre-existing pr4 失败)。news_desk presets + core_rpc 45 测 standalone 全绿。desktop **两 typecheck rc=0 / 128 TS 测 / electron-vite build(84 模块)**。Tk hub `py_compile` 通过;news_desk 包 headless import 通过(`creations.get('news_desk')` 仍注册,新架构 sidecar 经自己 load_plugins 注册不受影响)。

**真机验待用户**:① clip Tk app 仍正常(框架平移后)② news_desk 工作台 preset 下拉应用/另存/删除 → 组件列表换、预览实时变。

**承重决策**:框架 dataclass 落 clip-local 非 core/——它们是 Tk-era 脚手架(新架构用 TS component contract),随 clip Tk 退役一起死,不该进 core 永久层再删一遍(pre-alpha no-legacy + [[feedback_no_universal_standard]] 每插件自持)。这覆盖了「ComponentSpec 搬 core」旧债——前提(两活插件共享)已失效,改判 clip-local。

**news_desk 迁新架构(Electron + sidecar)至此=功能完整**:create/preview/export/imports/detail-lists/chapter-editor/presets 全通,Tk 侧退役。剩非阻塞:字幕双语并排 UI、外部文件导入、逐章 schedule 编辑、`tools/news_desk/publish.py` 新架构 publish(defer)。**clip Tk 仍在**(本轮只退 news_desk Tk);clip Tk→Electron 是独立后续。

---

## ▶ 续 31(2026-05-31,真机 dogfood 一串 bug 修复 + 素材侧缺口定性)

续30 后用户真机 dogfood news_desk,逐个报 bug,逐个修(均 land 推 origin)。按时间序:

| bug | 真因 | 修 |
|---|---|---|
| 另存为按钮无效(报 `prompt() is not supported`) | Electron 渲染进程不实现 `window.prompt` | 内联名称输入框(news_desk + clip StyleTab 都改);`9...`/`ac9d3d3` 系列 |
| 应用预设预览黑屏(其一) | `onApplyPreset` 的 `preview.reload()` blank 了 data→预览 unmount→重挂 WebGPU backend 黑屏 | `useNewsDeskPreview.reload()` 改**原地刷新**(只 type/instance 变才 blank) |
| 应用预设预览黑屏(其二) | 预设丢 `schedule`,`newsDeskChapterToInstance` 对 `undefined.map` 抛错→整 timeline build 崩→不重绘 | mapping `(c.schedule ?? []).map`;装配器 per-component try/catch(单组件崩不拖垮整 timeline + 视频轨) |
| 图片水印组件被跳过(`imagePath.trim()` 抛错) | 预设丢 `image_path`→mapping 传 undefined→compile `.trim()` 崩 | mapping `image_path ?? ""` + `text ?? ""` |
| 绑定是一次性的 | `BindMaterialRow` 只在 nobind 显示 | 改 `MaterialBindingBar` **常驻持久设置**(显示已绑 + 换绑) |
| 导入字幕不显示 | import 设了 srt_path 但 `cuesBySrtPath`(来自 preview_data)没刷 | `onImport` 调 `preview.reload()` |
| **导入切实例丢数据** | import provider(imports.py)越过 session 缓存 owner **直写 config**→缓存陈旧;`list_components`(切回)返旧组件,且后续 `owner.save()` 覆盖磁盘 | `Session.invalidate_creation` 在 import/commit/delete_render 后调,re-sync 单一所有者([[project_creation_config_owner]]);+回归测试 |
| 导入下拉跨字幕组件联动 | `ImportRow` 内部 choice state 被 React 复用 | `key={selected.id}` 每组件重置 |
| 图片水印无文件选择器/路径配置 | 通用 `PropertyPanel` 只渲染存在的字段且无 browse | `vc:pickImage` IPC + 专用 `ImageWatermarkProperties`(常驻路径行 + 浏览…/清除);PropertyPanel 加 `hide` prop |

**坑(已记 [[reference_electron_run_as_node]])**:bug 修在 sidecar(Python)/主进程(IPC)的,**Ctrl+R 不重载**——必须 `desktop/dev.ps1` 整重启(杀 electron + 清 .vite + 重 spawn sidecar)。bug 1/3/2 同批报来,其中 1(渲染)Ctrl+R 即生效,2(sidecar)/3(主进程)要整重启才生效——一度被误判"没修好"。

**全部真机验过基本正常。** 测试:全套 `pytest tests/` = **378 passed / 3 pre-existing failed / 0 新**;desktop typecheck rc=0 / **130 TS 测** / build。HEAD 已推 origin。

### ▶ 下一大任务 = 素材(material)侧迁新架构(用户点名"素材功能根本没实现")

新架构素材侧**只有只读 RPC**;**没有素材工作台**——创建素材 / 导入源视频 / ASR(字幕)/ 章节分析 / 编辑新闻背景 全部仍只在 Tk。创作侧能消费素材(绑定),但素材本身造不出来。**完整实现路线已写入 `docs/draft/electron-migration-design.md` ★实现进度 末「⚠️ 素材(material)侧」节**(权威):① Project/Material 写 RPC(create_material_instance / add_source_video 长任务)② 分析 kind 作 job(ASR/章节/翻译)③ context 编辑 RPC ④ 素材工作台 UI ⑤ Hub 素材 `[+]`。对齐 §2.2 设计 + 续7 四轨。source 获取/ASR/翻译 按 §0.5 "能力重归素材",顺带消化遗留 menubar 工具。
