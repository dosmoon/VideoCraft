# Claude Code 会话指引

本文件由 Claude Code 在每次会话启动时自动加载。**只放"每次会话都该读到"的路标式指引**，不当成第二个 `docs/`。具体设计/实现细节在 `docs/`，决策正文在 `docs/adr/`，本文件只指路。

---

## 架构决策

本项目重要决策记录在 [`docs/adr/`](docs/adr/README.md) 下，采用轻量 ADR 格式。

修改架构层代码（数据 schema、服务边界、核心数据流、跨模块契约）前，请先扫一遍 ADR 目录，确认不要违背已有决策。被 `Superseded` 状态标记的 ADR 已失效，看取代它的新 ADR。

不进 ADR 的东西（个人偏好、当前任务、API 文档）见 `docs/adr/README.md` 里的分工说明。
