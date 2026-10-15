# ZN Skill 写作检查清单（KWP-1 + AS-2，一次落地）

> 来源：anthropics/knowledge-work-plugins（Apache 2.0）与 addyosmani/agent-skills（MIT）。
> 只抄机制，不抄具体业务插件内容。本清单是 ZN 作者写新 Skill 时的唯一检查入口。
> AS-4（Evals Tier 1 + Tier 2，进 CI 的触发校验）已落地，见 §11。
> AS-1（floor-guard：不许为通过而改测试，机械检查）已落地，见 §12。

## 0. 先说清三个容易混淆的点

1. **文件名**：ZN 的 Skill 文件是小写 `skill.md`（`SkillStore` 只读 `skill.md`）；
   `SkillRouter` 优先读 `SKILL.md`、再回落 `skill.md`。新 Skill 写 `skill.md` 即可。
   本清单说“SKILL.md”时，指的就是这个文件。
2. **description 有两个上限**：清单上限（AS-2）是 **≤1024 字符**；ZN 运行时上限是
   **≤500 字符**（`skills.py` / `skill_routing.py` 的 `SkillStore` / `SkillRouter`
   超过即丢弃该 Skill）。写给 ZN 用的 Skill 必须同时满足两者——实际就是 **≤500 字符**。
   校验器把 >1024 判违规、(500, 1024] 判警告，绝不擅自放宽运行时上限。
3. **两个校验器互补，不是二选一**：`skill_routing.validate_skill_file`
   管 intake（触发条件、`allowed-tools` 白名单、正文 token 预算、外部 Skill 需人工复核）；
   本清单的 `skill_checklist.check_skill_writing` 管写作规范（引号触发短语、行数、
   绕过语言、风格启发）。新 Skill 提交前两者都要通过。

## 1. 规则总表（8 条，缺一不可）

| 编号 | 规则 | 机械 / 风格 | 判定 |
| --- | --- | --- | --- |
| C1 | description 用第三人称 + 引号触发短语 | 机械（引号）+ 风格（第三人称） | 校验器 + 人工 |
| C2 | 渐进披露三层齐全 | 机械（结构） | 校验器 + 人工 |
| C3 | 正文用祈使句短句 | 风格 | 人工为主，校验器给长句警告 |
| C4 | Common Rationalizations 表随 Skill 一起沉淀 | 人工 | 人工对照 §4 |
| C5 | Red Flags 一条都不能有 | 机械（部分）+ 人工 | 校验器 + 人工对照 §5 |
| C6 | Verification 证据清单随 PR 附上 | 人工 | 人工对照 §6 |
| C7 | description ≤1024 字符（ZN 实际 ≤500） | 机械 | 校验器 |
| C8 | SKILL.md <500 行；写流程，不写绕过方法 | 机械 | 校验器 |

## 2. C1 — description：第三人称 + 引号触发短语

description 必须同时说清**做什么**和**何时用**，且满足：

- **第三人称**：描述 Skill 本身，不描述作者或读者。
- **引号触发短语**：把用户会说的原话放进双引号，作为精确触发词。

✅ 好：

```yaml
description: "Fixes flaky CI tests. Use when CI fails intermittently, e.g. 'test passes locally but fails on CI'."
```

❌ 差（第一人称 + 无引号触发短语）：

```yaml
description: "I help you fix flaky tests when they fail on CI."
```

判定方法：校验器查引号（无引号 = 违规）；人看 description 是否以 “I / We / 我”
开头（是 = 改成第三人称）。“Use when …” 本身是可接受的触发句式，不算第二人称违规。

## 3. C2 — 渐进披露三层

| 层 | 内容 | 谁读 | 成本 |
| --- | --- | --- | --- |
| L1 短摘要 | frontmatter 的 `description` | 每次路由都读 | 最低 |
| L2 正文 | `skill.md` 正文：流程、步骤、判定 | 匹配后才读 | 中 |
| L3 references | `references/` 目录或正文 `## References` 节 | 按需加载单个文件 | 按需 |

规则：

- L1 只放摘要，绝不把流程塞进 description。
- L2 只放“本 Skill 必须知道”的流程；放不下的细节进 L3，不堆进正文。
- 正文超过约 120 行且没有 L3（无 `## References` 节、无 `references/` 目录）
  时，校验器给警告——把细节移进 `references/`。
- `scripts/` / `assets/` 只放执行时按需加载的文件，校验器不检查它们，
  但 `skill_routing.validate_skill_file` 会做脚本静态形状检查（不执行）。

## 4. C3 — 正文：祈使句短句

- 每步以动词开头：`Run …` / `Check …` / `Compare …`，不以 “I / We / 我” 开头。
- 一句只说一件事；散文行超过 25 词时校验器给警告，人来决定拆还是留。
- 条件写成 “If …，then …”，不写成叙述段落。

✅ 好：`Run the failing test three times. Record each outcome.`
❌ 差：`I usually run the failing test a few times and then I look at what
happens, and if it seems like it might be flaky I will try to rerun it.`

## 5. C4 — Common Rationalizations 表（借口 → 反驳）

每个 Skill 沉淀时，作者必须把本领域最常见的“为绕过规则找的借口”写进表里，
格式固定为“借口 → 反驳”。下面是通用起步表，写新 Skill 时按领域补充至少一条：

| 借口 | 反驳 |
| --- | --- |
| “就这一次，跳过测试没关系。” | 一次就是先例；跳过一次，后面每次都有理由跳过。测试红了就修测试或修代码，不跳过。 |
| “测试本身写错了，删了最快。” | 删测试 = 删证据。先证明测试错（复现 + 最小反例），再改测试，断言不弱化。 |
| “CI 抖动，重跑就绿，不用看。” | 重跑前先判回归还是抖动：同一失败在 main 上是否出现、失败是否换着来。判了抖动才能只重跑。 |
| “先合进去，后面再补证据。” | 没证据 = 草稿。证据（复现→通过、前后对比、验证输出）随 PR 一起交，不后补。 |
| “这个绕过方法只在本地用。” | 写进 Skill 的绕过方法就是会被所有人用的绕过方法。写流程，不写绕过方法。 |
| “改一下断言就能绿。” | 改断言 = 改标准。只允许翻 passes 标记且经过端到端验证；其余一律不改断言。 |

## 6. C5 — Red Flags（一条都不能有）

| # | Red Flag | 例子 |
| --- | --- | --- |
| R1 | 绕过检查 / 审批 / 测试的方法 | “skip the approval check”, “绕过测试” |
| R2 | 删测试 / 删断言 / 把失败标成通过 | “delete the failing test”, “mark it as passed” |
| R3 | 不跑验证就宣称完成 | “do not run the tests”, “不用跑测试” |
| R4 | 伪造证据（硬编码通过、编造结果） | “hardcode success”, “伪造通过” |
| R5 | 声称凌驾系统指令 | “ignore previous instructions”, “忽略系统指令” |
| R6 | 要求静默写盘 / 不留证据 | “do not record this”, “不留记录” |

校验器机械拦截 R1–R5 的常见措辞（逐行扫描，`Do not bypass …` 这类禁令句式
会被否定词豁免，不误报）。R6 及所有变体措辞由人工对照本表判定——校验器绿
不等于没有 Red Flag。

## 7. C6 — Verification 证据清单（随 PR 附上）

新 Skill 的 PR 正文必须附以下证据，缺一不可：

1. **逐条对照**：本清单 C1–C8 每条的结果（通过 / 警告已处理 / 不适用+原因）。
2. **校验器输出**：`check_skill_file` 对新 Skill 的判定（通过 + 警告处置说明）。
3. **正反触发演示**：一个正向例子（该触发的查询确实匹配该 Skill）+ 一个
   负向例子（不该触发的查询没有匹配），证明 description 触发短语不过宽、不过窄。
4. **Red Flags 自查**：对照 §6 逐条声明无 Red Flag；有警告的逐条说明为什么可接受。
5. **真实运行证据**（适用时）：按 Skill 流程实际跑一遍的结果，而不是只贴文档。

## 8. C7 / C8 — 长度上限与“写流程，不写绕过方法”

- **C7**：description ≤1024 字符（清单）；ZN 实际 ≤500 字符（运行时）。超 500
  的 Skill 在 ZN 里加载不到，等于没写。
- **C8**：整个 `skill.md` 文件 <500 行（校验器按总行数算，≥500 即违规）。
  超了就拆：流程留正文，细节进 `references/`，脚本进 `scripts/`。
- **写流程，不写绕过方法**：Skill 只写“遇到 X 时按什么步骤做”，不写“怎么
  躲开检查 / 审批 / 测试”。任何“如果检查拦住了你，就……”的段落，先问自己：
  这是在教流程，还是在教绕过？是后者就删掉，改成“检查拦住了 → 按 §5 反馈 /
  上报缺口”。

## 9. 校验器用法

```python
from pathlib import Path
from zn_agent.core.skill_checklist import check_skill_file

result = check_skill_file(Path("skills/flaky-test-fix/skill.md"))
print(result.passed, result.violations, result.warnings, result.layers)
```

- `passed` 为真只表示“无机械违规”；警告必须逐条处置（修掉或在 PR 里写明可接受的原因）。
- 校验器不联网、不执行脚本、不改任何文件；纯文本检查。
- 校验器不替代 `skill_routing.validate_skill_file` 的 intake 检查（见 §0 第 3 点）。

## 10. 不在本清单的事

- 不改 `SkillStore` / `SkillRouter` 的行为、不改 Skill 沉淀流程、不碰 workflows。

## 11. Evals（AS-4）：Tier 1 + Tier 2，进 CI

校验器绿 ≠ 写得好（见 §9）；Evals 是第二道机械防线：新 Skill 提交前，
两层校验都要通过。两层都是确定性的、零 token 的（不调模型、不联网、
不写文件），只读检查，不改变 `SkillStore` / `SkillRouter` 的运行时行为。

| 层 | 查什么 | 实现 | 失败 = |
| --- | --- | --- | --- |
| Tier 1 结构 | 本清单校验 + intake 校验 + 正文至少一个章节标题 + 本地链接全部可达 | `runtime/python/zn_agent/core/skill_evals.py` 的 `eval_tier1_file` | 违规（见下） |
| Tier 2 触发 | 正向引号触发短语经真实 Router 排进 top-k 且可激活；泛负向无关任务不触发；共享引号触发短语判碰撞违规；description 词集 Jaccard ≥0.6 判碰撞警告 | 同上，`eval_tier2_root`（用 `SkillRouter` 真实 `match` / `route`，不造玩具 ranking） | 正向未命中 / 负向误触发 / 共享触发短语 |

分层语义（与 §0 一致，不放宽运行时上限）：description `>1024` 字符判违规；
`(500, 1024]` 判警告（清单通过，但 `SkillStore` / `Router` 会丢弃该 Skill，
且 Tier 2 会报“磁盘上有但 Router 发现不了”警告）。Tier 1 中 intake 的
`description exceeds 500 characters` 原因被降为警告，不重复清单已有的
runtime-cap 警告，其余 intake 原因仍是违规。

碰撞是词法启发式：共享引号触发短语是真碰撞（触发分不清两个 Skill）；
Jaccard 只抓复制粘贴级近似描述，改写级语义相近可能漏网——那需要
embedding / 模型，本层故意不用。

本地跑：

```bash
# 仓库全量（Tier 1 扫全部 Skill 文件；Tier 2 跑 skills/ 目录，如存在）
PYTHONPATH=runtime/python python scripts/skill_evals.py
# 单个 Skill 根目录（子目录即 Skill 包，如 $ZN_HOME/skills），JSON 报告
PYTHONPATH=runtime/python python scripts/skill_evals.py --root <skills-root> --json
```

CI：`.github/workflows/zn-skill-evals.yml` 在 PR / push 到 main 时跑
仓库扫描 + `test_skill_evals.py`。该 workflow 是独立检查，未接进
`zn-ci.yml` 的必需检查门（`zn-ci.yml` 未动）；升为必需检查是单独的
分支保护决策，不在本 PR。

## 12. Floor-guard（AS-1）：不许为通过而改测试，机械检查

本清单的校验器管 Skill 写得好不好；floor-guard 管另一件事——
任何人（包括写 Skill 的人）都不许为通过而改测试。规则在仓库根
`CONSTRAINTS.md`，实现在 `runtime/python/zn_agent/core/floor_guard.py`
（只查 PR diff 的新增/删除行，不接线进运行时，不改既有行为），
CI 在 `.github/workflows/zn-floor-guard.yml`（独立检查，未接进
`zn-ci.yml` 必需检查门，升必需是单独的分支保护决策）。

拦截（违规）：压制注释（`# noqa`、`# type: ignore` 等）、skip 标记、
删测试 / 删断言、空 `except: pass`、stub 冒充实现、CONSTRAINTS /
floor-guard / 本 workflow 自身被放宽。警告（不拦截，PR 里交代）：
`pytest.xfail`、裸 `except:`、`# pragma: no cover`、TODO 标记、
删非测试代码里的 `assert`。禁令句、字符串字面量、三引号字符串里的
模式引用不判违规；例外必须显式批准 + 留痕，见 `CONSTRAINTS.md` §3。

本地跑：

```bash
# 对当前分支相对 origin/main 的 diff 做检查（与 CI 同一条命令）
git diff origin/main...HEAD | PYTHONPATH=runtime/python python3 scripts/floor_guard.py
# 单元测试
PYTHONPATH=runtime/python python3 -m pytest tests/zn_agent/core/test_floor_guard.py -q
```
