---
title: Download & Install
description: Download the VideoCraft Windows installer, install without admin rights, and get past the SmartScreen warning on first run.
sidebar:
  order: 1
---

## Requirements

- Windows 10 / 11, **64-bit**
- No admin rights needed

## Download

Grab the latest installer from the **[Releases page](https://github.com/dosmoon/VideoCraft/releases/latest)** — the file is named `VideoCraft-<version>-setup.exe`.

## Install

1. Double-click the installer. It installs **per-user** (`%LOCALAPPDATA%\Programs\VideoCraft`) — no admin prompt.
2. ⚠️ **The installer is not code-signed yet** (early stage). Windows SmartScreen may warn *"Windows protected your PC"* on first run → click **"More info" → "Run anyway"**. The [source code](https://github.com/dosmoon/VideoCraft) is open for inspection.
3. Launch VideoCraft from the Start menu.

## What's bundled, what's optional

- **ffmpeg is bundled** — nothing extra to install, no PATH setup.
- On first run VideoCraft may offer optional downloads (yt-dlp runtime, local AI models, GPU acceleration). They are **all skippable** and don't affect the core video features.

## Portable data

All settings, models, and project state live in a `user_data` folder **right beside the app** — nothing is written to `%APPDATA%`. You can move the whole installation folder freely, and your data survives updates.

## Legal note on the download feature

The built-in video downloader is powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and is not affiliated with any video platform. Before downloading content, make sure your use complies with local law, the platform's Terms of Service, and the copyright holder's permissions — see the [full notice in the README](https://github.com/dosmoon/VideoCraft#readme).
