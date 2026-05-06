# VideoCraft

> 视频创作者的全套工具箱 —— 下载、转录、翻译、烧录字幕，一站搞定。

[![最新版本](https://img.shields.io/github/v/release/dosmoon/VideoCraft?include_prereleases&label=下载最新版本)](https://github.com/dosmoon/VideoCraft/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)](https://github.com/dosmoon/VideoCraft/releases/latest)

---

## 这是什么？

VideoCraft 是一款面向视频创作者的本地工具集，VS Code 风格界面，将视频处理全流程整合到一个窗口：

**视频下载 → 语音转字幕 → 字幕翻译 → 烧录字幕**

同时提供视频剪辑、音频处理、AI 内容生成等十余种辅助工具。

**无需安装 Python，解压即用（Windows 10/11 x64）。**

---

## ⚡ 无需任何 API Key 即可使用的强大功能

以下功能**完全免费、开箱即用**，无需注册任何账号或填写任何 Key。

> 市面上同类工具（视频剪切、音频提取、字幕烧录等）多以订阅制或按次付费方式提供，VideoCraft 将它们打包在一起，完全免费。

| 功能 | 说明 |
|------|------|
| 📥 **视频下载**（内置 yt-dlp） | 封装业界最强开源下载工具 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，图形界面操作，支持数百个视频平台，无需命令行；可选下载平台原生字幕（subs-only 模式） |
| 🔤 **字幕烧录** | 将 SRT 字幕硬烧到视频，支持字体、颜色、大小、位置等样式配置 |
| ✂️ **按时间戳分割视频** | 按章节时间戳批量切割视频片段 |
| 🔗 **视频拼接** | 多个视频文件合并为一个，支持极速直拼（stream copy）和重编码两种模式 |
| 🎵 **提取 MP3 音频** | 从视频中提取音频，支持 128k / 192k / 256k / 320k 多种码率 |
| 🔊 **调整音量** | 视频/音频音量精确调节（±20dB） |
| 📐 **视频片段提取** | 按时间范围精确截取片段，可同步截取对应字幕 |
| 🔀 **自动均分视频** | 将视频自动分割为指定数量的片段，支持关键帧对齐 |
| 🔄 **MP3 码率转换** | 快速转换 MP3 文件码率 |
| 📝 **提取字幕文字** | 从 SRT 文件一键导出纯文本 |
| 📋 **按时间戳提取段落** | 根据分段文件提取各段落对应字幕内容 |

> ⚠️ **关于视频下载功能的版权声明**
>
> VideoCraft 内置的视频下载功能基于开源项目 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，与 YouTube 及任何其他视频平台**均无关联**。该功能的存在不构成对下载受版权保护内容行为的鼓励或认可。
>
> **使用本功能下载任何内容前，请用户自行确保该行为符合：**
> - 所在国家/地区的法律法规（包括著作权法）；
> - 相关视频平台的服务条款（Terms of Service）；
> - 内容版权方的授权范围。
>
> 用户须对使用本功能产生的一切后果自行承担全部责任。开发者及贡献者不对因使用本功能引发的任何版权纠纷或法律后果负责。

---

## 🤖 绑定 AI Key 后解锁更多强大功能

AI 功能需要用户自行提供对应服务的 API Key（按用量向第三方付费）。**VideoCraft 本身永久免费，不收取任何中间费用。**

| 功能 | 需要的 Key | 说明 |
|------|-----------|------|
| 🎙️ **语音转字幕** | Lemonfox | 音视频文件自动生成 SRT 字幕，支持 40+ 语言 |
| 🌐 **字幕翻译** | Gemini / Groq / DeepSeek（任选其一）| 将 SRT 字幕翻译为任意语言 |
| 📌 **生成视频分段** | Gemini | 根据字幕自动生成时间戳+标题分段 |
| ✨ **精炼分段描述** | Gemini | AI 优化分段标题的表达质量 |
| 🏷️ **生成视频标题** | Gemini | 基于字幕内容生成吸引眼球的标题 |
| 🗣️ **文字转视频** | Gemini + Google Cloud TTS | 文本合成语音并生成视频 |

---

## 📦 下载与安装

### 第一步：下载 VideoCraft

前往 **[Releases 页面](https://github.com/dosmoon/VideoCraft/releases/latest)**，下载最新版本的 `VideoCraft-portable-vX.X.X.zip`。

### 第二步：解压

解压到任意目录，**路径中不要包含中文或空格**：

| | 示例 |
|---|---|
| ✅ 正确 | `D:\Tools\VideoCraft` |
| ✅ 正确 | `C:\VideoCraft` |
| ❌ 错误 | `D:\我的工具\VideoCraft`（含中文） |
| ❌ 错误 | `D:\My Tools\VideoCraft`（含空格） |

### 第三步：安装 FFmpeg（必需）

VideoCraft 的视频处理功能依赖 [FFmpeg](https://ffmpeg.org)，需要单独安装：

1. 前往 [FFmpeg Builds](https://github.com/BtbN/FFmpeg-Builds/releases) 下载 `ffmpeg-master-latest-win64-gpl.zip`
2. 解压后，将其中的 `bin` 目录完整路径添加到系统环境变量 `PATH`

**验证安装**：打开命令提示符，输入以下命令，看到版本号即表示成功：
```
ffmpeg -version
```

### 第四步：启动

双击解压目录中的 **`VideoCraft.bat`**，主界面启动。

---

### 🔑 配置 API Key（可选，解锁 AI 功能）

在解压目录的 `keys\` 文件夹下，新建对应的文本文件，将 API Key 粘贴为文件内容保存即可：

| 文件名 | 获取地址 | 对应功能 |
|--------|---------|---------|
| `lemonfox.key` | [lemonfox.ai](https://lemonfox.ai) | 语音转字幕 |
| `Gemini.key` | [aistudio.google.com](https://aistudio.google.com) | 翻译 / 分段 / 标题生成（有免费额度） |
| `Groq.key` | [console.groq.com](https://console.groq.com) | 翻译备用（**免费额度较多，推荐入门**） |
| `DeepSeek.key` | [platform.deepseek.com](https://platform.deepseek.com) | 翻译备用（价格极低） |

> 💡 翻译功能只需配置一个 Key 即可，推荐先用 **Groq**（免费额度充足）或 **Gemini**。
> Key 文件内容只需一行，粘贴 Key 字符串保存即可。

---

### 🆓 零云端 Key 配置(纯本地 AI)

如果你**不想申请云端 Key**,或希望数据完全本地处理、断网也能跑,可以用本地推理引擎替代云端 API。当前覆盖 **LLM(翻译 / 字幕处理 / 切片排序)** 和 **ASR(语音转字幕)** 两类任务,**整条主闭环零云端 key**(TTS 配音仍依赖云端,后续补齐)。

**通用原则**:首次启动后在 **Tools → AI Console** 切换 provider,主界面 **Task Routing** 把对应任务行改路由到本地 provider 即可。无需重启。

#### 📚 LLM 走本地 Ollama

引擎:[Ollama](https://ollama.com)(MIT,商用安全)。

1. 从 [ollama.com](https://ollama.com) 下载安装(Windows / macOS / Linux 一键)
2. 命令行拉模型(推荐 Qwen3-4B,Apache 2.0,~2.5 GB,3 GB 显存即可):
   ```bash
   ollama pull qwen3:4b
   ```
3. **AI Console → Providers → Ollama → Edit**:无需填 Key,点 **健康检查** 验证连通,点 **刷新并选择…** 勾上模型,**保存**
4. Providers 行勾上 **启用**
5. **Task Routing** → `translate` / `subtitle.post` 等行 → Provider 改为 **Ollama**,Model 选 `qwen3:4b`

#### 🎙️ ASR 本地引擎选型

VideoCraft 内置三个本地 ASR 引擎,定位互补,可在 AI Console 按语言路由共存:

| 引擎 | 强项 | 弱项 | 速度 (CPU, 200s 音频) |
|---|---|---|---|
| **Parakeet TDT v3** (NeMo) | 英语 / 25 种欧洲语言:精度高,段落切分自然,做字幕直接可用 | 不支持中日韩阿等亚洲语言 | **~13 秒** (RTF 0.065) |
| **SenseVoice** (FunASR) | 中文(普通话/粤语) / 日 / 韩 / 英;非自回归速度快 | 无 word 级时间戳(段落级 OK,做字幕够用) | 约 Parakeet 量级 |
| **Faster-Whisper** | 99 种语言全覆盖,小语种唯一选择 | 英语精度劣于 Parakeet,small 档常见专业词错误 | small ~90 秒, large-v3-turbo ~5 分钟 |

**推荐路由**:
- 英语 / 欧洲语言 → **Parakeet**(`asr.transcribe` 行点 🌐 Lang,添加 `en→parakeet`,勾 Enable)
- 中文 / 粤语 / 日韩 → **SenseVoice**(`zh→sensevoice`,`ja→sensevoice` 等)
- 其他小语种 → Faster-Whisper(`auto` 默认 provider)

#### 🎙️ ASR 走本地 Parakeet TDT v3 (欧语高质量档)

引擎:[NVIDIA NeMo Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)(CC-BY-4.0,商用允许)。

1. 已在 `requirements.txt`,正常 `pip install -r requirements.txt` 即可(NeMo 装包较大,首次约 2~3 GB)
2. **AI Console → Providers → Parakeet TDT v3 → 启用**
3. **Task Routing** → `asr.transcribe` 行 → 点 **🌐 Lang** → "+ 添加" → 第一栏选 `en`(及其他需要的欧洲语言)→ 第二栏选 `parakeet` → 关闭弹窗 → 勾上行内 **Enable** 复选框激活语言路由

**首次跑**:模型自动下载到 `<repo>/user_data/models/hf/hub/`(~1.2 GB),Portable 自包含,之后完全离线。

#### 🎙️ ASR 走本地 SenseVoice (中日韩档)

引擎:[Alibaba FunASR + SenseVoiceSmall](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)(模型 MIT,SDK Apache 2.0,商用允许)。

1. 已在 `requirements.txt`,正常安装即可
2. **AI Console → Providers → SenseVoice → 启用**
3. **Task Routing** → `asr.transcribe` 行 → 点 **🌐 Lang** → 添加 `zh→sensevoice` / `ja→sensevoice` / `ko→sensevoice` / `yue→sensevoice` 等 → 关闭 → 勾 **Enable**

**首次跑**:模型自动下载到 `<repo>/user_data/models/modelscope/`(~900 MB,从阿里云 ModelScope 拉取,国内速度极快),之后完全离线。

**注意**:SenseVoice 不输出 word 级时间戳(段落级时间戳通过 fsmn-vad 切分获得),做 SRT 完全够用,但若需要逐字时间轴(精校字幕)请用 Whisper 系列。

#### 🎙️ ASR 走本地 Faster-Whisper (通用 / 小语种兜底)

引擎:[faster-whisper](https://github.com/SYSTRAN/faster-whisper)(MIT, CTranslate2 后端,99 种语言)。

1. 已在 `requirements.txt`
2. **AI Console → Providers → Faster-Whisper (本地) → Edit**:选模型尺寸 / 设备 / 计算精度,**保存**

   | 尺寸 | 体积 | CPU 速度 | 质量 |
   |---|---|---|---|
   | `tiny` | 75 MB | 极快 | 一般 |
   | `base` | 145 MB | 快 | 中等 |
   | `small` | 244 MB | 较快 | **小语种推荐** |
   | `medium` | 770 MB | 中等 | 较高 |
   | `large-v3-turbo` | 1.5 GB | 较慢 | 高 |
   | `large-v3` | 3 GB | 慢 | 最高 |

3. **设备**:保持 `auto`(= CPU)即可。**`cuda` 需要本机已装 CUDA 12 Toolkit + cuDNN**,否则推理时报 `cublas64_12.dll not found`
4. Providers 行勾上 **启用**
5. **Task Routing** → `asr.transcribe` 行 → Provider 改为 **Faster-Whisper (本地)** 作为默认兜底

**首次跑**:模型自动下载到 `<repo>/user_data/models/hf/hub/`,之后完全离线。

#### 📁 模型缓存目录

VideoCraft 默认把所有本地模型下载到 `<repo>/user_data/models/`(Parakeet / faster-whisper / 其他 HF 系):
- 内置目录,Portable 整包带走零外部依赖
- 想多 app 共享(LM Studio / ComfyUI 等):AI Console → 本地模型缓存 → 改成共享目录(如 `D:\AI_Models`),重启 VideoCraft 生效
- **Ollama 例外**:Ollama 自己管模型,需在 Windows 系统环境变量里设 `OLLAMA_MODELS`(AI Console 提供一键打开按钮)

#### ✅ 现在闭环里还剩什么云端依赖?

| 任务 | 本地方案 | 云端兜底 |
|---|---|---|
| 翻译 / 字幕处理 / 切片排序 | ✅ Ollama | Gemini / DeepSeek 等 |
| 语音转字幕 (ASR) | ✅ Parakeet (欧语) + SenseVoice (中日韩) + Faster-Whisper (兜底) | LemonFox |
| 文本转语音 (TTS) | ⏳ Phase L3 计划中 | Fish Audio |
| 联网下载视频 | n/a | n/a (yt-dlp 本地) |

---

## 🗺️ 功能介绍

### 主界面

VS Code 风格布局：**左侧文件浏览器** + **顶部菜单栏** + **右侧工具区**。

在左侧文件浏览器中右键点击视频、音频或 SRT 文件，可快速调用对应处理工具，无需手动选择文件路径。

---

### 核心工作流：视频 → 双语字幕视频

**方式一：项目工作台（推荐）—— 一站式跑完**

菜单 → **项目 → 项目工作台**：新建项目后填入视频链接，按顺序点击 step1 下载 → step2 段落拣选 → step3 ASR/翻译/烧录，全流程在同一窗口跑完，中途可随时取消。

**方式二：右键单步操作（适合零散文件）**

```
① 下载视频      菜单 → 下载 → 粘贴视频链接
② 语音转字幕    右键视频文件 → 语音转字幕         （需 Lemonfox Key）
③ 翻译字幕      右键 SRT 文件 → 翻译字幕          （需翻译 Key）
④ 烧录字幕      右键 SRT 文件 → 烧录到视频
```

---

### 切片稿工作台

菜单 → **项目 → 切片稿**：以"章节为中心"的剪辑稿编辑器，从已下载的视频/字幕生成 AI 章节排序，挑选要保留的章节，再批量导出短切片。支持加载草稿、AI 章节排序持久化、tri-state AI 叠加（标题精炼 / 排序 / 预设），适合做长视频拆条。

---

### 视频工具

| 工具 | 入口 | 说明 |
|------|------|------|
| 视频下载 | 菜单 → 下载 | 内置 yt-dlp，支持数百平台 |
| 提取 MP3 | 菜单 → 视频 → 提取 MP3 | 从视频/音频中提取 MP3 |
| 调整音量 | 菜单 → 视频 → 调整音量 | ±20dB 精确调节 |
| MP3 码率转换 | 菜单 → 视频 → 码率转换 | 快速转换码率 |
| 视频片段提取 | 菜单 → 视频 → 片段提取 | 按时间范围截取，可同步截取字幕 |
| 自动均分视频 | 菜单 → 视频 → 自动分割 | 均分为指定段数，支持关键帧对齐 |
| 按时间戳分割 | 菜单 → 视频 → 视频分段 | 按章节时间戳批量切割 |
| 视频拼接 | 菜单 → 视频 → 视频拼接 | 多文件合并，支持 stream copy 直拼与重编码两种模式 |
| 字幕烧录 | 菜单 → 视频 → 字幕烧录 | 硬烧 SRT 字幕到视频 |

---

### SRT 字幕工具

| 工具 | 说明 | 需要 Key |
|------|------|:-------:|
| 提取字幕文字 | 导出 SRT 为纯文本（`AllSubtitles.txt`） | — |
| 按时间戳提取段落 | 提取各段落对应字幕内容 | — |
| 语音转字幕 | 音视频自动转录为 SRT | Lemonfox |
| 字幕翻译 | 将 SRT 翻译为目标语言 | 翻译 Key |
| 生成视频分段 | AI 生成时间戳 + 标题 | Gemini |
| 精炼分段描述 | AI 优化分段标题 | Gemini |
| 生成视频标题 | AI 生成吸引眼球的标题 | Gemini |

---

### AI 路由配置

菜单 → **AI → Router Manager** 可配置各 AI 提供商的优先级和质量档位（Premium / Standard / Economy）。系统按优先级自动选择可用模型，主力不可用时自动切换备用，无需手动干预。所有 AI 任务均支持中途取消，错误信息按统一契约提示。

### AI Console Playground

菜单 → **AI → Console Playground**：内置的 prompt 调试工具，支持加载/保存测试样本（fixtures）、A/B 对比不同 prompt 与模型档位的输出，便于在写入到生产前先验证效果。

---

## 📄 License

本项目采用 [MIT License](LICENSE) 发布，您可以在协议许可的范围内自由使用、复制、修改、分发本软件。

> **关于贡献**：本项目目前**不接受外部 Pull Request 或代码贡献**。作者保留对本仓库的全部处置权（包括但不限于功能取舍、版本节奏、分支策略与未来商业化方向）。如发现 bug 或有功能建议，欢迎通过 Issue 反馈，但是否采纳由作者自行决定。

> **关于 Fork**：MIT 协议授予的权利不受上述贡献政策影响。您完全可以 Fork 本仓库自行维护、修改、再分发，只要保留原始版权声明与协议文本即可。但请注意：
> - "VideoCraft" 名称不在 MIT 授权范围内，作者保留对该名称的使用权，Fork 版本请使用其它名称发布，避免与官方版本混淆；
> - 作者不对任何 Fork 版本的功能、安全性或维护状态负责。
