# AI 架构 — core.ai 门面 + AI 控制台

VideoCraft 所有 AI 能力（文本 LLM、ASR、TTS）经统一门面 `core.ai` 路由，
UI 不直接调任何 SDK。Hub 内 AI 控制台（`tools/router/ai_console.py`）
集中管理 provider key、任务路由、prompt、调用统计。

---

## 架构原则（5 条铁律）

任何 AI 相关代码必须满足。

### 1. 严格三层分层

```
┌─────────────────────────────────────────┐
│ UI Layer (tools/)                       │
│  - TranslateApp / Speech2TextApp / ... │
│  - 不感知 AI 存在，禁 import core.ai   │
└──────────────┬──────────────────────────┘
               │ business APIs
               ▼
┌─────────────────────────────────────────┐
│ Core Business Layer (core/)             │
│  - translate.py / asr.py / tts.py      │
│  - srt_ops.py / prompts.py             │
│  - 处理 chunking / 进度 / 错误         │
└──────────────┬──────────────────────────┘
               │ AI infrastructure
               ▼
┌─────────────────────────────────────────┐
│ Core AI Infrastructure (core/ai/)       │
│  - complete / complete_json / asr / tts │
│  - Router / providers/ / 配置 / 统计   │
└─────────────────────────────────────────┘
```

UI 调 `core.translate.translate_srt(...)` 等 feature API；feature 内才
`from core import ai`。**例外**：AI 控制台本身、未来 AI playground
等"基础设施工具"允许直接 import core.ai。

### 2. 自描述接口

`core.ai.describe(task, tier)` 返回 capability 元数据
（max_input_tokens / supports_stream / supports_json /
safe_concurrency / latency_p50_ms / 实际 provider+model）。Phase 1 是
placeholder；M7 / Phase 2 时填真实值，feature 层可据此决定整块/分批/
流式策略。

### 3. ASR / TTS 对称封装

固定功能 API（ASR/TTS）和 LLM 共享门面结构：调用 pattern 一致，provider
差异藏在元数据里，无损切换 provider 不改 feature 代码。

### 4. Prompt 对 UI 隐藏

UI 工具层禁止出现 prompt 字符串 / 编辑框。Prompts 存在 `prompts/*.md`
（由 `core/prompts.py` 管理）。唯一可视化入口：AI 控制台 → Prompts tab。

### 5. Prompt 驱动功能同理

subtitle.pack / segments / refine / titles 这类"表面像业务功能、实际是
prompt 驱动"的 task 也归入此范式 — UI 调
`core.srt_ops.generate_subtitle_pack(srt)` 等 feature API，完全不见
prompt 字符串。注意 prompt 文件 (`subtitle.pack.md` 等) 与 router 的
task 标识 (`subtitle.post`) 解耦：prompt 由 feature 层用任意 key 加载，
所有四个字幕调用统一以 `task="subtitle.post"` 进 router。

---

## 文件布局

```
src/
├── core/
│   ├── ai/
│   │   ├── __init__.py            # 对外门面 facade
│   │   ├── router.py              # AIRouter 类 + task→provider 映射
│   │   ├── tiers.py               # TIER_* 常量（向后兼容；UI 已不暴露）
│   │   ├── errors.py              # AIError + 9 种 Kind 枚举（contract，未填）
│   │   ├── cancellation.py        # CancellationToken（contract，未 wire）
│   │   ├── config.py              # 默认 + providers.json I/O + TASKS 目录
│   │   ├── stats.py               # 线程安全调用计数
│   │   └── providers/
│   │       ├── gemini.py          # call / call_json / list_models
│   │       ├── openai_compat.py   # DeepSeek + Custom 共享
│   │       ├── claude_code.py     # `claude -p` subprocess
│   │       ├── lemonfox.py        # ASR HTTP + 上传进度 + 重试
│   │       ├── fish_audio.py      # TTS SDK + 流式 + 取消
│   │       └── _json_utils.py     # JSON fence 剥离 + 解析
│   ├── translate.py               # feature 层
│   ├── asr.py                     # feature 层
│   ├── tts.py                     # feature 层
│   ├── srt_ops.py                 # subtitle.* feature 层
│   └── prompts.py                 # prompt hub 加载/保存/重置
├── tools/
│   └── router/
│       └── ai_console.py          # AIConsoleApp Hub tab
├── ai_router.py                   # 薄兼容 shim（只剩 TIER_* 常量）
└── ...

prompts/                           # 仓库根，shipped + 用户编辑
├── translate.md
├── subtitle.segments.md            # 旧三件套（独立菜单仍在用）
├── subtitle.refine.md
├── subtitle.titles.md
└── subtitle.pack.md                # 一次产出 titles+segments+refined（JSON）

keys/                              # 仓库根，gitignored
├── providers.json                 # router 配置（auto-生成 + 迁移）
└── *.key                          # 各 provider API key
```

---

## core.ai 门面 API

```python
from core import ai

# 文本 LLM
text = ai.complete(prompt, task="translate", tier=ai.TIER_STANDARD,
                   provider=None, model=None)
obj  = ai.complete_json(prompt, schema={...}, task="subtitle.refine")

# 语音识别
result = ai.asr(audio_path, task="asr.transcribe", language="en",
                translate=False, speaker_labels=False, on_event=...)
# returns: provider 原始 verbose_json dict

# 语音合成
ai.tts(text, output_path, task="tts.synthesize", voice_id="...",
       audio_format="mp3", should_cancel=lambda: stop, on_chunk=...)

# 元数据
cap     = ai.describe(task, tier)
ok      = ai.is_tts_sdk_available("fish_audio")
models  = ai.list_models("Gemini")        # 远端拉取（仅 LLM）

# 单例（基础设施工具用）
from core.ai.router import router
```

`task` 参数命名空间化（`translate` / `subtitle.post` / `asr.transcribe` /
`tts.synthesize`）；`tier` 参数向后兼容但实际路由已不依赖 tier — Router
单选 `task → (provider, model)`。

> **2026-04 合并**：原 `subtitle.segments / refine / titles` 三个 task
> 已合并为单一 `subtitle.post`（字幕后处理）。四个 srt_ops 调用
> （segments / refine / titles / pack）现在均以 `task="subtitle.post"`
> 进 router。Prompt key 与 task 解耦——`prompts.get("subtitle.refine")`
> 等仍各自加载独立 markdown 文件。
>
> 旧 providers.json 中的三条 `subtitle.*` routing 由
> `_migrate_task_routing()` 自动 collapse 到 `subtitle.post`（取首条非空
> cell），并在下一次保存时从磁盘清除旧键。

UI 层规约：`tools/` 下禁止 `import ai_router` / `from fish_audio_sdk import ...` /
直接调 Lemonfox HTTP — 全部走 `from core import translate, asr, tts, srt_ops`。

---

## Provider 池

| 类型 | 内置条目 | 需要 API Key | 调用方式 | list_models |
|------|---------|--------------|---------|-------------|
| `gemini` | Gemini | ✅ | `google.generativeai` SDK | ✅ |
| `openai_compatible` | DeepSeek / Custom | ✅ | `openai` SDK + `base_url` | ✅ |
| `claude_code` | ClaudeCode | ❌ CLI 自管 | 本地 `claude -p` subprocess | ❌（固定别名）|
| `lemonfox` (ASR) | LemonFox | ✅ | HTTP POST + 上传进度 + 重试 | ❌ |
| `fish_audio` (TTS) | Fish Audio | ✅ | `fish_audio_sdk` 流式 | ❌ |

**Groq** 在 2026-04 移除 — 实测 Llama / qwen 系列 NLP 质量不达标。未来扩展走 OpenRouter / one-api 中转作为 `openai_compatible` 的 base_url。

**ClaudeCode** subprocess 设计要点：
- 无 API Key，依赖本机 `claude` CLI 登录态
- prompt 走 stdin 避开 Windows 32KB 命令行长度上限
- `--permission-mode bypassPermissions` 安全（VideoCraft 只取纯文本输出）
- Windows 上用 `shutil.which()` 解析 `.cmd` 路径再交 subprocess（npm 装的 CLI 必须）
- `_normalize_providers()` 升级时自动回填 _DEFAULT_PROVIDERS 新条目到老 providers.json

---

## AI 控制台（`tools/router/ai_console.py`）

Hub 内 tab，三个子 Notebook：

### Tab 1: Provider & 路由（2026-04 重做）
同一标签下两段堆叠，分担"配置 provider"与"分配任务"两件事。

**上：Task Routing（4 行）**
- 每行 = TASKS 中的一项（translate / subtitle.post / asr.transcribe / tts.synthesize），含 Provider 和 Model 两个下拉
- LLM 任务 Model 下拉支持手动输入（`<FocusOut>` / `<Return>` 触发保存）
- ASR/TTS 行 Model 列固定 "—"（provider-only routing）
- 切换 Provider 自动刷新对应 Model 下拉值并 reset 到首个可用模型
- 任意下拉变化即时调 `router.set_task_routing()` 持久化，不需要"保存"

**下：Providers（紧凑列表）**
- 每行一个已配置 provider，含名称 + LLM 模型计数 + Key 状态 + [Edit] [Test]
- Edit 对话框：API Key + Base URL（openai_compat）+ **已启用模型 Listbox** + [刷新并选择…] [移除选中] + executable/timeout（claude_code）+ timeout/retries（ASR）
- **模型 Picker 对话框**（[刷新并选择…] 入口）：后台拉 `list_models()` → 模态对话框，顶部搜索 + 中间可滚动复选框（已启用项预勾选）+ 底部手动添加入口；无 key 或拉取失败时仍可工作（仅手动添加模式）。Save 回写 Edit 对话框的 Listbox，再由 Edit 的 Save 持久化到 providers.json。
- Test 按钮：LLM 调短 `complete()` 真测；ASR/TTS disabled 占位（待样本数据）

**滚动语义**：canvas 滚轮事件用 `<Enter>` / `<Leave>` 局部绑定，避免渗透到 modal Edit 对话框；内容不溢出时滚轮 no-op。

> **2026-04 之前的旧布局**：单表 (provider, model) × task 单选矩阵，Gemini 模型多了之后行数膨胀；矩阵已废弃，逻辑迁到上述两段式。模型 picker 对话框（解决 list_models 一次性塞 20+ 模型到 textarea 的痛点）于 2026-04 末同步落地；Providers 段进一步卡片化暂留 Phase 3。

### Tab 2: Prompts
左 task 列表（被改的 ● 标记），右 Text 编辑器 + 占位符提示 + Save / Reset 按钮。
- Save → `prompts/<task>.md`
- Reset → 写回 `core.prompts.DEFAULTS[task]`

### Tab 3: 调用统计
Treeview 显示每 provider 的 calls / errors / error_rate / last_used。

---

## Prompt Hub (`core/prompts.py`)

```python
from core import prompts as p

p.get("translate")                        # 读 prompts/translate.md，缺则返回 DEFAULTS
p.set("translate", new_text)              # 写文件
p.reset("translate") -> str               # 写回 DEFAULTS 内置默认
p.is_overridden("translate") -> bool      # 当前文件是否与 DEFAULTS 不同
p.placeholders("translate") -> list[str]  # 文档化占位符
p.list_tasks() -> dict_keys
```

双重存在：`prompts/<task>.md` 是用户编辑面，`DEFAULTS` 字典是 Reset 兜底。
文件被删 → 自动 fallback 到 DEFAULTS。

调用方约定：feature 层 `prompt = explicit_prompt or _prompts.get(task)`，
即 `prompt=` 参数仍可外部覆盖（M7 等场景）。

---

## 数据模型

`keys/providers.json`（auto 生成 + auto 迁移）：

```json
{
  "providers":     {... LLM provider 配置（key_file / models / type / ...）},
  "asr_providers": {... ASR provider 配置},
  "tts_providers": {... TTS provider 配置},
  "tier_routing":  {... 兼容旧字段，UI 已不用},
  "task_routing":  {
    "translate":      {"provider": "DeepSeek",   "model": "deepseek-chat"},
    "subtitle.post":  {"provider": "ClaudeCode", "model": "sonnet"},
    "asr.transcribe": {"provider": "lemonfox",   "model": ""},
    "tts.synthesize": {"provider": "fish_audio", "model": ""}
  }
}
```

`task_routing` 是 flat schema：每个 task 单 (provider, model)。`_migrate_task_routing()`
两轮迁移：(a) 早期 M6 的 3-tier 嵌套结构 `{task: {tier: cell}}` collapse 到
standard tier 的值；(b) 2026-04 的旧三条 `subtitle.segments / refine / titles`
collapse 到 `subtitle.post` 并删除原键。

---

## 当前实施状态 vs Phase 2 留位

| 议题 | 当前状态 | Phase 2 / 未来 |
|---|---|---|
| 三层分层 | ✅ 强制落地 | — |
| core.ai 门面 | ✅ complete / complete_json / asr / tts / describe / list_models / is_tts_sdk_available | — |
| AI 控制台 | ✅ 三 tab：Provider & 路由（两段式：Task Routing 下拉 + Providers 列表 + 模型 Picker 对话框）/ Prompts / 统计 | Providers 段卡片化（Phase 3）；调用费用估算 / 错误率列 |
| Task 命名空间 | ✅ translate / subtitle.post / asr.transcribe / tts.synthesize（2026-04 三条 subtitle.* 合并为 subtitle.post）| 加 vision.* / embed.* / prompt.* |
| Prompt hub | ✅ `prompts/*.md` + AI 控制台 Prompts tab | per-(task, provider) 变体 |
| 错误契约 (X1) | ⚠️ AIError + 9 Kind 已定义但 provider 仍抛 RuntimeError | 给每 provider 写原生异常→Kind 映射；UI 加 Kind→动作按钮映射表 |
| 取消传播 (X2) | ⚠️ CancellationToken 类已建，未 wire 到 provider HTTP abort | provider adapter 注册 abort_cb；feature 层 chunk 边界 throw_if_cancelled；UI 加取消按钮 |
| 成本预估 (X3) | ✅ token 统计（无 $）| 永不做 $ 估算 |
| 缓存 (X4) | ❌ no-op（API 留 `cache_hint=None` 位）| A 前缀缓存（Anthropic cache_control / Gemini Context Cache）+ B 客户端 SHA256 缓存 |
| 流式 (X5) | ⚠️ chunk 级（feature 层分批回调）| token 级 + partial result 协议（callback 已"partial result ready"语义，向前兼容）|
| 并发 (X6) | ❌ 串行（`max_concurrency=1`）| ThreadPoolExecutor + provider semaphore；`safe_concurrency` 字段已留 |
| API Key 存储 | `keys/providers.json` 在仓库根 | 与 BACKLOG L17「用户数据绿色化」协同迁 `user_data/keys/` |
| ASR / TTS Test | ❌ 按钮 disabled 占位 | bundle 1s 样本 wav；TTS 加 `test_voice_id` 字段 |
| TTS Voice ID 收藏 | ❌ 每次手填 | 加常用 voice 库（独立 tab 或下拉）|

---

## 错误契约（X1，未实施）

落地时实施。**9 种 AIError.Kind**：

| Kind | 含义 | 可重试 | 谁重试 |
|---|---|---|---|
| NETWORK | DNS / TCP / TLS / timeout | ✅ | core.ai（指数退避 1/2/4s）|
| AUTH | Key 无效 / 过期 | ❌ | — |
| QUOTA | 配额耗尽 | ❌ | — |
| RATE_LIMIT | 瞬时过频 | ✅ | core.ai（按 Retry-After，上限 60s）|
| REFUSED | 安全过滤拒绝 | ❌ | — |
| MALFORMED | JSON schema 不合格 | ⚠️ | feature 层决定 |
| OVERFLOW | 超 context window | ❌ | — |
| CANCELLED | 用户主动取消 | ❌ | — |
| UNKNOWN | 未分类 | ❌ | — |

**AIError 结构**（`core/ai/errors.py` 已定义）：
```python
class AIError(Exception):
    kind: Kind
    provider: str
    message: str
    retry_after: float | None
    raw: Exception | None
```

**三层重试分工**：core.ai 管 transport（NETWORK/RATE_LIMIT），feature 管
semantic（MALFORMED 重写 prompt、OVERFLOW 自动分块），UI 管 user
（"重试"按钮）。

**UI 映射表**：每 Kind 配一条人话 + 推荐动作（如 AUTH → "打开 AI 控制台"）。
Phase 1 各 provider 仍直接抛 RuntimeError；Phase 2 实施时一次性写 provider
原生异常 → Kind 映射表。

---

## 取消传播（X2，未 wire）

```python
class CancellationToken:
    def cancel(self): ...                    # UI 调
    def throw_if_cancelled(self, provider): ...  # feature 层调
    def register_abort(self, cb): ...        # provider adapter 调
```

**取消语义 = 完全原子丢弃**，不保留半程产出。理由：translation 等
context-coupled task 的半程数据会造成后续质量割裂（模型失去前半段
建立的术语/语气约定，重跑得到风格不一致）。"独立批量任务"出现时再
单独讨论恢复。

**响应时间承诺**：provider 支持 HTTP abort 时 <1s；降级最差 30s
等当前调用完成；兜底 60s 硬超时。

---

## 不做 $ 估算的理由

- 无 provider 查价 API
- 爬 provider 官网脆弱且违反 ToS
- 内置价格表维护难过时
- Provider 分层定价 / 缓存折扣 / 批处理折扣让 $ 数字 ±30% 误差
- 用户自己最清楚自家账单（他们申请的 key）

仅显示 token 数让用户自己换算；Router tab 永远不展示 $。

---

## 历史

- **2026-03 Phase 1** — 三档路由 + Gemini/Groq/DeepSeek/Custom；消费方
  SrtTools / Translate-srt-gemini 迁移
- **2026-04 上半** — Groq 删除 + `complete_json` API + translate_srt 切
  JSON schema + ClaudeCode subprocess provider 上线
- **2026-04 中（M1~M5）** — `core/ai/` 包脚手架 → translate / srt_ops /
  asr / tts feature 层迁移；UI 全部走 core feature；旧 ai_router.py
  压缩为 TIER_* shim
- **2026-04 中（M6 + redesign）** — `RouterManagerWindow` Toplevel
  替换为 `AIConsoleApp` Hub tab；功能 × 档位矩阵；试用后 collapse
  tier 维度（task→provider+model 单选）；删 Enabled 勾子；加 Test +
  Refresh 按钮
- **2026-04 中（L16）** — Prompt hub：4 个 prompt 抽离到
  `prompts/*.md`；AI 控制台 Prompts tab
- **2026-04 末** — 字幕 task 合并 + AI 控制台两段式 + 模型 Picker：(a) `subtitle.segments / refine / titles` 三个 task 收敛为 `subtitle.post`，加迁移函数清理 providers.json；(b) 新增 `subtitle.pack` prompt 与 `core.srt_ops.generate_subtitle_pack()`，一次 `complete_json` 调用产出 titles + segments + refined（首个走 schema-enforced JSON 的 srt_ops 接口）；(c) AI 控制台 Routing 标签由 (provider × model) × task 矩阵改为「Task Routing 4 行下拉 + Providers 紧凑列表」两段式，并修掉滚轮全局 bind 渗透到 modal 的 bug；(d) LLM Edit 对话框模型部分由 textarea 改为「已启用模型 Listbox + 模型 Picker 对话框」，Picker 带搜索 + 复选 + 手动添加，解决 Gemini list_models 一次糊一大排的痛点（commits 813b7eb / f25614f / 9f1c939）
