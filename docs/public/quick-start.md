---
title: Quick Start
description: From a video link to a finished video in six steps — project, material, subtitles, chapters, creation, render.
sidebar:
  order: 2
---

The VideoCraft workflow is:

> **New project → add material (source video + subtitles + chapters) → generate creations (Clip / News Desk Video)**

## Six steps

1. **Create a project.**
2. Add a **News Video** material: paste a video link (downloaded via the built-in yt-dlp) or pick a local file; optionally trim to a time range.
3. **Subtitles**: one-click **ASR (speech-to-text)** / **import SRT** / **translate** / **quality-check & auto-fix**.
4. *(Optional)* organize **chapters**, or fill in the **AI news context** (15 fields — host, event, key points… AI can web-search to draft them, then you review).
5. **Generate a creation:**
   - **Clip** — batch-cut short clips from subtitle hotclips;
   - **News Desk Video** — a full video with bilingual subtitles, lower-third name plates, and a chapter strip.
6. Configure styling (subtitles / text & image watermarks / hook & outro cards / chapter strip) → **render**.

## About AI (optional, never forced)

The core video features need no AI. When you want ASR / translation / analysis, enable it from the **AI** and **Models** panels — three tiers, pick any, mix freely:

- **Built-in local** — download local models in the **Model Manager** (e.g. faster-whisper): runs offline, no key needed;
- **Self-hosted [aistack](https://github.com/dosmoon/aistack)** — point at your own gateway;
- **Cloud API** — bring your own key (Gemini / DeepSeek / Groq / LemonFox …), pay the provider directly — VideoCraft takes no cut.

Optional **GPU acceleration** is available in the Model Manager (CUDA runtime). Every download and config step is strongly guided but **skippable**.
