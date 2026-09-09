# E2E-15 — Windows Desktop bounded unexpected-modal recovery

Status: representative path verified on PR head; final CLOSED wording is reserved until merge and post-merge `main` verification.

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

Exact-head Windows Interactive run #282 passed the isolated E2E-15 acceptance and then the complete current product-route interactive suite.

The isolated E2E emitted:

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
  "old_edit_runtime": [42, 74123372],
  "fresh_edit_runtime": [42, 74188908],
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

On the verified pre-documentation PR head:

- ZN Source Boundary / Windows: success;
- Electron / TypeScript / Windows: success;
- ZN Kernel / Python / Windows: success;
- ZN Work Recovery E2E: success;
- ZN Managed Browser E2E: success;
- ZN Windows Interactive Desktop E2E #282: success, including isolated E2E-15 and the full current product-route interactive suite.

An unrelated E2E-28 dynamic-health timing flake exposed during the same development window was isolated to PR #238. Its root cause was a test assertion placed after the Router's intentional 60-second OPEN-to-HALF_OPEN cap; #238 changed only the guarded acceptance ordering, preserved Router semantics, passed the real E2E-28/34 acceptance and ZN CI, and was merged separately before this PR was rebased/merged forward.

## Closure rule

Do not use final `CLOSED` language for E2E-15 until:

1. documentation-sync head has applicable exact-head gates green;
2. PR #237 is merged through the normal GitHub path;
3. current `main` is re-queried;
4. post-merge canonical checks are green on the merge SHA.

Only after those steps is the final verdict allowed:

`CLOSED — E2E-15 bounded Windows unexpected modal recovery representative path is verified on current main.`
