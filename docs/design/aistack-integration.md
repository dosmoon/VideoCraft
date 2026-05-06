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

## 4. VideoCraft 端配置

### 4.1 Provider 选项

打开 **AI Console → Providers** tab，看到的 LLM/ASR/TTS provider 列表里
**aistack** 应当作为本地能力的**唯一入口**：

| 类别 | 选项 |
|---|---|
| LLM | Gemini / DeepSeek / Claude / Custom / **aistack** |
| ASR | LemonFox（云）/ **aistack** |
| TTS | Fish Audio（云）/ **aistack** |

> 历史上 LLM 列表有 "Ollama" 选项，base_url 指 `localhost:11434/v1`。
> D6 之后该选项被 aistack 取代——aistack 内部代理 Ollama，VideoCraft 不再
> 直连 Ollama。**升级时 providers.json 自动迁移**，无需手动改。

### 4.2 配置 aistack provider

**唯一必填字段：base_url**

| 字段 | 默认 | 说明 |
|---|---|---|
| `base_url` | `http://127.0.0.1:11500` | aistack 服务地址。本机用默认即可；用局域网/云上 aistack 改这里 |
| `auth_required` | `False` | aistack 默认不带鉴权（仅 localhost） |
| `key_file` | `""` | 不需要 API key |

UI 上点 aistack provider 行的"编辑"按钮，调一行 base_url 即可。
**不要分别为 LLM/ASR/TTS 各填一遍 URL**——一个 aistack 服务覆盖三类。

### 4.3 模型选择（task_routing 矩阵）

打开 **AI Console → Routing** tab，每个 task 选 (provider, model)：

```
Task                Provider    Model
────────────────────────────────────────────
translate           aistack     qwen3:4b           ← LLM 必须显式选
subtitle.post       aistack     qwen3:4b           ← LLM 必须显式选
asr.transcribe      aistack     自动               ← 留空让 aistack 按语种路由
                                whisper-small      ← 或显式选某个 Whisper size
                                parakeet           ← 或欧语强制走 Parakeet
                                sensevoice         ← 或 CJK 强制走 SenseVoice
tts.synthesize      aistack     自动               ← 当前只有 Qwen3-TTS，留"自动"即可
```

**配置要点**：

- **LLM 不能"自动"**——不同 LLM 的能力/速度/成本差太大，VideoCraft 不替你选
- **ASR 可"自动"**——aistack 按 `language=` 字段路由（zh→sensevoice, en→parakeet, 其他→whisper）
- **TTS 可"自动"**——aistack 选当前可用的 TTS 后端

### 4.4 Pick Models 按钮

点 task_routing 单元里的 **"Pick Models"** 按钮：

1. VideoCraft 调 `GET aistack:11500/v1/models`
2. 按当前 task 的 capability 过滤（translate → 只看 capabilities=["llm"]）
3. 把可选 model id 显示在下拉里

如果 aistack 没启动，按钮报"无法连接"，按提示先启动 aistack。
如果 aistack 启动了但缺某个能力（比如没装 Parakeet），那个 model 不在
列表里——`/v1/models` 只列**当前可服务**的模型。

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
