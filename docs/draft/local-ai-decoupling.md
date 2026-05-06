# 本地 AI 服务化解耦设计草稿

> Status: **草稿 / 讨论中**
> Created: 2026-05-06
> Owner: VideoCraft 主仓 + 待建的独立 repo
> 关联记忆: `project_local_ai_phase.md` `project_local_tts_docker.md` `refactor_architecture.md`

---

## 1. 背景与动机

经过本地 AI 闭环 L1~L3 三个阶段（Ollama LLM / faster-whisper-Parakeet-SenseVoice ASR / Qwen3-TTS via vLLM-Omni），事实已经证明：

1. **三类模型都是"重资产"**——动辄数 GB 权重、需要 CUDA、需要 Docker（vLLM-Omni）
2. **三类模块在事实上都已经是"外部服务"形态**：
   - Ollama 自己跑 service，VideoCraft 是 HTTP client
   - faster-whisper / Parakeet / SenseVoice 虽然 in-process 加载，但权重大到不可能塞 portable zip
   - Qwen3-TTS + vLLM-Omni 直接是 Docker 容器
3. **继续耦合在 VideoCraft 主仓有三大代价**：
   - 拖垮 portable 绿色化（P1 backlog）—— zip 体积爆炸
   - 拖垮 VideoCraft 主仓迭代节奏 —— 模型升级 = 主仓发版
   - 阻碍跨形态复用 —— Phase 商业产品也要用同样的 AI 能力

## 2. 决策

**把"本地 AI 闭环"独立成一个 repo，定位为 localhost 后台服务，VideoCraft 退回纯 HTTP 消费方。**

### 2.1 基础事项（已定）

- 新 repo 归属：`dosmoon` 组织
- 新 repo 名称：**`aistack`**（URL: `github.com/dosmoon/aistack`）
- 协议形态：**OpenAI API 兼容**（`/v1/audio/transcriptions`、`/v1/audio/speech`），流式走 SSE
- 默认端口：**`127.0.0.1:11500`**（避开 Ollama 11434）
- 开源策略：MIT 开源（本质是开源模型的胶水层，无独占价值；Phase 闭源照样能调用）

### 2.2 范围边界

aistack 的定位是 **「填补开源模型有了、但没有像 Ollama 那样开箱即用服务框架的空白」**。

- ✅ 入选：ASR（faster-whisper / Parakeet / SenseVoice）、TTS（Qwen3-TTS via vLLM-Omni）
- ❌ 不做：LLM（Ollama 已有完美方案，不重复造轮子；VideoCraft 的 LLM provider 直接指向 `localhost:11434/v1`）
- 🔮 未来可扩：本地视频生成、本地 vision-language 等社区无标准 server 的场景

### 2.3 命名约定

| 出现场合 | 写法 |
|---|---|
| **软件主窗口标题栏** | `dosmoon-aistack` |
| README 标题、文档正文、commit message | `aistack` |
| Repo URL | `github.com/dosmoon/aistack` |
| Python 包名 / import | `aistack`（子包：`aistack.asr` / `aistack.tts` 等） |
| Portable / 安装包文件名 | `aistack-portable-vX.X.X.zip` |
| 启动脚本 / 进程名 | `aistack.bat`、`aistack` |
| 日志、错误信息、CLI | `aistack` |

> 原则：**`dosmoon-` 前缀是「运行时品牌标识」，仅出现在用户视觉触达的 UI 上**；文档、代码、URL、文件名、社区交流一律裸名。VideoCraft 未来同此约定（标题栏 `dosmoon-VideoCraft`，其他不变）—— 单独工作项，不和本次拆分混做。

## 3. 协作模型（VideoCraft ↔ 新服务）

### 3.1 核心原则：**完全照搬 Ollama 模式**

> VideoCraft 启动时不 care 服务在不在；用到 AI 功能时按需探活，不在就给友好提示+引导，在就直接用。

### 3.2 发现服务

- 默认 base_url = `http://127.0.0.1:11500`
- VideoCraft 配置文件允许覆盖 base_url（高级用户/Phase 商业版可指向远端）
- 服务侧暴露 `/health` 或 `/v1/models` 端点用于探活

### 3.3 生命周期：**完全不管**

- 服务自带 launcher（双击 .bat / docker-compose up / systray app）
- VideoCraft **不**尝试启动它，**不**捆绑安装
- 这是"解耦"的关键红线 —— 一旦 VideoCraft 代管服务生命周期，解耦就破功

### 3.4 优雅降级（重要 UX）

- 涉及 AI 的入口（ASR / TTS / 翻译）进入时探活一次
- 服务未运行：弹窗"本地 AI 服务未运行" + [去下载安装] / [查看说明] 按钮，跳新 repo 的 README
- 服务运行但模型未装：服务返回结构化错误，VideoCraft 透传 + [打开模型管理器] 按钮（管理器是新 repo 的 web UI 或独立窗口，不是 VideoCraft 的）

### 3.5 配置职责划分

| 配置类型 | 归属 |
|---|---|
| 服务端：哪些模型、用什么后端、显存策略、容器编排 | **新 repo** |
| 客户端：base_url、超时、当前选用的模型名 | **VideoCraft** |

## 4. 边界划分（搬走 vs 留下）

### 4.1 留下（VideoCraft / 客户端逻辑）

| 文件 | 行数 | 角色 |
|---|---|---|
| `core/ai/router.py` | 863 | 编排/分发，仅需改 local provider 分支为 HTTP 调用 |
| `core/ai/config.py` | 462 | provider 配置注册表，新增 `local_ai_stack` 条目 |
| `core/ai/errors.py` | 235 | 错误类型，跨边界复用 |
| `core/ai/cancellation.py` `stats.py` `tiers.py` | 124 | 纯 client 侧逻辑 |
| `core/ai/providers/openai_compat.py` | 121 | **关键**——已是 OpenAI 兼容 client，直接复用 |
| `core/ai/providers/{claude_code,fish_audio,gemini,lemonfox}.py` | 731 | 云 API client，本来就是 HTTP |
| `core/tts.py` 等业务层 | - | 业务编排，走 router 不变 |

合计 **~2500 行原地不动**。

### 4.2 搬走（进新 repo）

| 文件 | 行数 | 内容 |
|---|---|---|
| `providers/faster_whisper_local.py` | 260 | `from faster_whisper import WhisperModel` 加载器 |
| `providers/parakeet_local.py` | 275 | NeMo 加载 + 16k 重采样 |
| `providers/sensevoice_local.py` | 549 | FunASR + VAD + 标点切片 |
| **L3 Qwen3-TTS / vLLM-Omni 资产** | TBD | docker-compose / 配置 / 启动脚本全套 |

合计 **~1084 行 + L3 资产**。

### 4.3 灰色地带（待讨论）

- **`core/paths.py` 中的模型路径常量** —— 如有指向本地权重的常量需梳理
- **`providers/_json_utils.py` (47 行)** —— 若被 local providers 独占用，跟着走
- **i18n 字符串**（zh.json / en.json）—— "本地 Whisper 已就绪"等需重写为"本地 AI 服务未运行/已就绪"，双语同步
- **Prompt hub / AI 业务编排**（翻译、改写）—— 倾向**留在 VideoCraft**（产品逻辑而非模型能力）
- **模型下载器 / 版本管理 UI** —— 进新 repo

## 5. 迁移路径

### Phase D1：新 repo 起步（不影响 VideoCraft）

1. 在 `dosmoon` 组织建仓
2. 把 L3 Qwen3-TTS / vLLM-Omni 资产作为第一块基石
3. 起一个最小可用的 OpenAI 兼容 HTTP server 骨架（FastAPI）
4. 写 launcher（先 .bat / docker-compose，后期可以加 systray）

### Phase D2：搬迁 ASR 三个本地 provider

1. 把 `faster_whisper_local.py` / `parakeet_local.py` / `sensevoice_local.py` 拷到新 repo
2. 包装成 `/v1/audio/transcriptions` 端点（带 provider 路由参数）
3. 在 VideoCraft 这边新增 `local_ai_stack` provider（复用 openai_compat），跑通端到端
4. **保留旧 in-process 路径作为 fallback**，灰度切换

### Phase D3：物理删除 + 文档更新

1. 确认新服务稳定后，从 VideoCraft 物理删除 3 个 `*_local.py`
2. 删除 `requirements.txt` 里的 `faster-whisper` / `nemo_toolkit` / `funasr` 等重型依赖
3. 更新 i18n 字符串
4. 更新 README、portable build 流程
5. portable zip 体积应有显著下降（量化目标待测）

## 6. 关键决议（2026-05-06 定稿）

| # | 议题 | 决议 | 关键理由 |
|---|---|---|---|
| 1 | Repo 名 / 命名约定 | `github.com/dosmoon/aistack`；产品名 `aistack`；UI 标题栏 `dosmoon-aistack` | 短 URL、品牌前缀仅作运行时标识；详见 §2.3 |
| 2 | 默认端口 | `127.0.0.1:11500` | 避开 Ollama 11434；落 IANA 未分配区好记 |
| 3 | 统一 gateway | **阶段一不做**，单 FastAPI 进程内分发 ASR/TTS | YAGNI；等显存吃不下、需要拆容器再加 |
| 4 | LLM 是否包 | **不包**，aistack 只做 ASR + TTS | Ollama 已有完美方案；详见 §2.2 |
| 5 | 模型管理 UI | 阶段一：**Web UI**（FastAPI `/admin`，HTMX/Jinja，零前端构建）+ **CLI**；不做桌面 app / systray | 跨平台零成本；后期可升级到 Tauri/Electron |
| 6 | L3 Tier 测试 | **直接在新 repo 内做**，不在 VideoCraft 内补完 | 测试代码顺手在 D1 阶段写，结果直接是 aistack 性能基线 |

## 7. 风险与备注

- **跨进程取消语义**：VideoCraft 的 `cancellation.py` 是 in-process 的，跨 HTTP 后取消怎么传递（HTTP request abort? 自定 cancel 端点?）需要专门设计
- **流式响应延迟**：本地 in-process 调用 0 延迟，HTTP 加 SSE 后会引入小幅 overhead，对 ASR 实时场景需测
- **错误类型穿透**：`AIError(Kind.X)` 需要序列化跨 HTTP 边界，client 侧再还原；errors.py 可能需扩展
- **部署门槛上升**：用户从"装 VideoCraft"变成"装 VideoCraft + 装 AI 服务"，需要靠 launcher / 安装引导补回 UX

---

> 后续推进基于本草稿。讨论结论直接 in-place 修订；定稿后改名 `local-ai-decoupling.md` 移出 draft 或转为正式 design doc。
