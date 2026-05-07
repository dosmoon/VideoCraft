# VideoCraft ↔ aistack 集成指南

> 本文档站在 **VideoCraft 消费方** 视角，说明怎么把 aistack 接进来用。
> aistack 自己的设计、调度策略、API 协议、错误信封等内容**不在这里维护**——
> 详见 `github.com/dosmoon/aistack` 的 `docs/api/`。
>
> 协同纪律：
> - VideoCraft 仅依赖 **aistack 公开 API 文档**
> - 不依赖 aistack 内部实现（哪个引擎、显存占多少、调度细节）
> - aistack 改实现不影响 VideoCraft；改 API 时 aistack 走版本号（`/v1` → `/v2`）

---

## 1. 什么是 aistack

**aistack** 是 dosmoon 旗下的本地 AI capability gateway——所有用本地资源的
AI 能力（ASR / TTS / 本地 LLM）通过它统一暴露成 OpenAI 兼容 HTTP API。

VideoCraft 跟 aistack 的关系跟"App ↔ 云 API 服务"同构：
- VideoCraft 只调 11500 端口
- 后面是本机 GPU、局域网 GPU、还是租用云 GPU——VideoCraft 不需要也不该知道

仓库：`github.com/dosmoon/aistack`

## 2. 安装与启动 aistack

> 详细步骤以 aistack repo 的 README 为准，本节只列 VideoCraft 用户最常碰到的。

```bash
git clone https://github.com/dosmoon/aistack.git
cd aistack
uv venv --python 3.12 myenv
uv pip install --python myenv/Scripts/python.exe -e ".[dev,asr-fasterwhisper]"
scripts\dev.bat                       # 启动开发服务器，http://127.0.0.1:11500
```

可选 ASR 引擎按需加：
```bash
uv pip install -e ".[asr-parakeet]"     # 欧语高速档（NeMo，重）
uv pip install -e ".[asr-sensevoice]"   # 中日韩档（FunASR）
```

TTS 需要 Qwen3-TTS Docker：
```bash
cd docker/tts_qwen3
docker compose up -d
```

GPU 模式：装 PyTorch CUDA 版（详见 aistack `docs/selection/runtimes.md`）。

## 3. 验证 aistack 在跑

```bash
curl http://127.0.0.1:11500/health
# {"status":"ok","version":"0.0.1"}

curl http://127.0.0.1:11500/v1/models
# 返回当前可用模型清单
```

如果 `/health` 返回 connection refused，说明 aistack 没启动；VideoCraft 调用时
会收到 `network` kind 的 503 envelope，文案里直接告诉用户怎么启动。

## 4. VideoCraft 端配置（2026-05-07 AI Console 改版后）

打开 **AI Console → Provider & 路由** tab，看到三块（顺序从上到下）：

```
┌─ 功能路由 ──────────────────────────────────────────────────┐
│ 每行带 LLM/ASR/TTS 胶囊标签 + provider 下拉 + 模型下拉      │
└─────────────────────────────────────────────────────────────┘
┌─ 本地模型代理 (aistack) ────────────────────────────────────┐
│ URL + 启用 + 「测试连通 / 刷新模型」按钮 + 状态行            │
└─────────────────────────────────────────────────────────────┘
┌─ 服务商管理 (云端) ─────────────────────────────────────────┐
│ 按 LLM / ASR / TTS 分块；aistack 不在这里                    │
└─────────────────────────────────────────────────────────────┘
```

> 历史上 LLM 列表有 "Ollama" 选项，base_url 指 `localhost:11434/v1`。
> D6 之后该选项被 aistack 取代——aistack 内部代理 Ollama，VideoCraft 不再
> 直连 Ollama。**升级时 providers.json 自动迁移**，无需手动改。

### 4.1 配置 aistack 网关（一处，全局生效）

**网关块只管「怎么连」，不管「用什么模型」**：

| 字段 | 默认 | 说明 |
|---|---|---|
| URL | `http://127.0.0.1:11500/v1` | aistack 服务地址。本机用默认；局域网/云上 aistack 改这里 |
| 启用 | ✓ | 取消勾选后功能路由表的 provider 下拉里隐藏 aistack |

**操作**：
1. 改完 URL → 点「测试连通 / 刷新模型」
2. 状态行显示 `✓ 在线 · 共 N 个模型 (LLM x / ASR y / TTS z)`
3. 测试动作顺手把 `/v1/models` 拉到的列表按 capabilities 切三组缓存到内存
4. 上方功能路由表里 provider 切到 aistack 时，对应类别的 model 下拉自动用
   这份缓存

**注意**：内部仍在 `providers / asr_providers / tts_providers` 三个 registry
里各自登记 aistack 一份（数据模型遗留），但 UI 上**只暴露一个 URL 输入框**，
保存时三处 base_url 同步写入。`/v1` 后缀只在 LLM 那条加，ASR/TTS 那两条
不加（client 模块自己拼路径）。

### 4.2 模型选择（功能路由表）

每行结构：`[胶囊] 任务名 | Provider 下拉 | 模型下拉`。

| 任务 | Provider 下拉行为 | 模型下拉行为 |
|---|---|---|
| `LLM` 翻译 / 字幕后处理 | 列出所有 LLM provider；首项 "自动 (候选池兜底)" → 存空字符串，dispatch 时走 priority fallback | provider 选 aistack 时列 capabilities=llm 的 model；选其他 LLM provider 时列该 provider 配置的 models 列表；选"自动"时下拉禁用 |
| `ASR` 语音转字幕 | 列出所有 ASR provider | provider 选 aistack 时列 `auto + capabilities=asr` 的 model（whisper-small / parakeet / sensevoice / ...）；选其他 ASR provider 时下拉禁用（Lemonfox 单模型） |
| `TTS` 文本转语音 | 列出所有 TTS provider | 同 ASR：选 aistack 时列 `auto + capabilities=tts`；其他禁用 |

**aistack 模型选 "auto" 的语义**：
- ASR：发送 `model=auto` 给 `/v1/audio/transcriptions`，aistack 按 `language=`
  字段做内部路由（zh→sensevoice, en→parakeet, 其他→whisper）
- TTS：当前只有一个 TTS 模型，留 auto 即可
- LLM：**没有 auto** —— 不同 LLM 能力/速度/成本差太大，必须显式选

### 4.3 dispatch 链路

VideoCraft 端的 `task_routing[task].model` 字段会透传到 aistack：

- ASR：`router.asr()` 读 `task_routing.model` → 转发到 `_aistack.transcribe(model_name=...)`
  → aistack `_select_provider` 里的 `auto` 走语言路由，具体 model id 走对应 backend
- TTS：同理，但 `auto`/空时回落到 `tts_providers["aistack"].model` 配置默认
- LLM：openai-compat 标准协议，model id 直接是 OpenAI request body 的 `model` 字段

## 5. 调用流程（开发者视角）

VideoCraft 的 `core/ai/providers/aistack.py` 是 HTTP 客户端：

- ASR 调用 → `core_asr.transcribe_audio(...)` → router 看到 `provider=aistack` →
  `aistack.transcribe()` → POST `/v1/audio/transcriptions` (multipart) → 返回
  Lemonfox-shape verbose_json
- TTS 调用 → 类似，POST `/v1/audio/speech`
- LLM 调用 (D6) → router 看到 `provider=aistack` → POST `/v1/chat/completions`

VideoCraft 端**不需要**：
- 知道 aistack 内部用哪个引擎
- 传 `keep_alive` 参数控制模型驻留
- 调任何 aistack 内部的 cache/unload 端点
- 在 ASR 完成后主动通知 aistack 释放显存以让 LLM 跑

aistack 自己负责本地资源调度——VideoCraft 只发请求收响应。

## 5.1 ASR 时间戳契约（重要）

每个 ASR 请求返回的 verbose_json 必须**同时**包含两层时间戳，缺一不可：

| 层级 | 字段 | 用途 |
|---|---|---|
| 句子级 | `segments[]` | 喂给 `translate_srt.py`，每行 SRT = 一次 LLM 调用，LLM 看到完整句子（时态、指代、从句结构都在），翻译质量靠这个 |
| 单词级 | `words[]` | 留给烧录模块（`core/burn_subs.py` 未来扩展）做按视频画幅的智能字幕分行 |

**`segment_granularity` 不传，让 aistack 走默认 `sentence`**。aistack `docs/api/asr.md` §"Why default to sentence" 明确写了：subtitle 模式给 LLM 翻译会产生破碎语境（half-clauses lose tense and referent），翻译质量会塌——这是不能接受的。

### 为什么客户端**绝不能**做"工业级 SRT 切分"

直觉容易踩坑：看到 50 分钟一行 SRT 不可读，第一反应是切碎。这是错的——`translate_srt.py` 的工作方式是 row-by-row 喂 LLM，**SRT 切多碎，翻译就被破坏多严重**。一旦客户端在 ASR 层 cue-size，下游翻译永远拿不到完整句子。

正确的层级分工是：

```
ASR (aistack)         →  segments[] (句子级) + words[] (单词级)
                         ↓
translate_srt.py       →  按 segments[] 节奏 row-by-row 翻译
                         ↓
burn_subs.py (未来)    →  根据视频画幅 + segments[] + words[] 做工业级分行
                         ↓
ffmpeg burn            →  最终烧录
```

每一层只做一件事，绝不组合。烧录层才知道"这视频是 9:16 还是 16:9"、"字号多大"、"安全区多宽"——也只有这一层做出的分行才工业级。当前 `core/asr.py` 的 SRT writer 是有意"一段一行"，靠 aistack 默认 sentence 切分输出可读性已经够；将来烧录层会用上 `words[]` 做画幅自适应分行。

### 为什么需要单词级时间戳

`words[]` 不是浪费，是给将来的烧录层留的原料：
- 竖屏视频（9:16）字幕条窄，长句要多行折，每行几个词需要按 word 边界对齐
- 卡拉 OK 风格逐字高亮（已有 `tools/subtitle/word_subtitle.py` 在用）
- 强制换行时不能切到词中间，需要 word boundary 对齐
- 现有的 `_verbose_json_to_srt` 切分算法非常粗糙——所有这些缺陷都留给 burn 层用 words[] 解决

当前所有 ASR provider（aistack / Lemonfox）的 `transcribe()` 都满足这个契约——返回 `{language, duration, text, segments[], words[]}` 完整 5 字段。

## 6. 错误处理

aistack 错误用统一信封返回（详见 aistack `docs/api/errors.md`）：

```json
{
  "error": {
    "kind": "network | malformed | overflow | cancelled | unknown",
    "provider": "aistack | Faster-Whisper | Parakeet | ...",
    "message": "..."
  }
}
```

VideoCraft `core/ai/providers/aistack.py` 把它解出来，包成
`AIError(Kind.X, provider, message)`，UI 层照常按 Kind 分支处理。

特殊：HTTP 503 + `Retry-After` header（不是上面信封）→ aistack 在跑别的请求，
回退几秒再试即可。`aistack.py` 客户端识别这种情况，按 Retry-After 自动等待重试
*(实现在 D6 阶段统一)*。

### 常见错误场景

| 情况 | aistack 返回 | VideoCraft 显示 |
|---|---|---|
| aistack 没启动 | connection refused | "aistack service is not reachable. Start it with: cd D:\My_Prjs\dosmoon-aistack && scripts\dev.bat" |
| ASR 选了 parakeet 但 NeMo 没装 | 503 `network` | "NeMo toolkit not installed. Run: pip install nemo_toolkit[asr]" |
| TTS docker 没起 | 503 `network` | "Qwen3-TTS container is not reachable. Start it with: docker compose -f docker/tts_qwen3/docker-compose.yml up -d" |
| 选了不存在的 model id | 400 `malformed` | "Unknown model: 'xxx'. Use whisper-{size}, parakeet, or sensevoice." |
| 同时多个 ASR 调用 | 503 + Retry-After: 5 | (客户端自动重试) |

## 7. 演进路径

aistack 的后端会随时间扩展，**VideoCraft 端不需要任何改动**：

| 阶段 | aistack 后端 | VideoCraft 改动 |
|---|---|---|
| 现在 | 本机 GPU + Ollama + Docker | 一次性配好 base_url |
| 多模型本机调度 | 同上 + GPU-aware eviction | **零** |
| 局域网阶段 | + 局域网 4090 peer | 改 base_url 指向那台机器 |
| 云租用阶段 | + RunPod / Lambda Labs | 改 base_url 指向云端 |

只要 aistack 守住 `/v1/*` API 兼容承诺，VideoCraft 端的代码和配置都不用动。

## 8. 故障排查清单

| 症状 | 检查 |
|---|---|
| AI 任务全部 503 | `curl http://127.0.0.1:11500/health` —— aistack 是否在跑 |
| ASR 报"backend not installed" | 进 aistack 目录跑 `uv pip install -e ".[asr-xxx]"` |
| TTS 卡 60-150 秒后才返回 | 正常的 vLLM-Omni 冷启动，二次调用正常 |
| GPU OOM 崩溃 | 同时跑了多个本地 AI 重负载，且 keep_alive 没让模型释放——参 aistack `docs/selection/runtimes.md` 里的 8GB VRAM 章节 |
| 切换 provider 后 model 下拉空 | 点 "Pick Models" 重新拉清单 |

## 9. 不该做的事

> 把这些原则记下来；项目内部 review 时优先卡这些点。

- ❌ VideoCraft 不要直接调 Ollama (`localhost:11434`)，全部走 aistack
- ❌ VideoCraft 不要直接调 Qwen3-TTS Docker (`localhost:7860/17860`)，全部走 aistack
- ❌ VideoCraft 不要给 aistack 发"keep_alive=0" "unload model" 之类的内部调度 hint
- ❌ VideoCraft 不要假定哪个 ASR 模型在 GPU 上、哪个不在
- ❌ VideoCraft 不要按 aistack 实现细节写代码（比如假设 Parakeet 比 SenseVoice 更耗显存）
- ✅ VideoCraft 仅按 aistack 公开 API doc 写代码

---

## 参考链接

- aistack repo: `github.com/dosmoon/aistack`
- aistack API 文档: `github.com/dosmoon/aistack/tree/main/docs/api/`
- aistack 设计文档: `github.com/dosmoon/aistack/tree/main/docs/design/`
- aistack 运行时: `github.com/dosmoon/aistack/blob/main/docs/selection/runtimes.md`
