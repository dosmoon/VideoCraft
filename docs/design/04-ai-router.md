# AI 架构 — core.ai 门面 + AI 控制台

> 重写于 2026-06-10。Tk 时代正文（Tk 控制台三 tab 布局、Prompt hub UI、Toplevel 对话框细节）见 git 历史；
> provider-dispatch 的插件边界由 [ADR-0008](../adr/0008-plugins-ts-python-capability-gateway.md) 固化（per-plugin Python 业务面已退役）。

VideoCraft 所有 AI 能力（文本 LLM、ASR、TTS）经统一门面 `core.ai` 路由，任何上层都不直接调 SDK。
UI 入口 = Electron renderer 的 AI 控制台（[AiConsole.tsx](../../desktop/src/renderer/aiconsole/AiConsole.tsx)），
经 `ai.*` RPC 读写 sidecar 侧的纯数据 read model（[core/ai/console_view.py](../../src/core/ai/console_view.py)）。

---

## 架构原则

### 1. 严格分层

```
┌──────────────────────────────────────────────┐
│ Electron renderer（UI + 插件，全 TS）          │
│  - 工作台调业务 RPC（asr / translate / 分析）  │
│  - AiConsole 调 ai.* RPC（唯一配置面）         │
└──────────────┬───────────────────────────────┘
               │ HTTP RPC（core_rpc）
┌──────────────▼───────────────────────────────┐
│ Core Business Layer（src/core/）              │
│  - translate / asr / subtitle_pipeline / …    │
│  - 处理 chunking / 进度 / 错误                │
└──────────────┬───────────────────────────────┘
               │ from core import ai
┌──────────────▼───────────────────────────────┐
│ Core AI Infrastructure（src/core/ai/）        │
│  - complete / complete_json / asr / tts      │
│  - Router / providers/ / 配置 / 统计          │
└──────────────────────────────────────────────┘
```

feature 层（`core/translate.py` 等）才 `from core import ai`；renderer 不感知 provider SDK。
例外：AI 控制台本身经 `ai.*` RPC 直达 router 配置。

### 2. 三档部署层 = 用户旅程三阶段（缺一不可）

| 档 | Provider | 定位 |
|----|----------|------|
| **内置 embedded** | faster-whisper（ASR）/ llama.cpp Qwen3（LLM）/ edge-tts（免费在线 TTS） | 开箱即用，零配置零 key |
| **aistack** | [github.com/dosmoon/aistack](https://github.com/dosmoon/aistack) 本地网关（端口 11500，统一 ASR/TTS/LLM） | 本地高性价比 |
| **云 cloud** | Gemini / DeepSeek / Custom(OpenAI 兼容) / ClaudeCode CLI / Lemonfox / Fish Audio | 质量天花板 |

### 3. 路由 = 严格尊重用户挑选

用户给某 task 选了 provider X → X 失败就 **raise**，绝不静默换 provider；
只有用户选 **Auto**（仅 LLM 档有）才走 candidates 顺序兜底。

### 4. ASR / TTS 对称封装

固定功能 API 与 LLM 共享门面结构，provider 差异藏在元数据里。
**TTS 例外：不走 task routing** —— 音色和引擎在使用现场挑选（每次合成时指定 provider + voice_id），路由表只管 LLM / ASR。

### 5. Prompt 归属

~~中央 Prompt hub / Playground~~ **已退役**（判定缺陷：prompt 与插件上下文不可分割）。
prompt 模板仍存 `prompts/*.md`（`core/prompts.py` 加载 + schema 在 `prompts_schemas.py`），但**不再有中央编辑 UI**；
方向 = prompt 调试回到各插件内部，框架只提供可复用调试组件（待做）。

---

## 文件布局

```
src/core/ai/
├── __init__.py            # 对外门面 facade
├── router.py              # AIRouter + task→(provider, model) 路由
├── config.py              # 默认 + providers.json I/O + 迁移；keys_dir() 经 core.user_data
├── console_view.py        # AI 控制台纯数据 read model（deploy_tier / key_status / routing tiers）
├── errors.py              # AIError + Kind 枚举（contract，详见下）
├── cancellation.py        # CancellationToken（contract，未全 wire）
├── stats.py               # 线程安全调用计数
├── tts_voice.py           # TTSVoice 数据模型 + 磁盘缓存（跨 provider 音色 catalog）
├── call_log.py / warmup.py / tiers.py
└── providers/
    ├── gemini.py / openai_compat.py / claude_code.py     # LLM 云
    ├── llama_cpp.py                                      # LLM 内置（GGUF 进程内）
    ├── faster_whisper.py                                 # ASR 内置（CTranslate2）
    ├── lemonfox.py                                       # ASR 云
    ├── aistack.py                                        # 本地网关（ASR/TTS/LLM 全类）
    ├── edge_tts.py / fish_audio.py                       # TTS
    └── _json_utils.py

core_rpc/methods/          # ai.* RPC（snapshot + 写操作 + test/refresh jobs）
desktop/src/renderer/aiconsole/AiConsole.tsx   # 控制台 UI
prompts/*.md               # prompt 模板（feature 层加载；无中央编辑 UI）
```

**Key 存储**：`keys_dir()` —— dev = repo 根 `keys/`；打包态 = 安装目录 `user_data/keys/`。
路径解析**唯一经 `core.user_data`**（多处各算一套必漂移，冻结态踩过两次）。
`providers.json`（providers / asr_providers / tts_providers / task_routing + 迁移函数）住在 keys_dir 下。

---

## core.ai 门面 API

```python
from core import ai

text = ai.complete(prompt, task="translate", provider=None, model=None)
obj  = ai.complete_json(prompt, schema={...}, task="subtitle.post")
res  = ai.asr(audio_path, task="asr.transcribe", language="en", on_event=...)
ai.tts(text, output_path, provider="edge_tts", voice_id="...", ...)   # provider 必填，不路由
cap  = ai.describe(task)
```

- `task` 命名空间化：`translate` / `subtitle.post` / `asr.transcribe` / …（2026-04 起三条 `subtitle.*` 合并为 `subtitle.post`）。
- 路由持久化**双轨**：`task_routing`（task → provider+model 精确选择）+ `task_tier_prefs`（task → 档位偏好 embedded/cloud/aistack/auto），控制台按档位组织选择。
- ASR 客户端契约：`segments[]` 保句子级，**绝不做 SRT 工业级 cue-sizing**（那是烧录层、翻译之后的事）；
  句子级重组在 [core/sentence_regroup.py](../../src/core/sentence_regroup.py)。
- 高频结构化任务用 lean 模式控制预算（如 `subtitle.post` 已走 `lean=True`；本地 1.7B Qwen3 在 schema 约束 + 原文锚 + 紧 prompt 下够用）。

---

## AI 控制台（Electron）

六 tab：**Routing · Embedded · Cloud · aistack · TTS · Stats**。

- 全部状态来自 `ai.snapshot`；每个写操作 RPC 返回新 snapshot，整个控制台单源重同步。
- `console_view.py` 返回纯结构化数据（无 i18n 字符串、无颜色）：
  `deploy_tier ∈ {local, free_online, aistack, cloud}`，`key_status.state ∈ {cli, no_key_needed, not_configured, empty, ok}`，
  LLM routing tiers = `(embedded, cloud, aistack, auto)`，ASR/TTS 无 auto。
- 网络类动作（Test connection / aistack 模型刷新）走 sidecar jobs，不阻塞 dispatch 线程。
- 模型下载 / 安装的唯一入口是独立的**本地模型管理**（菜单 AI →，[ModelManager.tsx](../../desktop/src/renderer/models/ModelManager.tsx)），不在控制台里；
  任何模型 / key / 外部依赖**强引导可跳过**，非 AI 功能不被 AI gate 堵死。

---

## 错误契约 / 取消（contract 状态）

- `AIError` + Kind 枚举已定义（NETWORK / AUTH / QUOTA / RATE_LIMIT / REFUSED / MALFORMED / OVERFLOW / CANCELLED / UNKNOWN）；
  重试分工：core.ai 管 transport（NETWORK / RATE_LIMIT 指数退避），feature 管 semantic（MALFORMED / OVERFLOW），UI 管 user。
  provider 原生异常 → Kind 的全量映射仍是欠账。
- `CancellationToken` 语义 = **完全原子丢弃**（不保留半程产出，避免 context-coupled 任务风格割裂）；HTTP abort wire 未全做。
- **永不做 $ 成本估算**（无查价 API、价格表必过时、误差 ±30%）；只显示 token 计数。

---

## 历史（浓缩）

- **2026-03 ~ 04**：Phase 1 三档路由 → core/ai 包化（M1~M6）→ Tk AIConsole tab → prompt hub → subtitle task 合并（详见 git 历史与归档文档）。
- **2026-05 上**：内嵌 AI 档落地（faster-whisper / llama.cpp / edge-tts，sherpa-onnx 弯路全删，见 [research-notes/sherpa-detour.md](../research-notes/sherpa-detour.md)）；aistack 拆为独立服务并接入；TTS 抽象重构（不路由 + 跨 provider catalog）；Tk 控制台重塑为 6-tab + task_tier_prefs。
- **2026-05 末 ~ 06**：Tk 退役；控制台迁 Electron（`ai.*` RPC + console_view read model）；Prompt hub / Playground 退役，prompt 回插件内（方向）。
