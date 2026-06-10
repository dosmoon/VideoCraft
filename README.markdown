# VideoCraft

> 一台「剪辑师是 AI」的节目生成器 —— 把一条源视频，做成成片或一批短视频。
> A program generator where the editor is AI — turn one source video into a finished video or a batch of short clips.

[![Release](https://img.shields.io/github/v/release/dosmoon/VideoCraft?include_prereleases&label=download)](https://github.com/dosmoon/VideoCraft/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-lightgrey)](https://github.com/dosmoon/VideoCraft/releases/latest)

📖 **Docs / 文档**: [dosmoon.com/VideoCraft](https://dosmoon.com/VideoCraft/) · [中文站](https://dosmoon.com/VideoCraft/zh-cn/)

**[中文](#中文) · [English](#english)**

<!-- TODO: add a main-window screenshot here -->

> ⚠️ 早期阶段 / Early stage — `0.x`，功能持续演进，欢迎试用与反馈。

---

## 中文

### ✨ 这是什么

VideoCraft 是一款 **Windows 桌面应用**，工作流是：

> **新建项目 → 添加素材（源视频 + 字幕 + 章节）→ 生成创作（切片 / 新闻编导视频）**

ffmpeg 已随包，**核心出片功能开箱即用，无需任何账号或 API Key**。AI（语音转字幕 / 翻译 / 分析）是可选的调味层，可用本地模型、自建服务或自己的云端 Key，三档任选。

### 📦 下载与安装

1. 前往 **[Releases 页面](https://github.com/dosmoon/VideoCraft/releases/latest)**，下载 `VideoCraft-<版本>-setup.exe`。
2. 双击运行安装程序：**免管理员**，安装到当前用户目录（`%LOCALAPPDATA%\Programs\VideoCraft`），数据就放在程序旁边（绿色、可整体搬走）。
3. ⚠️ **安装包暂未做数字签名**（早期阶段）：Windows SmartScreen 首次可能提示「Windows 已保护你的电脑」→ 点 **「更多信息」→「仍要运行」** 即可。源码开放，可自行核验。
4. **ffmpeg 已内置**，无需另行安装或配置 PATH。首次运行的可选引导下载（yt-dlp 运行时 / 本地 AI 模型 / GPU 加速）**都可以跳过**，不影响核心功能。

**系统要求**：Windows 10 / 11，64 位。

### 🚀 快速上手

1. **新建项目**。
2. 添加 **「新闻视频」素材**：粘贴视频链接（内置 yt-dlp 下载）或选择本地文件；可选裁到指定时间段。
3. **字幕**：一键 **ASR 语音转字幕** / **导入 SRT** / **翻译** / **质检并自动修复**。
4. （可选）整理 **章节**，或填 **AI 新闻背景**（主持人、事件、要点等 15 字段，可让 AI 联网补全后人工校正）。
5. **生成创作出片**：
   - **切片** —— 基于字幕热点片段，批量切出短视频；
   - **新闻编导视频** —— 双语字幕 + 名牌 + 章节条的完整成片。
6. 配置样式（字幕 / 文字水印 / 图片水印 / 开场·结尾卡片 / 章节条）→ **渲染导出**。

### 🎬 能做什么

**素材（一个项目共享一份源）**

| 素材 | 说明 |
|---|---|
| **新闻视频 / News Video** | 新闻 / 演讲 / 发布会素材：源视频 + 字幕 + 章节 + AI 新闻背景 |

**创作（从素材派生出片）**

| 创作 | 产出 |
|---|---|
| **切片 / Clip** | 基于字幕热点片段，批量切出短视频 |
| **新闻编导视频 / News Desk Video** | 新闻 / 演讲 / 发布会成片：双语字幕 + 名牌 + 章节条 |

> 更多节目形态开发中。

**字幕能力**：语音转字幕（ASR）、导入 SRT、翻译、质检自动修复、烧录（可配字体 / 颜色 / 大小 / 位置 / 描边 / 底色）。

### 🤖 AI（可选，三档，绝不强制）

核心出片不需要 AI。当你需要 ASR / 翻译 / 分析时，在 **AI** 与 **模型** 面板里按需启用，三档任选、可混用：

- **内置本地** —— 在 **模型管理器**里一键下载本地模型（如 faster-whisper），**离线运行、无需任何 Key**；
- **自建 aistack** —— 指向你自己部署的 [aistack](https://github.com/dosmoon/aistack) 网关；
- **云端 API** —— 填入你自己的 Key（Gemini / DeepSeek / Groq / LemonFox 等），按用量直接向服务方付费，**VideoCraft 不收任何中间费用**。

可选 **GPU 加速**（在模型管理器里安装 CUDA 运行时）。所有下载与配置都是强引导但**可跳过**。

### ⚖️ 关于视频下载功能的版权声明

VideoCraft 内置的视频下载功能基于开源项目 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，与 YouTube 及任何其他视频平台**均无关联**。该功能的存在不构成对下载受版权保护内容行为的鼓励或认可。

**使用本功能下载任何内容前，请用户自行确保该行为符合：**
- 所在国家 / 地区的法律法规（包括著作权法）；
- 相关视频平台的服务条款（Terms of Service）；
- 内容版权方的授权范围。

用户须对使用本功能产生的一切后果自行承担全部责任。开发者及贡献者不对因使用本功能引发的任何版权纠纷或法律后果负责。

### 📄 License / 贡献 / Fork

本项目采用 [MIT License](LICENSE) 发布（Copyright © 2025-2026 OldApeTalk），由 **dosmoon** 维护。你可以在协议许可的范围内自由使用、复制、修改、分发本软件。

> **关于贡献**：本项目目前**不接受外部 Pull Request 或代码贡献**。作者保留对本仓库的全部处置权（功能取舍、版本节奏、分支策略与未来方向）。发现 bug 或有功能建议，欢迎通过 [Issue](https://github.com/dosmoon/VideoCraft/issues) 反馈，但是否采纳由作者自行决定。

> **关于 Fork**：MIT 协议授予的权利不受上述贡献政策影响。你完全可以 Fork 自行维护、修改、再分发，只要保留原始版权声明与协议文本即可。但请注意：「VideoCraft」名称不在 MIT 授权范围内，Fork 版本请使用其它名称发布以免混淆；作者不对任何 Fork 版本的功能、安全性或维护状态负责。

---

## English

### ✨ What is it

VideoCraft is a **Windows desktop app**. The workflow is:

> **New project → add material (source video + subtitles + chapters) → generate creations (Clip / News Desk Video)**

ffmpeg ships inside the installer, so the **core video features work out of the box — no account or API key required**. AI (speech-to-text / translation / analysis) is an optional layer: use local models, your own self-hosted gateway, or your own cloud keys.

### 📦 Download & install

1. Go to **[Releases](https://github.com/dosmoon/VideoCraft/releases/latest)** and download `VideoCraft-<version>-setup.exe`.
2. Run the installer: **no admin needed**, installs per-user (`%LOCALAPPDATA%\Programs\VideoCraft`), and keeps its data right beside the app (portable — move the whole folder freely).
3. ⚠️ **The installer is not code-signed yet** (early stage): Windows SmartScreen may warn "Windows protected your PC" on first run → click **"More info" → "Run anyway"**. The source is open for inspection.
4. **ffmpeg is bundled** — nothing extra to install, no PATH setup. The optional first-run downloads (yt-dlp runtime / local AI models / GPU acceleration) are **all skippable** and don't affect the core features.

**Requirements**: Windows 10 / 11, 64-bit.

### 🚀 Quick start

1. **Create a project.**
2. Add a **News Video** material: paste a video link (downloaded via the built-in yt-dlp) or pick a local file; optionally trim to a time range.
3. **Subtitles**: one-click **ASR (speech-to-text)** / **import SRT** / **translate** / **quality-check & auto-fix**.
4. (Optional) organize **chapters**, or fill in **AI news context** (15 fields — host, event, key points… AI can web-search to draft them, then you review).
5. **Generate a creation:**
   - **Clip** — batch-cut short clips from subtitle hotclips;
   - **News Desk Video** — a full video with bilingual subtitles, lower-third name plates, and a chapter strip.
6. Configure styling (subtitles / text & image watermarks / hook & outro cards / chapter strip) → **render**.

### 🎬 What it makes

**Material (one shared source per project)**

| Material | Description |
|---|---|
| **News Video** | News / speech / press-briefing material: source video + subtitles + chapters + AI context |

**Creations (derived from the material)**

| Creation | Output |
|---|---|
| **Clip** | Batch-cut short clips from subtitle hotclips |
| **News Desk Video** | News / speech / press-briefing video with bilingual subs, lower-third name plates, and a topic strip |

> More program forms are in development.

**Subtitle features**: speech-to-text (ASR), import SRT, translate, quality-check with auto-fix, and burn-in (configurable font / color / size / position / stroke / background).

### 🤖 AI (optional, three tiers, never forced)

The core video features need no AI. When you want ASR / translation / analysis, enable it from the **AI** and **Models** panels — pick any tier, mix freely:

- **Built-in local** — download local models in the **Model Manager** (e.g. faster-whisper): **runs offline, no key needed**;
- **Self-hosted aistack** — point at your own [aistack](https://github.com/dosmoon/aistack) gateway;
- **Cloud API** — bring your own key (Gemini / DeepSeek / Groq / LemonFox …), pay the provider directly by usage — **VideoCraft takes no cut**.

Optional **GPU acceleration** (install the CUDA runtime in the Model Manager). Every download and config step is strongly guided but **skippable**.

### ⚖️ About the video-download feature (copyright notice)

VideoCraft's built-in download feature is powered by the open-source project [yt-dlp](https://github.com/yt-dlp/yt-dlp) and is **not affiliated** with YouTube or any other platform. Its presence does not encourage or endorse downloading copyrighted content.

**Before downloading anything, ensure your use complies with:**
- the laws of your country / region (including copyright law);
- the Terms of Service of the relevant platform;
- the rights granted by the content's copyright holder.

You bear full responsibility for all consequences of using this feature. The developers and contributors are not liable for any copyright disputes or legal consequences arising from its use.

### 📄 License / Contributions / Forks

Released under the [MIT License](LICENSE) (Copyright © 2025-2026 OldApeTalk), maintained by **dosmoon**. You may use, copy, modify, and distribute the software within the terms of the license.

> **Contributions**: this project currently **does not accept external Pull Requests or code contributions**. The author retains full discretion over the repository (features, release cadence, branching, future direction). Bug reports and feature ideas are welcome via [Issues](https://github.com/dosmoon/VideoCraft/issues), but adoption is at the author's discretion.

> **Forks**: nothing above limits the rights granted by MIT. You're free to fork, maintain, modify, and redistribute, as long as you keep the original copyright and license text. Note: the name "VideoCraft" is not covered by the MIT grant — please release forks under a different name to avoid confusion; the author is not responsible for any fork's functionality, security, or maintenance.
