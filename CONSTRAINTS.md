# CONSTRAINTS.md — ZN 仓库硬底线（AS-1）

> 这是机械检查的底线，不是提示词建议。`floor-guard`
>（`runtime/python/zn_agent/core/floor_guard.py` + `scripts/floor_guard.py`）
>在 CI 里对每个 PR 的 diff 做确定性判定：违规 → 检查失败；警告 → 必须在 PR 里交代。
>提示词可以被忽略、被绕过、被模型“理解错”；这份文件的规则由代码执行。

## 1. 不可压制项（没有任何静默例外）

**NEVER 为通过而改测试。** 具体包括：

1. **NEVER 压制注释**：`# noqa`、`# type: ignore`、`# pylint: disable`、
   `# nosec`、`// eslint-disable`、`// @ts-ignore`、`// @ts-nocheck`。
   压制 linter / 类型检查来掩盖问题，等同于删测试。
2. **NEVER 跳过测试**：`@pytest.mark.skip`、`@pytest.mark.skipif`、
   `pytest.skip(`、`@unittest.skip*`、`describe/it/test/suite.skip(`、
   `xit(`、`xdescribe(`、`fit(`、`fdescribe(`。跳过 = 红灯被遮住，不是绿灯。
3. **NEVER 删测试 / 删断言**：删除 `def test_*`、删除测试文件、删除测试中的
   `assert` / `expect` 断言。移动测试（删 + 在同文件原样加回）不算删除；
   改名测试（旧名消失、新名出现）算删除——旧测试的覆盖消失了，必须走例外流程。
4. **NEVER 空异常吞噬**：`except: pass`、`except ...: pass`、
   `except ...: ...`。异常必须被处理、被记录、或被显式重新抛出。
5. **NEVER stub 冒充实现**：非测试代码里的 `raise NotImplementedError`、
   `return NotImplemented`、`pass  # stub/todo`、非测试代码里 import
   `unittest.mock` / `mock`。没做完就写没做完，不要用占位符冒充完成。
6. **NEVER 伪造证据**：PR 里的测试结果、截图、对比数字必须来自真实运行。
   手写“已通过”、改截图、编数字，一经发现即按严重违规处理。
7. **NEVER 削弱底线自身**：删除或放宽本文件的规则、删 floor-guard 的拦截模式、
   删 floor-guard 的测试用例、删 CI 里的 floor-guard 调用、给 floor-guard 加
   “放行名单”。守卫没有放行名单——见 §4。

警告（不拦截，但必须在 PR 里交代，否则视为未完成）：
`pytest.xfail`、`@unittest.expectedFailure`、裸 `except:`、
`# pragma: no cover`、`// istanbul ignore`、非测试代码里的 TODO / FIXME、
删除非测试代码里的 `assert`。

## 2. 豁免判定（防误报，floor-guard 已机械实现）

以下情况 floor-guard **不**判违规，不是例外、不用申请：

- **禁令句**：该行本身在禁止这种写法，例如“NEVER add `# noqa`”。
  禁止压制 ≠ 使用压制。
- **字符串字面量**：模式出现在引号里，例如 `x = "# noqa"`，是文档/数据，不是生效的压制。
- **三引号字符串**：docstring 与测试 fixture 里引用模式，不生效。
- **既有代码**：floor-guard 只查 diff 的新增/删除行。仓库里已有的压制，
  在有人动到那些行之前不被追溯。动到了，就按新代码的标准判。

误报与漏报的取舍（已定）：宁可漏报、不可误报。漏报由人工审查补
（审查者只读 diff，漏网的压制在审查中可见）；误报会阻塞正常 PR，
所以启发式规则（禁令句、引号、三引号）一律朝“放过”倾斜。
`pytest.xfail` 只判警告是同一取舍：它仍运行测试，藏不住红灯。

## 3. 例外流程（显式批准 + 留痕，绝不静默放宽）

确实需要打破 §1 时（例如：平台专属测试在某 runner 上根本无法运行，
必须 skip；防御性 `except: pass` 守的是确实不可达的分支），按以下流程，
缺一不可：

1. **PR 正文写明例外申请**：破了哪条、为什么必须破、影响范围、
   替代保障（用什么别的手段守住这块覆盖）。
2. **批准**：由非作者的审查者批准。自己批准自己的例外 = 没有批准。
3. **留痕**：例外随 PR 合并进 Git 历史（PR 正文 + 代码注释里写清原因
   与批准人）。口头同意、聊天记录、私下约定，一律不算。
4. **有期限 / 有跟进**：例外必须带到期或跟进任务（例如“Windows runner
   修好后去掉 skip，见 #xxx”）。无期限的例外 = 永久放宽，不批。

**没有例外通道的项**：伪造证据（§1 第 6 条）、删除失败测试以掩盖回归、
静默放宽本文件。想改本文件的规则，见 §5。

## 4. floor-guard 本身不受信任

floor-guard 是检查工具，不是权威。它的判定规则：

- 只读 diff，不读运行时状态；不接线进任何运行时路径；不改既有行为。
- 本 workflow 是独立检查，**未**接进 `zn-ci.yml` 的必需检查门
  （`zn-ci.yml` 未动）；升为必需检查是单独的分支保护决策，不在本 PR。
- floor-guard 判违规时，检查变红；例外流程批准后，由人决定是否合入
  （检查仍红，但留痕 + 批准齐全时可合）。红检查 + 无批准 = 不合。
- floor-guard 判通过时，不代表代码没问题：它只查压制类模式，
  审查、测试、CI 其余检查照常。

## 5. 修订本文件

- **加规则**：直接提 PR，floor-guard 不拦（新增行不触发“规则被删”）。
- **删规则 / 放宽规则**：floor-guard 会判违规（删除了带
  NEVER / MUST / 禁止等关键词的规则行）。想合入，必须走 §3 例外流程：
  PR 正文写清删了什么、为什么、替代保障，并取得非作者批准。
  批准后合入，检查仍红留痕。
- **修订记录**：每次改动在本节追加一行（日期 + 改了什么 + PR）。

## 修订记录

- 2026-10-15：首版落地（AS-1）：不可压制项 + 豁免判定 + 例外流程 + floor-guard
  判定规则。PR 待填。
