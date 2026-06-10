# 版本号规则 (Versioning)

> 本项目发布版本号的约定，**后续遵从**。这是「发布/流程」约定，不是架构决策，故不进 `adr/`。
> 配套：发布动作的完整 checklist 见 [`design/packaging-design.md`](design/packaging-design.md) §10。

---

## TL;DR（一眼版）

- 格式 `MAJOR.MINOR.PATCH`（SemVer 形状）；当前处 `0.x` **不稳定期**。
- **版本号标识「一次发布」，不标识每次构建**——构建身份（build 号 + 短 SHA）是另一回事，正交（见下「版本 vs 构建标识」）。
- **单一权威源 = [`desktop/package.json`](../desktop/package.json) 的 `version`**。其它出现版本号的地方（`pyproject.toml` 等）在切发布时对齐它，不各自维护。
- **发布 = 打 tag `vX.Y.Z`**（三段式）→ CI 出包。一个版本 ↔ 一个 tag ↔ 一次发布。
- `1.0.0` 是一句**刻意声明**「可以给陌生人用了」，不是自然到达。

---

## 各位语义（App 味，非库味）

SemVer 原意是给**有对外 API 契约的库**设计的；VideoCraft 是终端 App，没有 API 契约，"破坏"语义模糊，所以用 SemVer 形状但语义按 App 调整：

| 位 | 何时 +1 | 例 |
|---|---|---|
| **MAJOR** | 里程碑 / 重塑（你会当 "2.0" 宣传）；或工程文件格式不兼容（旧工程打不开） | — |
| **MINOR** | 一波向后兼容的新能力（新节目形态、新编辑器、新 AI 档） | 录播自动剪辑落地 → `0.4.0` |
| **PATCH** | bug 修复 / 小调整 / 重新打包，无新功能无破坏 | crop 重打包 → `0.3.4 → 0.3.5` |

MAJOR 一半是技术决定、一半是营销决定。

---

## `0.x` 期专属规则（当前阶段）

SemVer 明文：**`MAJOR=0`（`0.y.z`）= 不稳定期，不承诺任何兼容性，啥都能随时变。** 契合本项目 pre-alpha 无用户状态——**别纠结 MAJOR/MINOR 的严格定义**。

`0.x` 通行实操：**MINOR 当「大改/破坏」档，PATCH 当「其它一切」档**，即把 `0.` 当占位、`MINOR.PATCH` 当真正的「大.小」：

- `0.3 → 0.4`：一波值得讲的新功能 / 不兼容改动。
- `0.3.5 → 0.3.6`：修 bug、小事、重新出包。

到 `1.0.0` 之前安心待在 `0.x`。

---

## 何时涨（时机）+ 发布流程

1. **在「切发布」那一刻涨，不是每次 commit / merge 涨。** 你决定"这个要发出去/给人装" → 才 bump。日常 push main 不涨号。
2. 流程（tag 驱动，CI 已是 `v*` 触发）：
   1. 改 `desktop/package.json` 的 `version`（必要时同步 `pyproject.toml`）。
   2. 打 **annotated tag** `vX.Y.Z` + 一句 release note（数字旁必须有"为什么涨"）。
   3. push tag → CI 出该版本的包。
3. **预发布**：要发测试版给 tester 用 `0.4.0-beta.1` / `0.4.0-rc.1`（SemVer 预发布后缀，排序低于 `0.4.0`）。
4. **tag 一旦 push 不可变**（发布即不可变）：要改 = 出新 PATCH，不移动/复用旧 tag。

---

## 版本 vs 构建标识（正交，别混）

| | 发布版本 (version) | 构建标识 (build identity) |
|---|---|---|
| 例 | `0.3.5` | build `42` · `ef0f28d` |
| 答的问题 | 哪**次发布** | 哪**次构建**、哪个 commit |
| 谁动 | 人，切发布时**手动** | **自动**派生（CI = `github.run_number`；本地 = git commit 数 + 短 SHA） |
| 频率 | 罕见 | 每次 build |

构建标识的落地（`build-info.json` + 「关于」卡片 + Windows FileVersion `0.3.5.<build>`）是单独的工程，不影响本规则。

---

## 不变量 / 纪律

- **单一版本源 = `desktop/package.json`**；运行时一律 `app.getVersion()` 读它，不在代码里另写常量。
- **三段式 tag `vX.Y.Z`**。历史遗留的两段式 tag `0.3` 不动它（不可变），新发布一律三段。
- 版本号不参与构建身份；分发文件名保持干净（`VideoCraft-0.3.5-setup.exe`），不塞 build 号。
