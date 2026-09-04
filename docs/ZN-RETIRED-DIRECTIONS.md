# 已废弃的产品方向

这个文件只记录已经明确放弃、不要再恢复成产品路线的方向。

## 专用“自我维护”系统

**状态：已废弃并移除。**

自 2026-09-04 起，ZN 不再拥有一套专门用于“维护自己、修自己、给自己上报 BUG”的特殊产品系统。

以后如果要修改 ZN 仓库，就把 ZN 当成一个普通代码仓库，走现有的通用能力：Work、文件、终端、Git、测试、浏览器和通用编码流程。目标仓库刚好是 ZN，不会因此获得额外权限，也不会进入一套特殊的 repair / maintenance runtime。

不要重新引入下面这些东西：

- 专门的 maintenance runtime、maintenance cognition 或 maintenance repair 链；
- 专门为“ZN 修自己”准备的 investigation / review / publication 状态机；
- 专用 upstream BUG report、transport、intake、reconcile 控制面；
- 专用 maintenance UI、IPC、RPC 或桌面策略；
- 因为目标仓库是 ZN 就自动获得写代码、提交、合并、发布或更新权限的特殊路径。

以下通用架构继续保留，它们不是“自我维护系统”：

- Health / 运行健康观测；
- Recovery / 恢复；
- Work / Memory / Resident 连续性；
- File / Terminal / Git / Repo Test；
- Browser / Desktop / Computer Use；
- Update / 发布相关的普通产品能力和安全边界。

简单说：**ZN 可以像处理别的项目一样处理自己的仓库，但不再有“自我维护”这套特殊架构。**

这次清理是项目所有者明确要求的一次性架构收口。专用实现、专用测试、专用界面和专用文档应从当前代码树中删除；对应的专用文件历史也应做一次性清理。这个例外不代表以后可以随便重写 Git 历史。正常情况下仍禁止无明确授权的 force push 和历史重写。
