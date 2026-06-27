# 发布 Checklist (Release Checklist)

> 切一个发布版 `vX.Y.Z` 的**可勾选驱动单**。每次发布从上到下走一遍。
> 本文只列 **做什么**；**为什么 / 怎么做的细节**在权威源里，按链接跳：
> 版本号规则 → [`versioning.md`](versioning.md)；打包/发布流程 → [`packaging.md`](packaging.md) §4；依赖刷新 → [`design/packaging-design.md`](design/packaging-design.md) §10。
>
> 复制下面的清单到本次发布的草稿 / commit 描述里逐项勾。

---

## 0. Pre-flight
- [ ] 定版本号（PATCH / MINOR，见 [`versioning.md`](versioning.md)），记一句「为什么涨」。
- [ ] `git status` 工作树干净（未跟踪的临时调试脚本不入包、可忽略）。

## 1. Bump 版本号（三处对齐）
> 单一权威源 = `desktop/package.json`；其余两处是同步镜像。
- [ ] `desktop/package.json` 的 `version` → `X.Y.Z`
- [ ] `pyproject.toml` 的 `version` → `X.Y.Z`
- [ ] `src/__init__.py` 的 `__version__`（+ 注释里的版本）→ `X.Y.Z`
- ℹ️ **无需手改**：App「关于/帮助」对话框、设置关于卡片走 `app.getVersion()`；版权年 `appInfo.ts` 取当前年；Windows `FileVersion` = `<ver>.<run#>` 由 CI 派生 —— 全部自动跟随 `package.json`。

## 2. 依赖刷新（见 [`packaging-design.md`](design/packaging-design.md) §10）
- [ ] `yt-dlp` bump 到 latest（`pyproject.toml` `[project.dependencies]`）—— 唯一必须追新的包；已是 latest 则跳过。
- [ ] `uv lock` 重生成 `uv.lock`（项目版本号也会顺带更新到 `X.Y.Z`）。
- [ ] `myenv/Scripts/python.exe -m pytest tests/` 全绿（含 `test_dependency_pins`）。

## 3. 本地打包态验证（见 [`packaging.md`](packaging.md) §2、[`packaging-design.md`](design/packaging-design.md) §10.4-10.6）
- [ ] `./packaging/build_sidecar.ps1`（`uv sync --frozen` 重打冻结 sidecar）
- [ ] `./packaging/fetch_ffmpeg.ps1`（幂等）
- [ ] `./packaging/generate_build_info.ps1`
- [ ] `pnpm -C desktop build:win` → 产出 `desktop/release/VideoCraft-X.Y.Z-setup.exe`
- [ ] 复审 `desktop/electron/main.ts` 的 `disable-gpu-sandbox`（dev concession，打包前确认是否仍需要）。
- [ ] 打包态终验：`d:\tmp\e2e_ytdlp.py` + 装 installer 真机过核心链路（ASR/LLM/本次新功能路径）。

## 4. 提交 + 打 tag（见 [`packaging.md`](packaging.md) §4）
- [ ] commit version bump（含 `uv.lock`），英文消息，例 `chore(release): bump to X.Y.Z`。
- [ ] ⚠️ **tag 必须等于 `desktop/package.json` 的版本**（installer 版本取自 package.json，对不上 CI fail fast）。
- [ ] `git tag -a vX.Y.Z -m "<release note>"` → `git push origin <branch>` → `git push origin vX.Y.Z`。

## 5. CI → 草稿 Release → publish（见 [`packaging.md`](packaging.md) §4.5-4.7）
- [ ] tag 触发 `.github/workflows/build-windows.yml`；`gh run watch <run-id> -R dosmoon/VideoCraft --exit-status` 盯到绿。
- [ ] GitHub → Releases 草稿：把 `--generate-notes` 初稿替换为**中英双语** release note，核对挂载的 `*-setup.exe` + `.blockmap`。
- [ ] 点 **Publish release** 才公开（不发就删草稿，从未对外）。

## 6. 收尾
- [ ] 更新 [`task.md`](task.md)：记 `vX.Y.Z` 已发布（精简接力指针）。
