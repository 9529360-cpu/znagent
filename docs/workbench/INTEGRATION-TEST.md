# ZN Workbench P0 — 人工验收 / AI 电脑测试手册

本集成包含：会话导出（#527）、消息复制/快捷键（#528）、Resident 持久化重命名（#529）、执行时间线（#541）。主分支整合经 PR CI 验证后才能作为可测基线；这是桌面**开发测试**，不替代正式签名安装包。

## Windows x64 上启动
在拥有 ZNagent 源码的电脑中打开 PowerShell（不要修改其它仓库或正式安装）：

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
node --version
npm run setup
npm run doctor
npm run dev
```

要求 Node.js 22.22.0 及以上；按照 `npm run doctor` 提示配置 uv/Python 和本机模型。切勿在测试记录里粘贴真 API Key。

## 端到端验收（让另一位 AI 实际操作）
1. 启动 ZN 桌面端，新建 Work，发送一条普通消息。确认收到回复；若模型未配置，明确报告“未配置”，不能假装对话流正常。
2. 在现有会话的顶部重命名。关闭并重开窗口，确认标题、历史消息及 Work ID 不变。
3. 使用 **Enter / Ctrl+Enter** 发送，**Shift+Enter** 换行，**Ctrl+K** 聚焦会话搜索。任务进行中用 **Esc** 请求取消，确认 UI 以 Resident 返回状态为准，不显示虚假已停止。
4. 在用户授权的临时工作区，用安全的只读文件检查任务生成真实 Body 动作。观察运行中时间线的动作类型、成功/失败、完成时间、结果摘要；任务结束后查看历史 activity 的折叠时间线。不能使用虚构的工具调用截图替代验证。
5. 分别复制一条用户消息和一条 ZN 回复，检查剪贴板文本。导出 Markdown/JSON 并打开文件：只有用户/ZN 文本，不包含内部技术详情、工具参数或工作区私有路径。
6. 退出并重新启动桌面端，核验重命名和历史时间线是否从同一 Resident Work 恢复；长对话的旧工具记录应默认折叠。
7. 检查展开/收起产物侧栏、窗口紧凑和展开模式，保证无溢出、键盘焦点可见、文本可读。这里没有自动化真实屏幕截图验收，须在电脑上操作记录证据。

## 自动验证
```powershell
npm run typecheck
npm run test --workspace apps/desktop -- electron/zn-conversation-export.test.ts electron/zn-workbench-shortcuts.test.ts electron/zn-execution-timeline.test.ts electron/zn-workbench-integration.test.ts
```

Python 核心工作测试必须在 Windows CI 中通过 `test_work_ledger.py` 与 `test_work_progress.py` 的原有完整测试集；同时不能忽略全套 ZN CI、Work Recovery、Floor Guard 和 Windows Clean Install。

## 已知限制 / 失败判断
- 实时界面仍观察 Resident 原有进度协议，并非真正的 token SSE；Markdown/LaTeX 和文件拖拽上传不包含在此整合中。
- 历史时间线只保留最近六条 **已完成** Body 动作的短摘要，不是完整审计和工具参数回放。
- 未配置或不可用的模型不能视为流式会话成功；拒绝/未知外部副作用不得自动重试。
- 发现任何数据丢失、权限绕过、任务重复执行、UI 崩溃或持久化错误，立即停止验收，保留脱敏后的操作步骤、环境、窗口截图和日志摘要。
