# 本地 AI 闭环 · 阶段进度

**目标**:把 VideoCraft 推广的最大阻碍 —— 必须配云端 API key 才能跑通最小闭环 —— 干掉。

**总览**:

| Phase | 范围 | 推理引擎 | 状态 | Commit |
|---|---|---|---|---|
| **L1** | LLM (翻译/字幕处理/切片排序) | Ollama (MIT) + Qwen3:4b | ✅ 已上线 2026-05-05 | `8823915` |
| **L2.1** | ASR (语音转字幕) 基线 | faster-whisper (MIT) + Whisper small | ✅ 已上线 2026-05-05 | `c1e72f4` |
| **L1.5** | UX 收尾 | — | ✅ 已上线 2026-05-05 | `85db20f` |
| **L2.2** | ASR 高质量档 | Parakeet v3 + SenseVoice 双模型路由 | ⏳ 已锁定方案 | — |
| **L3** | TTS (文本转语音) | 待定 (Qwen3-TTS / Piper) | ⏳ 用户主动暂缓 | — |
| **L4** | 首启自动化 / 一键安装 | — | ⏳ Backlog | — |

---

## L1 — Ollama LLM(已上线)

- **协议链路**:Ollama 自身 MIT,默认拉的 Qwen3:4b Apache 2.0 → 法律链路全干净
- **架构复用**:复用现有 `openai_compatible` provider type(Ollama 暴露 OpenAI 兼容协议在 `localhost:11434/v1`),不新建 provider adapter
- **关键扩展点**:provider config 新增 `auth_required: False` 字段。`config.has_auth()` 短路返回 True,`router._call/_call_json` 用占位 api_key `"ollama"` 调用 OpenAI SDK(本地服务忽略 Bearer 内容)
- **UX**:AI Console Edit 对话框检测 `is_local`,隐藏 API Key 行,加 Health Check 按钮 + Pick Models(走 `/v1/models`)
- **关键文件**:`src/core/ai/{config,router}.py`、`src/tools/router/ai_console.py`

## L2.1 — faster-whisper ASR(已上线)

- **协议链路**:MIT(faster-whisper)+ MIT(Whisper 模型)→ 干净
- **架构复用**:`router.asr()` 加 `elif provider == "faster_whisper"` 分支,跳过 key/base_url 校验。输出 normalize 到 LemonFox 的 `verbose_json` shape (`language/duration/text/segments[]/words[]`),下游零改动
- **关键决策**:`device="auto"` 默认 CPU。CUDA 路径要用户自己装 CUDA 12 Toolkit + cuDNN(否则推理时报 `cublas64_12.dll not found`)。这是 ctranslate2 wheel 的现实问题,不绕
- **语言映射**:适配器内部把显示名 (`"English"` / `"Chinese"` / `"中文"`) 映射回 ISO (`en` / `zh`),因为 faster-whisper 只认 ISO,LemonFox 兼容显示名所以 Speech2Text/ProjectWorkbench 一直传显示名
- **路由修复**:`transcribe_audio()` 之前默认 `provider="lemonfox"` 硬编码,导致 AI Console 改 task_routing 没用。改成 `provider=None` → router 查 `task_routing[asr.transcribe]`
- **enabled 语义对齐**:LLM `_complete_explicit` 不检查 `enabled`,但 ASR/TTS 严格要求 `enabled=True`,造成首次设置后报"provider disabled"。改成 ASR/TTS 也不检查 enabled(显式 task_routing 即视为启用)
- **关键文件**:`src/core/ai/providers/faster_whisper_local.py`(新)、`src/core/{asr,ai/__init__,ai/router}.py`、`src/tools/router/ai_console.py`、`requirements.txt`

**性能基线**:200 秒英文 mp3 / CPU 8 核 / Whisper small → 90 秒(RTF 0.45),100 段 + 611 词级时间戳。中文 20 秒样本 → CPU 9 秒,质量足以识别"霍尔木兹海峡"这种专有名词。

## L1.5 — UX 收尾(已上线)

- **`n/as` 显示问题**:本地 ASR 走专属 `request_summary_local` 事件 + i18n 模板(原 LemonFox 模板硬编码 `{timeout}s` 后缀,本地无超时拼出 "n/as")
- **本地推理过程不再寂静**:Speech2Text 加 5 个本地事件的 log 渲染(`request_summary_local` / `model_loading` / `model_loaded` / `state_processing` / `state_done`),包含按钮态更新("加载模型中…" / "转写中 N段 / Ts")
- **provider 行加 Enable 复选框**:之前只能改 `providers.json` 文件;现在 LLM/ASR/TTS 一致都有
- **README 整合**:两段独立的"本地 Ollama"和"本地 Faster-Whisper"合并成一个**"零云端 Key 配置"**统一章节,带能力矩阵 + 现状表

---

## L2.2 — Parakeet v3 + SenseVoice(下一步,已锁定)

**为什么做**:

- 用户场景以**速度敏感**为主,"标准中文 + 欧语足够,不需要方言"
- 文档对比:
  - 英语场景:Parakeet TDT v3 ~3000 RTFx vs Whisper large-v3-turbo ~250 RTFx → **快 12 倍**,WER 6.32% vs 7.5%(更准)
  - 中文场景:SenseVoice CER ~6-8 vs Whisper large-v3 CER ~14 → **准确率 2 倍领先**,体积小 40 倍

**协议判断**:

- Parakeet TDT v3 → CC-BY-4.0(商用 OK,需署名)→ 干净
- SenseVoice → FunASR Model License → 协议明文允许商用,只有"不得违法 / 不得二次出售权重"两条禁止行为。VideoCraft 是开源自部署工具,**用户从 ModelScope 自己拉权重**,跟 Ollama 拉 Llama 4 / Qwen Plus 同构 → 操作上没问题。**不需要"找法务"**这种企业级动作

**实施轮廓**(明天展开):

1. **依赖**:`pip install nemo-toolkit funasr` —— 体积大(几 GB),需 GPU
2. **Provider entries**(`config.py`):
   - `parakeet_v3`:NeMo,英/西/法/德/俄,~600 MB 模型
   - `sensevoice`:FunASR,中/粤/日/韩,~250 MB 模型
3. **新 Provider Adapters**:
   - `providers/nemo_parakeet.py`:输出 normalize 到 lemonfox shape
   - `providers/funasr_sensevoice.py`:同上
4. **语言路由层**:可以是新建 `providers/language_routed_asr.py` 元 provider,根据语言 hint 或前 N 秒 LID 检测路由到 Parakeet 或 SenseVoice;或者更简单 — 让用户在 AI Console 直接选 `parakeet_v3` 或 `sensevoice`,task_routing 不动
5. **GPU 检测**:Parakeet/SenseVoice CPU 上跑没意义,需要装 CUDA 12 + cuDNN。沿用 L2.1 的 `device="auto"` 默认 CPU + 用户主动选 cuda 模式
6. **AI Console UI**:同 L2.1 的 local ASR Edit 对话框模板,加 Model / Device / Compute Type 等
7. **README**:把"零云端 Key 配置"章节扩成 ASR 子节里的"档位选择"(faster-whisper 基线档 / Parakeet+SenseVoice 高级档)

**预计工程量**:2~3 个工作日。

---

## L3 — TTS 本地化(暂缓)

用户主动暂缓:"TTS 不着急,先放着"。后续选型见 `tts_local_selection_v4.md`,推荐档 Qwen3-TTS 1.7B + Piper 兜底。

## L4 — 首启自动化(Backlog)

GPU 检测、一键安装 Ollama、自动 pull 模型、首启 onboarding 弹窗。当前用户已经能配通,这个等用户反馈再决定优先级。
