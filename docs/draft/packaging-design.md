# P3 打包 / 分发设计

> **状态**:草案 / 2026-06-03 · 承接 [`electron-migration-design.md`](electron-migration-design.md)「剩余工作计划」P3 + §3.2 + §7.3
> **前置**:ADR-0008 终态(三插件零插件专属 Python)已达成;P0~P2 + P6 全完成。**当前 = 纯 dev 模式,零分发产物。**
> **决策已锁(2026-06-03 用户拍板)**:① sidecar = **PyInstaller onedir**(非 onefile)② **瘦装包 + 引导下载**。
> **纪律**:Windows-first([architecture-vision §3]);用户数据全部 install-local,绝不 %APPDATA%([[feedback_portable_data]]);非 AI 功能不被下载门槛堵死([[feedback_no_forced_downloads]]);早期=严谨锁定可演化基础([[feedback_early_stage_foundation]]);每步 build-green。

---

## 0. 现状摸底(实测,定方案的依据)

| 事实 | 实测来源 | 对打包的含义 |
|---|---|---|
| **`myenv` = 7.0 GB,严重污染** | `du -sh myenv` | **绝不能整包 ship。** 装了 `requirements.txt` 明令移除/不该有的:`nvidia` 2.0G(CUDA wheels)、`torch` 823M(requirements 明令 DO NOT install)、`sherpa_onnx` 288M(记忆称 2026-05-10 已删)、`onnxruntime`/`wandb`/`pandas`/`pyarrow`/`transformers`/`llvmlite`/`sympy` 等。myenv ≠ requirements.txt。 |
| **`requirements.txt` 才是真实运行时闭包** | 读 | 非 AI 核心:yt-dlp/requests/srt/google-genai/fish-audio-sdk/openai/json-repair/edge-tts/Pillow/pywin32(基本纯 Python + 轻量)。嵌入 AI(opt-in):faster-whisper(CTranslate2 原生)+ llama-cpp-python(CPU 档 wheel,**非 myenv 里那个 785M CUDA 版**)。 |
| **引导下载模式已落地** | `user_data/{runtimes,models}` 存在 + `core/env` + `core_rpc/methods/{env,models,gpu}.py` | Node 运行时引导(`runtimes`)、AI 模型下载(`models`)、GPU CUDA wheels 安装(`gpu`)都已有机制可复用。 |
| **sidecar 硬依赖 repo 布局** | `electron/sidecar.ts:73`、`main.ts:54` | spawn `<repoRoot>/myenv/Scripts/python.exe -m core_rpc.server`,cwd=repoRoot;`repoRoot = resolve(__dirname,"../../../")`。**打包态此假设全部不成立**——核心改造点。 |
| **ffmpeg 已有 packaged-aware 雏形** | `electron/ffmpeg.ts:52-64` | 优先 `process.resourcesPath/ffmpeg.exe`,否则 PATH。bundle ffmpeg 即生效,无需改这块。 |
| **userData 已 repo-local** | `main.ts:97` `app.setPath("userData", resolve(here,"../../user_data"))` | 打包态需改成 install-local(见 §4)。 |
| **sidecar 自己 bootstrap `src/` 上 sys.path** | `core_rpc/server.py:26-29` | `_REPO=dirname(dirname(__file__))`、`_SRC=_REPO/src`。打包后 `src/` 必须随 `core_rpc/` 一起进 onedir,保持相对布局。 |
| 无 electron-builder / 无 PyInstaller spec / 无构建脚本 | `package.json` + glob | Tk 的 `build_portable.py`/`build-portable.yml` 已在 P2 删;P3 从零搭。 |

---

## 1. 目标产物

- **单一 Windows 安装包**(electron-builder NSIS)+ 可选便携 zip。
- 装完**开箱即用的范围** = 项目管理 + 三插件(clip/news_desk/news_video 素材的非 AI 部分)+ 视频导出(WebCodecs,GPU 在 renderer)。**视频功能不依赖任何下载。**
- **首次/按需引导**(强引导可跳过):Node 运行时(yt-dlp JS 挑战)、嵌入 AI 运行时(faster-whisper/llama-cpp)、AI 模型、CUDA GPU 档。
- 体积目标:**基线装包 ~250–400 MB**(不含嵌入 AI 重依赖与模型)。

---

## 2. sidecar 打包(PyInstaller onedir)

### 2.1 干净依赖闭包(打包输入)—— 先决步骤
**不碰 7GB 的 myenv。** 用 **uv** 从 `requirements.txt` 建一个全新、最小、CPU 档的构建专用环境作 PyInstaller 输入:

- 拆 `requirements.txt` 为两层:
  - **base(随包冻结)** = 非 AI 核心 + 引擎依赖:yt-dlp/requests/srt/google-genai/fish-audio-sdk/openai/json-repair/edge-tts/Pillow/pywin32。
  - **embedded-ai-extra(运行时按需装,不进冻结)** = faster-whisper + llama-cpp-python(CPU)。理由:它们是 opt-in 嵌入 AI;装进运行时可写目录(见 §5.3),避免冻结 onedir 体积 + 封死 sealed site-packages 的更新。
- 构建脚本 `packaging/build_sidecar.ps1`:`uv venv .build/sidecar-venv` → `uv pip install -r requirements-base.txt`(新拆出)→ PyInstaller。
- **绝不**让 torch/sherpa/nvidia/wandb/pandas 进来(requirements 已排除,干净 env 自然没有)。

### 2.2 PyInstaller spec(`packaging/core_rpc.spec`)
- 入口 = `core_rpc/server.py`(entry,`python -m core_rpc.server` 的等价)。
- `onedir`(非 onefile,避免每次启动解压到 temp,§3.2)。
- **datas**:把 `src/` 整树纳入(server.py 运行时按 `_REPO/src` 找;打包后用 `sys._MEIPASS` 解析,见 §5.1 对 server.py 的小改),保持 `core_rpc/` 与 `src/` 的相对布局。
- **hiddenimports**:`methods/__init__.load_plugins()` 动态 import 插件 + provider 域,PyInstaller 静态分析抓不全 → **用 `collect_submodules` 整包收** `core`/`creations`/`materials`/`core_rpc`(比手列稳)。**实测全收成功**:三插件注册 + core 数据 + env 注册表都在。
- **入口 wrapper(实测必需)**:冻结后入口脚本以 `__main__` 运行、无父包上下文 → `server.py` 的相对 import(`from .dispatch import`)全断。spec 入口改 `packaging/sidecar_entry.py`(`from core_rpc.server import main`,把 sidecar 当包导入),**server.py 一行不改**、dev `-m` 路径不受影响。
- **原生 DLL 收集**:pywin32(`pywin32_system32`)、CTranslate2(若 base 含)——base 不含嵌入 AI 时这块最小化,是选 lean 的附带好处。
- 输出 `dist/core_rpc/`(含 `core_rpc.exe` + `_internal/`),打进 Electron `resources/sidecar/`。

### 2.3 体积预期
base 冻结(无 faster-whisper/llama/CUDA)≈ Python 运行时 + 上述纯/轻依赖 ≈ **80–150 MB**。嵌入 AI 运行时装时再落 user_data。

---

## 3. Electron 打包(electron-builder)

- 加 `electron-builder` devDep + `package.json` build 配置(或 `electron-builder.yml`)。
- target:`nsis`(安装包)+ `portable`(可选 zip)。Windows x64。
- `extraResources`:`resources/sidecar/`(PyInstaller onedir)+ `resources/ffmpeg.exe` + `resources/ffprobe.exe`(见 §6)。
- electron-vite `build` 产 `out/{main,preload,renderer}` → builder 收 `out/` + extraResources。
- `appId` / 产品名 / 图标 / 版本(`package.json` version 现 `0.0.0` → 对齐 `pyproject.toml` 的 `0.3.5` 或独立版本线,待定)。
- **Win11 26200 sandbox 兜底**已在 `main.ts`([[project_electron_version_policy]]),打包态保留;`disable-gpu-sandbox` 的 dev concession(`main.ts:103`)打包前复审是否仍需。

---

## 4. 路径解析:dev ↔ packaged(核心代码改造)

单一 seam:`app.isPackaged`。新增 `electron/paths.ts` 统一解析,`main.ts`/`sidecar.ts` 消费。

| 资源 | dev | packaged |
|---|---|---|
| sidecar 可执行 | `<repoRoot>/myenv/Scripts/python.exe -m core_rpc.server`(cwd=repoRoot) | `<resourcesPath>/sidecar/core_rpc.exe`(无需 python/cwd=repoRoot 假设) |
| `repoRoot`(src/core_rpc 根) | `resolve(__dirname,"../../../")` | 不再需要(冻结包自带 src/;sys._MEIPASS) |
| userData | `resolve(__dirname,"../../user_data")`(repo-local) | install-local:安装目录旁 `user_data/`(便携);NSIS 装到 Program Files 时该处只读 → 落 `<exeDir>/../user_data` 或显式可写的安装根。**待定:便携 zip vs NSIS 的可写根策略**(便携=exe 旁;NSIS=需选可写位置或退 `%LOCALAPPDATA%` 例外?与 portable-data 铁律冲突 → 倾向只出便携包 + NSIS 装到用户可写目录)。 |
| ffmpeg/ffprobe | PATH(`core/env` 检测) | `<resourcesPath>/ffmpeg.exe`(`ffmpeg.ts` 已支持) |

`sidecar.ts` 改:`SidecarOptions` 从 `{repoRoot}` 改成注入解析好的 `{command, args, cwd}`(packaged 走 exe,dev 走 python -m),其余收发逻辑不动。

---

## 5. sidecar 在打包态的运行时调整

### 5.1 `server.py` 的 `_REPO/_SRC` 解析
打包态 `__file__` 在 `_internal/` 下,`dirname(dirname())` 不再是 repo 根。改:冻结态(`getattr(sys,"frozen",False)`)用 `sys._MEIPASS` 作根;dev 态保持现状。src/ 经 spec 的 datas 进同一根。

### 5.2 native warmup
`core/ai/warmup.py` 的 `_NATIVE_MODULES`(ctranslate2/faster-whisper/llama_cpp)在 base 冻结里**不存在** → warmup 的 try/except 已容错(`server.py:103`)。装了嵌入 AI 后才需预热;预热模块解析要能看到 §5.3 的运行时 site。

### 5.3 嵌入 AI 运行时安装位置(opt-in)
冻结 onedir 的 site-packages 是 sealed/只读 → 运行时 pip 装的 faster-whisper/llama-cpp 不能进那里。方案:装进 **`user_data/runtimes/py-extra/`**(可写),冻结 sidecar 启动时把它 prepend 到 `sys.path`。`core_rpc/methods/env.py` 或 `gpu.py` 加一个 `embedded-ai` 可安装组件(镜像现有 CUDA wheels 安装流,`core/gpu_install` 是范本)。**这是 lean 决策的代价,需一段新代码;细节 P3 实施期定。**

---

## 6. 二进制依赖

| 依赖 | 策略 | 依据 |
|---|---|---|
| ffmpeg / ffprobe | **暂不随包(用户拍板 2026-06-03)→ PATH 回退**;真分发前补 pinned 下载 | `core.env` 的 ffmpeg/ffprobe 是 detect-only(`install=None`)、只探 PATH,无现成下载源(info_url=gyan.dev);`ffmpeg.ts` 已有 PATH 回退,开发机/装了 ffmpeg 的机器能跑。**最终随包来源 = 构建时从 gyan.dev 拉 pinned 静态构建抽 exe 进 resources/**(step 4,延后);随包后视频=核心功能仍不该被下载门槛堵死([[feedback_no_forced_downloads]])。 |
| Node.js(yt-dlp JS 挑战) | **引导**到 `user_data/runtimes`(已落地) | 仅 yt-dlp 部分链接需要;`core/env` 已有 Node 下载安装。 |
| 嵌入 AI 运行时(faster-whisper/llama-cpp) | **opt-in 引导**装 `user_data/runtimes/py-extra`(§5.3) | AI 重依赖,opt-in([[feedback_no_forced_downloads]])。 |
| AI 模型 / CUDA wheels | **绝不随包**,运行时下载 user_data(已落地) | 铁律 + 体积。 |
| 字体 | 系统 `C:/Windows/Fonts`(现状) | §3.2 既定。 |

---

## 7. 构建管线

- `packaging/` 新目录:`build_sidecar.ps1`(uv 建 base env → PyInstaller → 产 `resources/sidecar/`)+ `core_rpc.spec` + `requirements-base.txt`(拆出)。
- `desktop/package.json` 加脚本:`build:win`(electron-vite build → electron-builder)。
- 顺序:`build_sidecar.ps1` → 拷 ffmpeg → `pnpm build` → `electron-builder`。
- CI:GitHub Actions Windows runner(P2 删的 `build-portable.yml` 是 Tk 的;这是全新 Electron 管线),**先本地跑通再上 CI**。

---

## 8. 实施步骤(增量、每步 build-green、低风险优先)

> **原则**:路径 seam 与构建管线解耦——seam 可在无任何打包产物时就写好并经 dev 回归;构建管线产物后再端到端验。**TS 替代/seam 测好前不破坏 dev 启动。**

1. **路径 seam(纯 dev 可验)**:新增 `electron/paths.ts`(`app.isPackaged` 分发 sidecar command/args/cwd + userData + resources)。`sidecar.ts` 改吃注入式 `{command,args,cwd}`。`main.ts` 接线。**dev 行为字节不变**,typecheck + build + dev 启动回归。
2. **server.py 冻结态根解析**(§5.1):`sys.frozen`/`_MEIPASS` 分支;dev 不变;pytest 不受影响(非冻结)。
3. **拆 requirements-base.txt** + `packaging/build_sidecar.ps1` + `core_rpc.spec`;本地跑出 `resources/sidecar/core_rpc.exe`,命令行手验它能起 stdio loop(echo 往返)。
4. **ffmpeg 随包**:拷 ffmpeg/ffprobe 进 resources;`ffmpeg.ts` 已支持,验 packaged 探测命中。
5. **electron-builder 配置** + `build:win`;出 NSIS;**安装到干净目录端到端跑一遍**(开项目→clip/news_desk 导出 mp4→素材建实例)。
6. **userData install-local 落位**(§4 待定项定夺)+ 便携/NSIS 可写根策略。
7. **嵌入 AI opt-in 安装**(§5.3):`py-extra` + sys.path prepend + env 组件;装后验 ASR/本地 LLM。
8. **打磨**:图标/版本/产品名;`disable-gpu-sandbox` 复审;CI。

---

## 9. 待决 / 风险

- **userData 可写根**(§4):portable-data 铁律 vs NSIS 装 Program Files 只读。**倾向主推便携 zip(exe 旁 user_data),NSIS 引导用户装到可写目录。** 实施步骤 6 定。
- **PyInstaller × 动态插件加载**:`load_plugins()` 全靠 hiddenimports 列全,漏一个则该域运行时 ImportError。需逐域核对(creations/materials/ai providers)。
- **嵌入 AI 运行时装到 `py-extra` 的 sys.path 注入**(§5.3):新机制,与现有 GPU 安装流的交互(nvidia DLL PATH 注入在 `core/gpu.py`)要一起验。
- **版本线**:`package.json 0.0.0` vs `pyproject 0.3.5` vs VideoCraft `0.3` tag — P3 出包前统一。
- **`disable-gpu-sandbox`**(`main.ts:103`)是 dev concession,打包前复审。
