# 当前任务 / Current Task

> **不是 backlog。**仅记录"现在正在做什么 + 上次停在哪儿 + 下一步要做什么"，
> 用于会话清理后下一次 Claude 能直接接力。**实现细节不放这里**——放到对应设计文档。

---

## ✅ 当前状态(2026-06-27) = v0.3.7 已发布（TTS 配音）

> 本轮(2026-06-27)：① **切发布 v0.3.7**（PATCH）——版本号三处对齐（`desktop/package.json` 权威 + `pyproject.toml` + `src/__init__.py`，并修了 `__init__.py` 里误导的 "single source of truth" 注释）；yt-dlp 已 latest（2026.6.9）无需 bump；`uv lock` 同步项目版本；pytest 163 全绿。tag `v0.3.7` → CI 绿 → 草稿 Release（双语 notes）→ **已 publish**（2026-06-27 13:31 UTC，<https://github.com/dosmoon/VideoCraft/releases/tag/v0.3.7>）。⏸ 真签名仍 deferred（需证书）。
> ② **新增统一发布单** [`release-checklist.md`](release-checklist.md)：把散在 versioning / packaging §4 / packaging-design §10 的发布步骤合成一份可勾选驱动单（只列 action + 链回权威源），packaging.md §4 加互链。
> ③ 发布内容 = 自 v0.3.6 起的 **TTS 配音套件**（字幕→TTS 配音 + news_desk 音轨 + clip 配音轨 + per-语言/音色多版本 + 原声电平控制）+ 应用内「新建项目」入口 + dub/i18n/desktop 修复。

---

## 📦 上轮(2026-06-11) = v0.3.6 已发布（多语言生成修复）

> 本轮(2026-06-11)：① **文档站上线** <https://dosmoon.com/VideoCraft/>（中英双语 + 双套 UI 截图；发布源=docs/public/，规范见主站 docs-system-plan.md，主站卡片已挂链接）。
> ② **修复章节/热点片段生成语言**（81ba75e）：prompt 加 {output_language} 硬性指令 + lang_iso 穿透 + 陈旧 prompts/ 覆盖文件追加兜底——此前非中文字幕一律生成中文。
> ③ **clip 候选语言改人工决定**（5d224cd + 104dbcb）：样式 tab 绑定行下新增「候选来源」下拉（模仿 news_desk 章节来源）；切换显式确认并清空勾选/覆盖（`clips_overrides_clear`）；快照在先的老实例钉住不漂移。
> ④ **v0.3.6 已发布**（2026-06-11 20:49 UTC，双语 notes，<https://github.com/dosmoon/VideoCraft/releases/tag/v0.3.6>）。⏸ 真签名 deferred(需证书)。

---

## 📦 上上轮（2026-06-10）= docs/ 治理完毕；v0.3.5 已发布

> 本轮(2026-06-10 晚)落地 **docs/ 全面 archive + 重写**（上轮拍板的任务）：
> ① **21 篇过期文档移 [`docs/_archive/`](_archive/README.md)**（design/ 6 篇 Tk 时代：01/03/05/07/10/11；draft/ 13 篇已落地或已废弃：electron-migration-plan / adr-0008-migration-tasks / project-restructure / clip-component-migration / ai-clip-redesign / composition-style / architecture-vision / news-desk-derivative / news_desk-ux-v0.3 / publish-sidecar / chapter-verify-edit / substrate-spike-findings / tech-selection-embedded-ai；原 draft/archive/ 2 篇并入），`_archive/README.md` 给了逐篇归档原因 + 现行替代指引。
> ② **3 篇重写到 Electron 现实**：[`design/00-overview.md`](design/00-overview.md)（入口路标：当前架构图 + ADR 索引 + 文件结构）、[`design/04-ai-router.md`](design/04-ai-router.md)（三档 provider 池 / 6-tab Electron 控制台 / prompt hub 已退役）、[`design/12-i18n.md`](design/12-i18n.md)（renderer tr.ts 530 keys 热切换 + Python 侧 28 keys）。
> ③ 修断链：BACKLOG.md、derivative-snapshot-principle、composition-otio-foundation、electron-migration-design、06-core-layer（顺带清掉其 Tk 残留模块表）+ 3 处代码注释路径。ADR 全部核过：0001~0011 状态准确，0004 已自带 Superseded 注记，无需动。
> 保留现行：design/ 02/06/08/09 + aistack-integration + composition-timeline-v0。
> ④ **draft/ 二次收口（同日晚）**：3 篇现行权威升入 design/（[composition-otio-foundation](design/composition-otio-foundation.md) / [derivative-snapshot-principle](design/derivative-snapshot-principle.md) / [packaging-design](design/packaging-design.md)，后者状态改「已实施」）；electron-migration-design 归档（迁移完成，正文已由 ADR-0008/0010 + 00-overview 承载）。**draft/ 现在只剩 2 篇真草稿**（media-segment-composer=P1 PPT2Video、buffer-publishing）。入站链接（versioning/BACKLOG/desktop README/ir.ts/core_rpc）已同步改。
> ⑤ **BACKLOG 治理（同日晚）**：`BACKLOG.md` 移入 [`docs/BACKLOG.md`](BACKLOG.md) 并大幅精简——已完成项 / 随 Tk 退役失效项（项目工作台 UX、video_tools 下沉、窗口风格、Tab 滚动等）/ 已被现实解决的观察（自建渲染引擎已落地）/ 旧 core/program 节目生成规划 / 暂缓裁决全文，全部拆到 [`_archive/backlog-archive-01_2026-04_2026-06.md`](_archive/backlog-archive-01_2026-04_2026-06.md)（参考 task.md 分卷做法）。顺带修正 06-core-layer 模块表残留死行（burn_subs/burn_presets/tts.py 已删、env 组件实数 8+1）+ prompts.py 过期注释。
> ~~遗留小尾巴：`src/hub_layout.py`~~ 已删（2026-06-10 同日，pytest baseline 对照过）。
> ✅ **v0.3.5 Release 已发布**（2026-06-10 20:07 UTC，notes 重写为双语用户向后 publish，<https://github.com/dosmoon/VideoCraft/releases/tag/v0.3.5>）。⏸ 真签名 deferred(需证书)。
> 旧会话记录见下「📦 已归档历史」。

---

## ▶ 下一任务（新对话先读）= 录播自动剪辑方向（大功能）

> source 加录播 → ASR → AI 全自动剪裁/章节/切废段/过渡；per-品类插件；= OTIO 多段装配的真实需求来源（crop-on-Clip 已落地多段裁剪 IR 地基，见 [ADR-0011](adr/0011-spatial-crop-clip-transform.md)）。记忆锚点 [[project_recorded_autoedit]]。从设计稿起步（放 `docs/draft/`）。

---

## ✅ P3 打包 / CI / 发布（2026-06-10 收口）

> **权威 = [`packaging.md`](packaging.md)（操作手册）+ [`versioning.md`](versioning.md)（版本规则）+ [`packaging-design.md`](design/packaging-design.md)（设计 §8/§9/§10）。**

**CI（GitHub Windows runner）已落地 + 验证绿**：
- `.github/workflows/build-windows.yml`：`workflow_dispatch` + `v*` tag 触发 → setup-uv 冻结 sidecar（`build_sidecar.ps1`）→ 拉 ffmpeg（`fetch_ffmpeg.ps1`）→ pnpm `electron-vite build` + `electron-builder --win`，**CI 就地把 yml 的 `signAndEditExecutable: false` flip 成 true**（本机 yml 默认仍关，CI 才开；**不能用 `-c.win...=true` CLI override**——点号短形式被 yargs 当 config 文件路径 ENOENT，首跑就栽这）→ rcedit 嵌品牌图标 → installer 传 artifact，`--publish never`。
- **首验结果**：run `27191231392` 全绿 4m3s；winCodeSign 被拉下、edit/sign 管线对 `VideoCraft.exe` 跑过（图标内嵌确认生效）；artifact `VideoCraft-0.3.5-setup.exe`（183MB）下载验过 = `NotSigned`（符合预期，无证书）。
- ✅ **build 标识 + CI 端到端验过（2026-06-10, run #3 sha 4c7930c）**：`generate_build_info.ps1` → `build-info.json` 随包（实测包内 `{"build":"3","commit":"4c7930c",…}`）+ Windows FileVersion `0.3.5.3`（BUILD_NUMBER=run_number，经 signAndEditExecutable flip 生效）+ exe 版权 `© 2025-2026 OldApeTalk`。版本号规则见 [`../versioning.md`](../versioning.md)。
- ✅ **Node 20 弃用尾巴已清（run #4）**：action 全升 node24 大版本（checkout@v6 / setup-node@v6 / upload-artifact@v7 / pnpm@v6 / setup-uv@v8.2.0——后者无浮动 major tag 故钉精确）+ `runs-on: windows-2025`（脱离 `windows-latest`）。Node 20 公告消失。**残留 windows 公告**（`windows-2025`→`-vs2026` 镜像 6/15 刷新）纯信息性、任何标签都躲不掉、构建照常绿，不管。
- ⏸ **真签名（Authenticode）deferred**：用户选「先只要图标，暂不签名」。exe 当前 unsigned，SmartScreen 会警告。拿证书后接（方案见 packaging-design §10）。

**▶ 下一大功能候选 = 录播自动剪辑方向**：source 加录播 → ASR → AI 全自动剪裁/章节/切废段/过渡；per-品类插件。见 memory [[project_recorded_autoedit]]。（注：crop-on-Clip 已落地多段裁剪的 IR 地基，见 [ADR-0011](adr/0011-spatial-crop-clip-transform.md)）

**纪律**：[[feedback_pre_alpha_no_legacy]] 不留兼容层；改 Python 整重启 sidecar；每步 build-green（pytest + desktop typecheck/vitest/build）；**冻结态 bug 不能只在 dev 验**（用驱动真 `core_rpc.exe` 的冻结 E2E 复现，见 [[feedback_frozen_bug_repro]]）；**renderer 性能/卡顿 bug 先装探针拿数据再改，整秒级的"慢"先比对代码里的 timeout/budget 常量，renderer 改动必 `dev.ps1` 整重启**（[[feedback_measure_dont_guess_renderer]]）；**Tk→新壳"缺口"恢复前先 grep docs 查是否故意删的**（[[feedback_parity_gap_not_bug]]）；**外部/远端写操作前先只读核对**（[[feedback_external_actions]]）。

---

## 📦 已归档历史

> 已完成会话记录移出本文件，按时间分卷：
> - [`_archive/task-archive-01_2026-05-19_2026-06-05.md`](_archive/task-archive-01_2026-05-19_2026-06-05.md)：FastAPI 传输重构、P3 打包/Tk 退役、续 6~37 OTIO/Electron 迁移史。
> - [`_archive/task-archive-02_2026-06-05_2026-06-08.md`](_archive/task-archive-02_2026-06-05_2026-06-08.md)：三轮 dogfood（点 source 崩 / 60fps 导出死锁 / clip·news_desk 4 项 + 候选页跟随）。
> - [`_archive/task-archive-03_2026-06-08_2026-06-09.md`](_archive/task-archive-03_2026-06-08_2026-06-09.md)：i18n 孤儿清扫 / env-screen 修复 / news_desk 剪裁 + crop-on-Clip 重构（ADR-0011）。
>
> 需要历史背景接力时去那里查；本文件只保留**仍在进行**的任务。
