# ZN 真实模型端到端证据收集 harness（M-11）

opt-in 的证据收集工具：**默认不跑、不进 CI 必需项**。回答 backlog M-11
的问题——现有测试的 provider 响应全是受控测试边界，没有任何可重复的
"真实模型下 ZN 能端到端完成任务"的证据收集机制。

## 用法

```bash
# 1. 校验任务集（默认，不触网）
PYTHONPATH=runtime/python python -m zn_agent.core.live_model_evidence_harness \
  --taskset evidence/live_model_taskset.json --out evidence/runs

# 2. 真实模型运行（opt-in 闸门）
ZN_E2E_LIVE=1 ZN_E2E_MODEL=deepseek-chat \
PYTHONPATH=runtime/python python -m zn_agent.core.live_model_evidence_harness \
  --taskset evidence/live_model_taskset.json --out evidence/runs --live
```

闸门逻辑（`resolve_live_gate`）：
- 未设置 `ZN_E2E_LIVE=1` → 真实调用被跳过，任务记为 `skipped`，报告如实写原因；
- 闸门开启但模型路由解析不出凭证（`DEEPSEEK_API_KEY` 等现有环境变量约定）→
  同样跳过，不假装跑；
- 只有路由解析成功才真正调用模型。凭证永不写入代码、日志与报告。

## 任务集

`evidence/live_model_taskset.json`（schema `zn-live-model-taskset/v2`，T6 起；
harness 对 v1 / v2 都读，见下）。9 个任务，覆盖研究 / 浏览器 / 文件 /
编码 / 跨面五个域。每个任务自带 `expected_output`（CP-3 终报逐项举证的
验收口径）与确定性检查：

- `fact_markers`：模型输出原文必须命中的事实标记；
- `file_content`：模型产物（终报 evidence 条目可选带 `artifact` 字段）
  由 harness 写到隔离 scratch 目录后做内容命中 / JSON 或 Python 解析检查；
- `python_run`：编码类任务，harness 用**仓库自带**的测试片段在子进程
  （`python -I`，超时熔断）里执行模型产物，记录真实运行证据；
- `http_observation`：浏览器类任务仅 live 模式，harness 自己独立抓取同一
  URL，把独立观测与模型报告交叉比对；
- `ics_parse`（T6 起）：R5 日历任务，harness 用仓库自身的
  `calendar_connector.parse_ics`（日历连接器真实解析路径）对模型产出的
  ICS 做语义解析，事件字段全命中时登记一条 objective 为「ICS 解析核查」
  的证据条目供终报引用（与 `fact_markers` 的「事实标记核查」登记同机制：
  未全命中不登记，引用落空、判定保持 partial）。

## 判定与失败分类

复用 CP-3 判定器 `completion_verdict.adjudicate_completion`
（与 M-5 推广到单人 Work 的是同一个判定器，无第二判定器）：
harness 记录的 evidence 条目（`relative_path` / `objective` / `result`）
扮演"Body 验证证据"角色，模型终报必须逐条引用真实证据。

失败分类是确定性纯函数 `classify`（可单测）：
- `tool_environment`：调用/抓取/检查执行本身抛异常；
- `model_capability`：终报被 rejected，或产物确定性检查失败；
- `verification_gap`：终报结构成立但有验收项缺匹配证据（partial）；
- `other` 兜底；`verified` 或被闸门跳过记 `none`。

## 基线实测与任务集公平性修复（Q6，2026-10-20）

第一份真实基线用 apikey.fan 专线通道（slb + deepseek-flash，用户授权）
跑出后做了三跑对照，结论：**原样任务集量出的不是模型能力，而是任务集
自身的三处公平性缺陷**。内容检查凡能跑的全过（事实标记 5/5、http 交叉
命中、文件内容命中、python_run 退出码 0）：

| 跑法 | 结果 | 卡点 |
|---|---|---|
| 任务集原样 | 0/6 verified | 提示词从未给 CP-3 终报 JSON 结构，6/6 挂在"终报提取失败" |
| + 终报格式说明（REPORT_SHAPE_HINT） | 0/6 verified | 提取 6/6 成功、内容检查全过，但判定器要求 criterion 与 expected_output 逐字一致，提示词从未把验收项原文给模型 |
| + 验收项原文 | 3 verified（file-01 / file-02 / cross-01） | research-01 partial、browser-01 / coding-01 rejected，见下 |

第三跑剩余三项的判定理由逐项复现（判定器 reason 原文定位）：

- `research-01`（partial）：账本里只有一条 harness 尾记条目
  （objective「模型终报原文」），`fact_markers` 核查本身不登记证据——
  模型无任何可引用的核查记录，引用必然落空。**harness 对接缺口**。
- `browser-01`（rejected）：理由原文"终报 unfinished 引用了不在
  expected_output 中的验收项：未能实际访问 https://example.com……"。
  模型引用全部合规（criterion 逐字 + URL 命中账本「独立抓取」条目），
  只是诚实地把"未能实时核验"写成了说明文字放进 unfinished——而逐字
  契约从未在任务里讲清。**任务信息缺口**（模型无浏览工具，抓取本就由
  harness 执行并登记）。
- `coding-01`（rejected）：理由原文同类——unfinished 里写了"需执行
  python solution.py，确认所有断言通过……"。测试由 harness 实际执行
  并已登记 run_python 证据（退出码 0），模型引用亦合规。**任务信息缺口**。

本次修复（不弱化判定器、不改 CP-3 语义、不放宽逐字匹配）：

1. `evidence/live_model_taskset.json`：每个任务的 `system_guidance` 内嵌
   REPORT_SHAPE_HINT 原文，并写明逐字引用契约（criterion / unfinished
   只能逐字引用验收项原文、不得写说明文字）与验证分工（核查由 harness
   执行并登记，不要把待核查事项写进 unfinished）；每个任务的
   `user_prompt` 末尾附该任务 expected_output 原文清单；
   research-01 补引用指引（evidence_ref 写"事实标记核查"）、
   coding-01 / browser-01 补分工说明。
2. `live_model_evidence_harness.py`：`fact_markers` 全命中时登记一条
   objective 为「事实标记核查」的证据条目（缺标记不登记，引用落空、
   保持 partial）；顺带删除从未被接线的 `_REPORT_SYSTEM_PROMPT` 死代码
   （终报指引改由任务集随任务下发，为权威来源）。
3. 测试锁定：任务集每个任务必须自带形状说明与验收项原文；fact 核查
   登记 / 不登记两种路径各有 runner 级测试。

修复后的正式基线在合入后于干净 main 上重跑（opt-in live），逐项 verdict
见对应 PR 正文与运行报告（schema 不变，跨次可比）。

## 任务集扩展：覆盖 R5–R12 新能力（T6，2026-10-21）

原 6 任务（M-11/Q6）量不出 R 系列落地的 8 个新能力面，回归守护有盲区。
T6 新增 3 个任务，**只选免密钥 / 本地可验的**：

| 任务 | 能力面 | 证据条目来源 |
|---|---|---|
| `calendar-01` | R5 ICS 日历 | `file_content` 登记「文件产物写出：event.ics」；`ics_parse` 用仓库自身 `calendar_connector.parse_ics` 做语义解析，全命中时登记「ICS 解析核查」 |
| `fx-01` | R7 汇率换算 | `file_content` 登记「文件产物写出：conversion.json」（JSON 解析 + 三次换算数值命中） |
| `rss-01` | R3 RSS 提取 | `file_content` 登记「文件产物写出：headlines.txt」（三条标题 + 三条链接命中） |

选型说明：

- R2（web search）未纳入——裸模型无法调用工具，基线只能量"工具形状输出"
  而非工具调用本身；且唯一可用的公共 SearXNG 实例有网络漂移风险，不适合
  当回归基线（`http_observation` 对"页面本身变化属环境漂移"的教训已写在
  harness 里）。R6/R9/R10（邮件/多媒体/消息）需用户凭证，不进基线。
- 三个新任务沿用 Q6 公平性写法：`system_guidance` 内嵌 REPORT_SHAPE_HINT
  原文、user_prompt 末尾附验收项原文清单、逐字引用契约与验证分工说明；
  不改判定器、不改 CP-3 语义。
- schema 有序升级 `zn-live-model-taskset/v1` → `v2`：harness
  `SUPPORTED_TASKSET_SCHEMAS` 对两版都读；v1 的旧 6 任务文件可直接被新
  harness 加载、跑、对比（报告 schema 仍是 `zn-live-model-evidence/v1`，
  跨次可比，T5 对比工具照常读取）。

## 报告

`evidence/runs/<run_id>.{json,md}`，schema `zn-live-model-evidence/v1`
（固定字段集，跨次可对比；`sample-dry-run.*` 为格式样例）。
报告含：任务 id / 域 / 模型名 / verdict / 失败类 / 耗时 /
缺失清单 / 关键证据摘录。`_scratch/` 为隔离产物目录，不提交。

## 测试

`tests/zn_agent/core/test_live_model_evidence_harness.py`：任务集 schema 校验、
分类逻辑、终报提取、闸门三态、runner 四条路径 + 干闸门跳过、
报告往返与写出——全部 mock，不触网，随 CI 正常跑。
真实模型调用只出现在 opt-in 路径，默认 CI 不受影响。
