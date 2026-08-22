# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

把 ZN 建成“维护者无关”的长期项目：任何人类或外部模型接手，都以仓库、测试和 CI 为事实来源，可以继续开发、PR、合并和发布；ZN 后续再逐步具备自维护自身源码的能力。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 最近确认的新增自维护文档提交：`0da639dbf75d99650df86f34a16e2e6d4f0d05b5`
- 当前远程 HEAD 可能已因后续文档提交继续前进；接手时必须重新读取分支 HEAD，不得把上面的 SHA 当成最新 HEAD。
- 本会话通过 GitHub 远程接口工作，没有本地工作区状态可声明。

## 已完成

- 已确认 `main` 是 Hermes 参考基线，真实 ZN 开发在 `dev/zn-agent`。
- 已重新确认 ZN 核心方向：模型是可替换认知资源，不是 ZN 主体。
- 已确认现有 N → N+1 runtime / update 架构与“身体可换、身份/记忆连续”方向一致。
- 新增 `docs/ZN-SELF-MAINTENANCE.md`，定义自维护、自修复、PR/CI、发布、用户确认安装和回退闭环。
- 已确认仓库已有 `.github/workflows/zn-ci.yml`、`zn-release.yml`、`zn-linux-appimage-update-smoke.yml`。
- 已确认正式发布工作流使用 GitHub Actions，正式 tag 为 `zn-v*`，多平台构建后发布不可变更新资产并最后推进 `stable.json`。
- 已确认发布所需外部存储凭证通过 GitHub Secrets/Variables 引用，而不是硬编码进源码。

## 重要发现

- 根目录已有 `AGENTS.md`，但当前仍是 Hermes 开发指南，不能新建同名文件；后续应在不丢失仍有参考价值内容的前提下，把 ZN 接手规则放到文件最前面或逐步迁移为 ZN 规则。
- 当前没有发现已有 `.agent/HANDOFF.md`，本文件为首次建立。
- 当前发布流水线已经具备“维护者可替换”的重要基础，但 GitHub 仓库级权限/分支保护/Secrets 的实际配置不能仅从源码文件推断，需要通过 GitHub 设置确认。

## Task Queue

| 优先级 | 任务 | 状态 | 依赖 | 备注 |
| --- | --- | --- | --- | --- |
| P1 | 把维护者无关原则正式接入 `ZN.md` | planned | 无 | 明确换 GPT/Claude/人类不影响开发发布 |
| P1 | 更新根 `AGENTS.md` 为 ZN-first 接手规则 | planned | 无 | 保留必要 Hermes 参考规范，但 ZN 规则必须优先 |
| P1 | 更新 `docs/ZN-IMPLEMENTATION-STATUS.md` | planned | ZN.md | 标记 SM0 完成、SM1 planned |
| P1 | 完成 M8 N→N+1 busy/idle 连续性验证 | in_progress | 现有 runtime/update | 自维护最终安装闭环的地基 |
| P1 | 核对 GitHub Actions/分支保护/Secrets/Variables 实际权限 | planned | 仓库设置权限 | 代码不能证明设置已正确配置 |
| P2 | SM1：健康观察与维护任务 | planned | 文档契约 + M8关键连续性 | 暂不自动改源码 |
| P2 | SM2：自身仓库只读调查 | planned | SM1 | GitHub 凭证只走安全引用 |
| P2 | SM3/SM4：隔离修复 + PR/CI | planned | SM2 | 不直接写正式分支 |
| P2 | SM5/SM6：风险审批 + 自动发布 | planned | SM4 | 高风险修改保留人工批准 |
| P2 | SM7：用户确认更新 + 自动回退 | planned | M8 + SM6 | 客户端最终点击更新 |

## 已验证的仓库自动化

通过读取仓库文件确认：

- `.github/workflows/zn-release.yml`
  - `zn-v*` tag 可触发正式发布；
  - Linux / Windows / macOS 多平台打包；
  - 使用仓库变量 `ZN_UPDATE_CHANNEL_URL`、`ZN_PUBLIC_RELEASE_URL`、`ZN_UPDATE_S3_*`；
  - 使用 GitHub Secrets `ZN_UPDATE_S3_ACCESS_KEY_ID` / `ZN_UPDATE_S3_SECRET_ACCESS_KEY`；
  - 正式版本先上传不可变资产；
  - 创建/更新 GitHub Release；
  - `stable.json` 最后推进。

本轮没有实际触发 release，也没有宣称发布成功。

## 风险 / 阻塞

- 无法仅通过仓库源码确认 GitHub Secrets 是否已经真实配置。
- 无法仅通过仓库源码确认 `dev/zn-agent` / 未来 `main` 的 branch protection 是否符合预期。
- 根 `AGENTS.md` 仍以 Hermes 为主，未来模型接手时可能产生错误方向，属于需要尽快修正的 P1 文档风险。
- 不要把任何 GitHub Token、S3 key、签名证书写进本文件。

## 下一步

1. 先把“维护者可替换、仓库自动化拥有发布能力”的原则补进 `ZN.md`。
2. 再改现有 `AGENTS.md`，让任何新模型第一眼知道 ZN 才是产品，Hermes 只是参考源码。
3. 同步 `ZN-IMPLEMENTATION-STATUS.md`。
4. 核对 GitHub 仓库实际权限配置后，再决定是否调整 branch protection / Actions 权限。
