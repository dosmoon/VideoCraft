# Third-Party Licenses / 第三方组件协议声明

VideoCraft 自身代码以 [MIT License](LICENSE) 发布。本项目的 portable 发行包另外捆绑了若干第三方开源组件，各组件的协议条款一并列于下表，并随发行包以原始 LICENSE 文件形式保留在各组件目录内。

> 用户可在 portable 包内进入 `python/Lib/site-packages/<package>-<version>.dist-info/` 找到对应的 `LICENSE` 原文。

---

## 1. 运行时（Runtime）

| 组件 | 版本族 | 协议 | 协议出处 |
|---|---|---|---|
| **CPython** | 3.x | Python Software Foundation License | https://docs.python.org/3/license.html |
| **Tcl / Tk**（tkinter 后端） | 8.6 | BSD-style (Tcl/Tk License) | https://www.tcl.tk/software/tcltk/license.html |

## 2. Google 生态（Apache License 2.0）

| 组件 | 用途 |
|---|---|
| google-auth, google-auth-httplib2 | OAuth 鉴权 |
| google-api-core, google-api-python-client | Google API 通用客户端 |
| google-cloud-texttospeech | TTS（文字转语音） |
| google-genai, google-generativeai, google-ai-generativelanguage | Gemini API |
| googleapis-common-protos | Google API 通用 proto |
| grpcio, grpcio-status | gRPC 运行时 |
| protobuf, proto-plus | Protocol Buffers |
| uritemplate, httplib2 | HTTP 工具 |

协议全文：http://www.apache.org/licenses/LICENSE-2.0

## 3. HTTP / 网络栈

| 组件 | 协议 |
|---|---|
| requests | Apache 2.0 |
| urllib3 | MIT |
| httpx, httpcore, h11 | BSD-3-Clause |
| certifi | Mozilla Public License 2.0（仅根证书数据） |
| charset-normalizer | MIT |
| idna | BSD-3-Clause |
| websockets | BSD-3-Clause |
| anyio, sniffio | MIT / Apache 2.0 双协议 |

## 4. AI / 第三方 SDK

| 组件 | 协议 | 用途 |
|---|---|---|
| openai | Apache 2.0 | OpenAI API SDK |
| deepl | MIT | DeepL 翻译 SDK |
| jiter | MIT | 高速 JSON 解析（OpenAI SDK 依赖） |
| tenacity | Apache 2.0 | 重试 |
| distro | Apache 2.0 | OS 信息探测 |

## 5. 数据 / 模型

| 组件 | 协议 |
|---|---|
| pydantic, pydantic-core | MIT |
| annotated-types, typing-extensions, typing-inspection | MIT |
| packaging, pyparsing | Apache 2.0 + BSD 双协议 |
| future | MIT |

## 6. 加密 / 安全

| 组件 | 协议 |
|---|---|
| cryptography | Apache 2.0 与 BSD-3-Clause 双协议（用户自选其一） |
| cffi | MIT |
| pycparser | BSD-3-Clause |
| pyasn1, pyasn1-modules | BSD-2-Clause |

## 7. 媒体 / 文档处理

| 组件 | 协议 | 用途 |
|---|---|---|
| Pillow | HPND（permissive） | 图像处理 |
| lxml | BSD-3-Clause | XML 处理 |
| python-pptx | MIT | PowerPoint 处理 |
| xlsxwriter | BSD-2-Clause | Excel 写入 |
| ffmpeg-python | Apache 2.0 | FFmpeg Python 封装（**不含 FFmpeg 本身**，FFmpeg 由用户自装） |
| srt | MIT | SRT 字幕解析 |
| babel | BSD-3-Clause（含 Unicode 数据，遵循 Unicode License） |

## 8. 视频下载

| 组件 | 协议 | 备注 |
|---|---|---|
| **yt-dlp** | Unlicense（公有领域） | https://github.com/yt-dlp/yt-dlp |

> 关于 yt-dlp 的版权使用声明，详见 README "关于视频下载功能的版权声明"一节。

## 9. Windows 平台支持

| 组件 | 协议 |
|---|---|
| pywin32 (win32, win32com, pythonwin, adodbapi, isapi) | PSF-style |

## 10. 工具类

| 组件 | 协议 |
|---|---|
| colorama | BSD-3-Clause |
| pip, setuptools, wheel | MIT |

---

## 关于 FFmpeg

FFmpeg **不随 VideoCraft 发布**，由用户自行从官方渠道下载安装并配置 PATH 环境变量。其 LGPL / GPL 协议义务由 FFmpeg 官方分发渠道承担，与 VideoCraft 无关。

---

## 协议合规声明

VideoCraft 在使用上述第三方组件时遵守以下原则：

1. 完整保留各组件的原始 LICENSE 文件，未做任何修改；
2. 未声称对上述组件拥有著作权；
3. 未使用上述组件原作者的名义为 VideoCraft 背书；
4. 凡协议要求标注"基于 XX 修改"的组件，本项目均未做源码修改，仅作为依赖调用。

如发现本声明遗漏或描述有误，请通过 Issue 告知。
