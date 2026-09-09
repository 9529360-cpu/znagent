# E2E-15 — Windows Desktop bounded unexpected-modal recovery

Status: CLOSED representative path on current main.

Updated: 2026-09-09

## User-facing scenario

Natural-language task:

> 找到昨天那份订单资料，把里面的编号拿到我现在开的软件里，找到对应记录并确认处理好了。

During the active Desktop step, the real WinForms fixture opens an unexpected same-process modal through `ShowDialog()` after the original target has already been grounded. The fixture does not reveal the modal HWND, RuntimeId, or recovery action to Resident code and does not dismiss the modal on Resident's behalf.

## Verified representative path

The implementation remains inside the existing Resident and existing pointer-click lifecycle. There is no DialogAgent, second router, second Work/store, second completion truth, or generic dialog framework.

Admission requires fresh evidence for one exact interruption:

- exact admitted parent HWND/PID/process;
- foreground changed away from that exact parent;
- exact same-process dialog;
- direct Win32 owner relation `GW_OWNER(dialog) == parent`;
- UIA `IsModal == true`;
- parent UIA interaction state is `BlockedByModalWindow`;
- exact dialog UIA subtree supplies the candidate Button controls;
- deterministic semantics identify exactly one safe defer/continue/close-notice action.

Before input, the exact dialog/Button authority is freshly revalidated, including dialog/parent/owner identities, Button RuntimeId/name and center. Stale or ambiguous evidence fails closed before input.

After one proven pointer dispatch, the implementation never blindly replays. Recovery is bounded and requires fresh proof that the exact dismissed dialog is absent and the exact parent is visible, enabled, foreground, identity-consistent and UIA `ReadyForUserInteraction`. Only then is the old Desktop grounding discarded and the original Work freshly re-sensed/re-grounded.

## Real Windows evidence

Historical PR acceptance included an earlier verified pre-documentation Windows Interactive run #282. The final PR head was `f1513a34b798fbb07cfc2d903f63d621c085e90e`.

PR #237 was merged through the normal GitHub path as:

```text
merge SHA: d5a5be80d6d35328685be07fc54be76d1bcc955c
```

On that merge SHA, post-merge canonical validation was green:

- ZN CI #1694: success;
- ZN Windows Interactive Desktop E2E #293: success, including isolated E2E-15 and the complete current product-route interactive suite;
- ZN Work Recovery E2E #329: success;
- ZN Managed Browser E2E #279: success.

The current-main isolated E2E emitted:

```json
{
  "dialog_dispatch_count": 1,
  "is_modal": true,
  "parent_interaction_state": 3,
  "safe_action": "稍后继续",
  "unsafe_update_count": 0,
  "modal_absent": true,
  "parent_ready": true,
  "same_root_work": true,
  "old_edit_runtime": [42, 67832336],
  "fresh_edit_runtime": [42, 67897872],
  "final_title": "ZN 对应订单记录已打开",
  "wait_for_input_idle": false
}
```

The important acceptance facts are:

- exactly one modal dismiss dispatch;
- the safe defer action is selected;
- the risky update action is never invoked;
- the modal disappears;
- the exact parent becomes ready again;
- the same Root Work continues;
- the original UIA target becomes stale and a different fresh RuntimeId is grounded;
- the final application state independently proves the original task completed.

`wait_for_input_idle` is deliberately telemetry, not a hard readiness oracle. Microsoft documents `WindowPattern.WaitForInputIdle` as framework-dependent and warns callers not to rely on it to determine exact idle readiness. The successful real run returned `false` while the stronger exact Win32/UIA recovery evidence proved the parent was usable and the Work completed.

## Safety boundary

This representative closure does not mean arbitrary Windows dialogs are autonomously handled.

Autonomous action is limited to one exact same-process directly owned UIA modal with one uniquely safe semantic defer/continue/close-notice action. The path fails closed for, among other cases:

- ambiguous safe candidates;
- stale dialog or Button evidence;
- cross-process dialogs;
- wrong owner relationships;
- credentials/password prompts;
- UAC/elevation/security prompts;
- save/discard/delete/overwrite decisions;
- file pickers;
- payment/purchase decisions;
- installer/restart/update decisions that alter system state;
- other dialogs whose semantics are not deterministically safe.

No modal side effect is replayed after dispatch uncertainty or after a recorded successful dispatch.

## Regression gates

Before merge, the final PR head passed its applicable exact-head gates. After merge, current `main` at `d5a5be80d6d35328685be07fc54be76d1bcc955c` passed the canonical validation listed above.

An unrelated E2E-28 dynamic-health timing flake exposed during the same development window was isolated to PR #238. Its root cause was a test assertion placed after the Router's intentional 60-second OPEN-to-HALF_OPEN cap; #238 changed only the guarded acceptance ordering, preserved Router semantics, passed the real E2E-28/34 acceptance and ZN CI, and was merged separately first as `8cd2ff73038bbdba33017f71d91893296b7c082c`.

## Closure

The merge and post-merge conditions have now been satisfied.

`CLOSED — E2E-15 bounded Windows unexpected modal recovery representative path is verified on current main.`
