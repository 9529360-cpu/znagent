# ZN 真实模型端到端证据报告（20261019-195639）

- 模式：dry（模型：deepseek-chat）
- 闸门：未设置 ZN_E2E_LIVE=1：opt-in 闸门关闭，真实模型调用被跳过
- 时间：2026-10-19T19:56:39+0000 → 2026-10-19T19:56:39+0000
- schema：zn-live-model-evidence/v1 / harness v0.1.0
- 汇总：共 6 项，rejected=5、skipped=1
- 失败分类：none=1、tool_environment=5

| 任务 | 域 | verdict | 失败类 | 耗时(s) | 缺失项 |
|---|---|---|---|---|---|
| research-01 | research | rejected | tool_environment | 0.0 | - |
| browser-01 | browser | skipped | none | 0.0 | - |
| file-01 | file | rejected | tool_environment | 0.0 | - |
| file-02 | file | rejected | tool_environment | 0.0 | - |
| coding-01 | coding | rejected | tool_environment | 0.0 | - |
| cross-01 | cross_domain | rejected | tool_environment | 0.0 | - |

## 任务明细

### research-01（research）从给定资料中提炼三个关键事实

- verdict：rejected；失败类：tool_environment
- 备注：模型调用抛异常：RuntimeError：dry-run：opt-in 闸门关闭，未做真实模型调用
- 证据摘录：

### browser-01（browser）真实页面抓取交叉验证

- verdict：skipped；失败类：none
- 备注：http_observation 检查需要 live 模式（真实抓取），闸门关闭时跳过
- 证据摘录：

### file-01（file）按规范写出 JSON 配置文件

- verdict：rejected；失败类：tool_environment
- 备注：模型调用抛异常：RuntimeError：dry-run：opt-in 闸门关闭，未做真实模型调用
- 证据摘录：

### file-02（file）改写已有文本：追加条目

- verdict：rejected；失败类：tool_environment
- 备注：模型调用抛异常：RuntimeError：dry-run：opt-in 闸门关闭，未做真实模型调用
- 证据摘录：

### coding-01（coding）修复一个小 bug 并通过运行验证

- verdict：rejected；失败类：tool_environment
- 备注：模型调用抛异常：RuntimeError：dry-run：opt-in 闸门关闭，未做真实模型调用
- 证据摘录：

### cross-01（cross_domain）研究 + 文件：读资料写摘要文件

- verdict：rejected；失败类：tool_environment
- 备注：模型调用抛异常：RuntimeError：dry-run：opt-in 闸门关闭，未做真实模型调用
- 证据摘录：

