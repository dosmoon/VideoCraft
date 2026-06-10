# aistack upstream feature request — segment-level SSE for ASR

> **ARCHIVED 2026-05-08 — never filed.** Upstream shipped this feature
> independently before we submitted. The shipped contract differs from
> the draft below; consult `dosmoon-aistack/docs/api/integration.md` §4
> for the authoritative shape:
>
> - Trigger is the form field `stream=true`, not the `Accept: text/event-stream`
>   header we proposed.
> - Event types are OpenAI-aligned: `transcript.text.delta` /
>   `transcript.text.done` (not our `segment` / `done`).
> - A `warning` event was added for backends that don't natively stream
>   (e.g. Parakeet) — they emit one warning + one full-text delta + done.
> - `/v1/models` exposes `supports_streaming` per entry instead of the
>   suggested `recommended_chunk_sec`.
> - Slot-busy 503 now uses the unified error envelope (adjacent ask #2 — accepted).
>
> VideoCraft client adapted on 2026-05-08; see
> `src/core/ai/providers/aistack.py` (`_consume_sse_transcription`).

Drafted 2026-05-07. Bilingual (中文 / English). Paste either half into a
GitHub issue against `dosmoon/aistack` when ready.

Status: not yet filed. Waiting for tomorrow's aistack-side test results
before submitting, in case the dev there has already started something
adjacent.

Source motivation: VideoCraft hit the wall going from 17min → 1h+ video
ASR. The three problems are concrete and observable; the proposal is the
minimum surface that fixes all three at once.

---

## 中文版

**Title**: ASR: 段级 SSE 流式输出 / Segment-level SSE streaming for ASR

### 背景

我在 VideoCraft 里用 aistack 跑长视频字幕。当前契约是 `POST /v1/audio/transcriptions` 阻塞返回完整 JSON，对短音频（< 20 min）没问题，但扩展到 1 小时以上时遇到三个具体问题：

1. **不可见**：客户端发出请求后到结果返回之间完全静默，用户无法判断 server 是否还活着，体验上等同卡死。
2. **不可中断**：跑了 30 分钟发现配置错了（语言、模型），只能 kill 进程，已经消耗的 GPU 时间和带宽全部浪费。
3. **不可恢复**：一旦请求失败（网络抖动、server OOM、本地磁盘满），所有已完成的 segment 全部丢失，必须从头重跑。

按 `docs/api/integration.md`，cancel/progress 都没有针对 ASR 的方案，LLM 那条 "close stream → TCP RST → 释放 slot" 也不保证适用 ASR。

### 提议：段级 SSE 流式 ASR

```http
POST /v1/audio/transcriptions
Accept: text/event-stream
```

每当一个 segment 解码完成，server 推一个事件：

```
data: {"type": "segment", "start": 12.4, "end": 18.7, "text": "...", "language": "zh"}
data: {"type": "segment", "start": 18.7, "end": 24.1, "text": "..."}
...
data: {"type": "done", "language": "zh", "duration": 3600.0}
```

错误用现有信封：

```
data: {"type": "error", "error": {"kind": "...", "provider": "...", "message": "..."}}
```

向后兼容：客户端不发 `Accept: text/event-stream` 时维持现有阻塞 JSON 行为不变。

### 为什么是 SSE 而不是 job 模式

一条特性同时解决三个问题：
- **进度**：客户端按 `end / duration` 自己算百分比，server 不必算
- **取消**：客户端关连接，沿用你文档里 LLM 流式那条 "TCP close → 释放 slot" 的现成约定，不需要新端点
- **可恢复**：消费者收一段落一段盘，崩了不丢

相比 `POST /jobs` + `GET /jobs/{id}` + `DELETE /jobs/{id}` 的三端点 job 模式，SSE 与 `/v1/chat/completions` 现有流式契约同构，文档/客户端心智模型可以复用。

### 后端兼容性

不同 ASR backend 流式能力不一样。建议契约定为 **segment-level**（不是 token-level），以便覆盖：

| Backend | 能力 |
|---|---|
| faster-whisper / whisper.cpp | 原生 segment iterator |
| parakeet | 分段后逐段推 |
| senseVoice | 一次性输出，可由 aistack 用 VAD/固定窗口预切后逐段推 |

后端差异藏在 aistack 内部，客户端契约统一。

### 同时建议（不强求，可单开 issue）

1. **`/v1/models` 的 ASR 条目加 `recommended_chunk_sec` 字段**：客户端在长音频时可主动 VAD 预切并复用 503/Retry-After 重试逻辑。
2. **错误信封统一**：当前裸 503（slot lock）走 FastAPI stock detail 而非 `{error: {kind, provider, message}}` 信封，消费者必须写两套兜底解析。建议统一。

### 不在本 issue 范围内

- 取消端点（`DELETE /jobs/{id}`）—— stream-close 已够
- 服务端进度百分比字段 —— 客户端能算
- token-level streaming —— 价值有限，复杂度高

---

## English version

**Title**: ASR: Segment-level SSE streaming for ASR

### Context

I'm consuming aistack from VideoCraft to transcribe long videos. The current contract — `POST /v1/audio/transcriptions` with a blocking JSON response — works fine under 20 minutes, but at 1h+ I hit three concrete problems:

1. **Opaque**: between request send and response return there's no signal at all. The user can't tell whether the server is still alive; effectively indistinguishable from a hang.
2. **Uninterruptible**: realizing 30 minutes in that the config is wrong (language, model) leaves no option but `kill -9`, wasting all GPU time spent so far.
3. **Unrecoverable**: any mid-flight failure (network blip, server OOM, client disk full) loses every segment decoded up to that point. Full restart from zero.

Per `docs/api/integration.md`, neither cancel nor progress is specified for ASR. The LLM "close stream → TCP RST → release slot" path is documented but not promised for ASR.

### Proposal: segment-level SSE for ASR

```http
POST /v1/audio/transcriptions
Accept: text/event-stream
```

One event per decoded segment:

```
data: {"type": "segment", "start": 12.4, "end": 18.7, "text": "...", "language": "zh"}
data: {"type": "segment", "start": 18.7, "end": 24.1, "text": "..."}
...
data: {"type": "done", "language": "zh", "duration": 3600.0}
```

Errors use the existing envelope:

```
data: {"type": "error", "error": {"kind": "...", "provider": "...", "message": "..."}}
```

Backwards compatible: clients that omit `Accept: text/event-stream` keep getting the current blocking JSON.

### Why SSE, not a job pattern

One feature, three wins:
- **Progress**: client computes `end / duration` itself; server doesn't need to.
- **Cancel**: client closes the connection — reuses the documented "TCP close → slot released" pattern from LLM streaming. No new endpoints.
- **Recoverable**: consumers persist segments as they arrive; a crash loses only the in-flight one.

Versus a `POST /jobs` + `GET /jobs/{id}` + `DELETE /jobs/{id}` triplet, SSE is isomorphic to the existing `/v1/chat/completions` streaming contract — docs and client mental model carry over.

### Backend compatibility

ASR backends vary in native streaming support. Locking the contract at **segment level** (not token level) keeps it portable:

| Backend | Capability |
|---|---|
| faster-whisper / whisper.cpp | Native segment iterator |
| parakeet | Push per segment after chunk completes |
| senseVoice | Inherently one-shot — aistack pre-chunks via VAD/fixed window and pushes |

Backend differences stay inside aistack; the client contract stays uniform.

### Adjacent asks (separable, file separately if you prefer)

1. **`recommended_chunk_sec` on each ASR entry in `/v1/models`** — lets clients VAD-pre-chunk for long audio and ride the existing 503/Retry-After retry path.
2. **Unified error envelope**: bare 503 from the slot lock currently uses FastAPI's stock `{detail: ...}` rather than `{error: {kind, provider, message}}`. Forces consumers to write two parsers. Suggest unifying.

### Out of scope for this issue

- Dedicated cancel endpoint (`DELETE /jobs/{id}`) — stream-close suffices.
- Server-side progress percentage field — client can derive.
- Token-level streaming — limited payoff, high complexity.
