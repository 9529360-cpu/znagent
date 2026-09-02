# ZN Maintainer Handoff

This is a lightweight engineering fact index. Real code, live Git refs and
actual test/CI results override this file whenever they disagree.

## Active product slice

Branch `work/desktop-task-consolidation` contains commit `7330e8d9`, based on
the cumulative PR #165/#167/#168 head. Its effective diff against
`dev/zn-agent` replaces the four task-specific desktop Runtime layers from that
stack with one typed desktop goal handled by the existing
`ResidentGoalRuntime`.

The production MRO now returns directly from
`ReportingMaintenanceResidentRuntime` to `NaturalFileWorkResidentRuntime`;
these classes are no longer in production or in the tree:

- `NaturalFileDesktopResidentRuntime`
- `NaturalFileDesktopSubmitResidentRuntime`
- `NaturalBrowserDesktopSubmitResidentRuntime`
- `NaturalNamedDesktopInputResidentRuntime`

File selection and fresh action-time source revalidation live in the existing
`natural_file_goal` authority boundary. Exact named Edit/Button discovery is
read-only and rejects unsafe Edit targets. `ResidentGoalRuntime` forms only one
current movement at a time, then re-senses before focus, text, submit and final
completion. The submit click remains non-replayable when its outcome is not
proven.

## Real user behavior added

The same production caller and mechanism now cover these ordinary requests:

- “把文件里的账号填进账号输入框，然后点查询。”
- “把文件里的订单号填进当前软件的订单搜索框，然后打开结果。”
- “找到昨天那份订单资料，把订单编号填到当前程序对应的搜索框，提交后确认结果已经打开。”

They all execute as: bounded workspace source discovery, exact safe current-app
Edit discovery, focus if needed, fresh source re-read, privacy-safe text digest
verification, exact Button discovery, one submit, and independent fresh
foreground-result verification. Ambiguous files and unsafe inputs stop before
desktop side effects. Already-correct text skips keyboard input but still
submits and verifies the result.

## Local evidence

- Consolidated desktop/negative tests: 13 passed.
- Existing resident-goal, browser-text and natural-file regression selection:
  17 passed.
- Full core discovery initially exposed one browser-result/file route being
  consumed by generic browser-language orientation before its existing bounded
  handler. The branch now bypasses proposal-only browser orientation for that
  already-typed task and retains its two-source agreement in durable
  Investigation facts; the repaired regression plus the new desktop scenarios
  pass locally.
- Remote run `33652385640` proved Source Boundary and Electron jobs on
  `43c2fa43`; its Python job predates the browser-result/file repair.
- Windows clean-install run `33592990443` passed on `43c2fa43`.
- Windows interactive run `33652390143` executed 18 tests: 14 passed and four
  existing browser-session/research tests failed (ambiguous visible pages,
  unstable title, and missing reference visits). It is real non-green evidence,
  not a runner-allocation failure and not proof of the new desktop task.

## Next verification

Push the branch, open one PR against current `dev/zn-agent`, and use repository
CI plus the Windows interactive desktop workflow as the next authority. Do not
merge the old stacked PRs #165/#167/#168 independently; their effective
task-specific Runtime design is superseded by this consolidation candidate.

The next product extension should add another source investigator (for example
browser evidence) to the typed goal, not another Runtime subclass or a new
task-specific action sequence.

## Safety boundary

No force push, history rewrite, private browser-profile copying, credential
expansion, updater replacement, rollback, signing, or destructive identity or
memory migration is authorized. A model may propose goal data, but it does not
own facts, target identity, action authority, non-replay decisions, or
completion judgment.
