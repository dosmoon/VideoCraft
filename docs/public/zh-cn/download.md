---
title: 下载与安装
description: 下载 VideoCraft Windows 安装包，免管理员安装，以及首次运行通过 SmartScreen 提示的方法。
sidebar:
  order: 1
---

## 系统要求

- Windows 10 / 11，**64 位**
- 无需管理员权限

## 下载

前往 **[Releases 页面](https://github.com/dosmoon/VideoCraft/releases/latest)** 下载最新安装包，文件名为 `VideoCraft-<版本>-setup.exe`。

## 安装

1. 双击运行安装程序：**免管理员**，安装到当前用户目录（`%LOCALAPPDATA%\Programs\VideoCraft`）。
2. ⚠️ **安装包暂未做数字签名**（早期阶段）：Windows SmartScreen 首次可能提示「Windows 已保护你的电脑」→ 点 **「更多信息」→「仍要运行」** 即可。[源码开放](https://github.com/dosmoon/VideoCraft)，可自行核验。
3. 从开始菜单启动 VideoCraft。

## 哪些已内置、哪些可选

- **ffmpeg 已内置**，无需另行安装或配置 PATH。
- 首次运行的可选引导下载（yt-dlp 运行时 / 本地 AI 模型 / GPU 加速）**都可以跳过**，不影响核心功能。

## 绿色便携

所有设置、模型、项目状态都放在程序旁边的 `user_data` 文件夹里 —— 绝不写 `%APPDATA%`。整个安装目录可自由搬走，更新后数据保留。

## 关于视频下载功能的版权说明

内置的视频下载功能基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，与任何视频平台均无关联。下载任何内容前，请自行确保符合所在地法律法规、平台服务条款与版权方授权 —— 完整声明见 [README](https://github.com/dosmoon/VideoCraft#readme)。
