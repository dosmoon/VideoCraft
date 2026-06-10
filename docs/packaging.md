# 打包 & 发布说明 (Packaging & Release)

> **操作手册（runbook）**：怎么把 VideoCraft 打成 Windows 安装包、怎么切发布。
> 设计与取舍（为什么 onedir / 瘦包 / bundle ffmpeg 等）见 [`draft/packaging-design.md`](draft/packaging-design.md)；
> 版本号怎么涨见 [`versioning.md`](versioning.md)。本文只讲**怎么做**。

---

## 0. 三种产出，先分清

| 场景 | 怎么触发 | 产出 | exe 图标 / 签名 |
|---|---|---|---|
| **本地打包** | 手动跑脚本 + `pnpm build:win` | `desktop/release/` 下 installer + `win-unpacked/` | exe = 默认 Electron 图标、unsigned（本机绕 winCodeSign）；窗口/安装包图标是品牌图标 |
| **CI 打包** | `gh workflow run` 手动 dispatch | run artifact `VideoCraft-windows-installer` | exe = **品牌图标内嵌** + FileVersion `<ver>.<run#>`；仍 unsigned（无证书） |
| **正式发布** | push `v*` tag | CI 构建 → **草稿 Release**（挂 installer）+ run artifact | 同 CI 打包；草稿不公开，需人工 publish |

> exe 的 Authenticode **真签名暂缺**（没证书）；SmartScreen 首次会警告。方案见 packaging-design §10。

---

## 1. 前置依赖

- **uv**（驱动 sidecar 冻结；`uv venv --python 3.12` 会自取 Python 3.12）。
- **Node + pnpm**（renderer/打包；本机版本见 `desktop/package.json` 的 pnpm/electron 约束）。
- 其余（PyInstaller、electron-builder、ffmpeg、winCodeSign）由脚本/工具链自取，无需手装。

---

## 2. 本地打包（出一个能跑的 installer）

按顺序跑（前三个是 `pnpm build:win` 的**前置产物步骤**，缺了会报错）：

```powershell
./packaging/build_sidecar.ps1        # uv 冻结 sidecar → desktop/resources/sidecar/
./packaging/fetch_ffmpeg.ps1         # 拉 pinned ffmpeg/ffprobe → desktop/resources/（幂等）
./packaging/generate_build_info.ps1  # 生成 build-info.json → desktop/{build,resources}/
pnpm -C desktop build:win            # electron-vite build + electron-builder NSIS
```

产出：`desktop/release/VideoCraft-<version>-setup.exe`（+ `.blockmap`）和 `desktop/release/win-unpacked/`。

> 本机 `electron-builder.yml` 保持 `signAndEditExecutable: false`（非 admin/无 Developer Mode 机器解压 winCodeSign 会挂）→ 本机包的 **exe 用默认图标、FileVersion 不被改**。要品牌图标内嵌 + FileVersion，走 CI（见 §3）。详见 packaging-design §3 的 winCodeSign 坑。

---

## 3. CI 打包（要品牌图标内嵌的包）

```powershell
gh workflow run build-windows.yml -R dosmoon/VideoCraft --ref main
gh run watch <run-id> -R dosmoon/VideoCraft --exit-status   # 盯到绿
gh run download <run-id> -R dosmoon/VideoCraft -n VideoCraft-windows-installer -D <dir>
```

CI 在 GitHub Windows runner 上：跑 §2 的四步 → **就地把 `signAndEditExecutable` flip 成 true**（runner 有符号链接权限）→ rcedit 嵌品牌图标 → `BUILD_NUMBER=run_number` 折入 Windows FileVersion `<ver>.<run#>` → 传 artifact（`--publish never`，不自动发 Release）。

---

## 4. 正式发布（tag → 草稿 Release → 人工 publish）

**构建与发布解耦**：打 tag 只出包进草稿，公开是另一个人工动作。

1. **bump 版本**（[`versioning.md`](versioning.md)）：改 `desktop/package.json` 的 `version`，同步 `pyproject.toml`。⚠️ **tag 必须等于 package.json 版本**——installer 版本号取自 package.json 非 tag，对不上 CI 会 fail fast。
2. **刷新追新依赖**：照 packaging-design §10 的 checklist（主要是 bump `yt-dlp` + `uv lock` + pytest 绿）。
3. **提交** version bump。
4. **打 annotated tag + push**：
   ```powershell
   git tag -a v<X.Y.Z> -m "<release note>"
   git push origin v<X.Y.Z>
   ```
5. tag 触发 CI → 构建 → 建/更**草稿 Release**（`VideoCraft v<X.Y.Z>`，挂 `*-setup.exe` + `.blockmap`）。
6. **复核**：GitHub → Releases → 该草稿，审 release notes（`--generate-notes` 自动生成的初稿，按需编辑）+ 验证挂的包。
7. **Publish**：点 “Publish release” 才公开；不想发就**删草稿**，从未对外。

> 草稿只有仓库写权限者可见；公众在你 publish 前看不到。重打同名 tag 会**复用并覆盖**草稿资源（幂等，不报错）。`git tag` 本身一推即公开（CI 靠它触发），公开的只是 tag 引用，不是 Release。

---

## 5. 包内有什么

`<app>/resources/` 下：`sidecar/`（冻结 core_rpc + src/ + 依赖）、`ffmpeg.exe`/`ffprobe.exe`（随包）、`icon.ico`（品牌图标）、`build-info.json`（build#/commit/时间，「关于」卡片读它）。嵌入 AI / 模型 / CUDA 不随包，运行时按需装进 `<exeDir>/user_data`（packaging-design §5/§6）。

---

## 6. 已知事项

- **exe unsigned**：SmartScreen 首次警告，拿证书后补真签名（packaging-design §10）。
- **windows runner 镜像公告**：`windows-2025` 2026-06-15 刷成含 VS2026 的新镜像，纯信息性、构建照常，不用管。
