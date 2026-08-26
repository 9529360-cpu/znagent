# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Product capability ledger: [`ZN-PRODUCT-CAPABILITY-MAP.md`](ZN-PRODUCT-CAPABILITY-MAP.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## Current checkpoint - 2026-08-26

M10 canonical source promotion remains complete. Ordinary development remains on `dev/zn-agent`; `main` was not modified in this stage.

Current focus implementation chain:

```text
61d3bc36b4f18697f5ab5f68da9d52c17c9da97f
feat: add exact managed browser focus lifecycle

7fd6f191f2f099b86d3573fca4be06fc64783211
fix: make resident timestamps freshness-safe

37f273a43a07d3d316055a47019da4fffe4bb9a3
ci: cover browser freshness clock changes
```

Status: **VERIFIED NARROW REAL-CHROMIUM MANAGED-BROWSER FOCUS; FINAL DOCUMENTATION-HEAD NORMAL WINDOWS CI STILL REQUIRED**.

## Managed-browser focus is now a real narrow lifecycle

The first target mutation is implemented without widening Playwright into a generic tool surface.

Call chain:

```text
BrowserTargetQuery(DOM_ID, main frame)
-> PlaywrightManagedBrowser.observe_target()
-> bounded ZN BrowserTarget + transient provider-local exact element handle
-> BrowserActionAuthority from the exact current observation
-> execution-time provider revalidation of the same current node
-> BrowserActionKind.FOCUS dispatch
-> fresh target re-observation
-> exact JS node continuity check
-> independent document.activeElement check
-> BrowserEffectEvidence(postcondition="same_exact_target_focused")
```

Important boundaries:

- the Playwright element handle is a disposable provider-local execution resource, not ZN identity;
- current page/target/permission/freshness authority is required before dispatch;
- same-shape node replacement before dispatch fails closed;
- replacement during dispatch fails closed even when DOM id and semantic shape remain the same;
- success requires both exact-node continuity and fresh focused-state evidence;
- provider handles are disposed when observations are replaced and when sessions close;
- `CLICK`, `TYPE_TEXT`, select/check/keyboard and generic provider methods remain unavailable;
- target sensing remains exact DOM-id, unique visible element, main frame only.

## Freshness collision found and fixed

The first full CI attempt exposed a real authority-freshness defect rather than a product-action defect.

At implementation head `61d3bc36`, both normal Windows CI and the managed-browser workflow failed the same focus freshness assertion because the pre-action and post-action observations could receive the identical microsecond timestamp. Since browser authority uses the observation timestamp as freshness identity, this could allow an extremely fast re-observation to appear indistinguishable from the previous one.

The test was not weakened. Commit `7fd6f191` changed resident `utc_now()` to be thread-safe and process-monotonic: if the platform wall clock repeats or moves backward relative to the previous emitted timestamp, the next emitted timestamp advances by one microsecond. This preserves the existing ISO UTC contract while preventing same-process freshness collisions.

Commit `37f273a4` also adds `runtime/python/zn_agent/core/models.py` to the managed-browser workflow path filter because the shared timestamp source now directly affects browser authority/freshness behavior.

## Real managed Chromium verification

Dedicated workflow:

```text
run 32963487090
head 37f273a43a07d3d316055a47019da4fffe4bb9a3
Windows local managed Chromium E2E   success
```

Verified in the real Windows Chromium runtime:

```text
35 browser/core tests   OK
2 real Chromium E2E     OK
```

The real E2E includes:

```text
test_local_headless_chromium_observes_targets_focuses_exact_node_and_verifies_navigation ... ok
test_metadata_floor_survives_private_network_permission ... ok
```

This proves the narrow target-sensing -> exact-node focus -> independent focused-element evidence path on actual local Chromium, plus the existing navigation/network-safety evidence.

## Other verified browser foundations retained

Previously verified slices remain:

- resident-owned browser session/permission/query/target/observation/action/authority/effect contracts;
- lazy resident ownership and shutdown cleanup of managed Chromium;
- real local headless Chromium navigation with fresh authority and observed final URL;
- bounded exact-DOM-id/main-frame target sensing;
- stale target/authority rejection;
- password target fail-closed behavior without explicit sensitive-field permission;
- no raw input value/HTML/uncontrolled page dump in target observation evidence;
- real Windows interactive Edge default-UIA sensing of a focused HTML input without forced renderer accessibility or user-profile copying.

The User Browser Bridge proof remains sensing-only and does not prove control of the user's authenticated browser session.

## Current browser product truth

Browser is not complete.

Verified narrow/foundation slices now include:

- managed navigation;
- managed exact DOM-id/main-frame target sensing;
- managed exact-node `FOCUS` with execution-time revalidation and independent postcondition evidence;
- real local Chromium proof for those slices;
- isolated-profile real Edge UIA focused-input sensing proof.

Still incomplete:

- managed `CLICK`;
- managed `TYPE_TEXT`, select/check/keyboard and other mutations;
- iframe/child-frame and generic accessibility target sensing;
- multiple-target/disambiguation UX;
- multi-tab/popup/frame lifecycle;
- headed managed-browser product UX;
- screenshots/visual target fusion;
- download/upload/file-picker authority;
- persistent managed profile policy;
- cloud browser adapter;
- browser crash/health/recovery lifecycle;
- complete DNS-rebinding/network-sandbox hardening;
- formal Chromium/Playwright release packaging;
- authenticated User Browser Bridge attachment/session/tab/permission/mutation lifecycle;
- browser permission UX and MFA/sensitive-field handoff.

Desktop text mutation remains limited to the already-focused empty native Win32 `Edit`; WPF/Edge current-text sensing must not be treated as browser text-mutation authority.

## CI truth at this document update

The implementation head `61d3bc36` had a failed normal CI and failed managed-browser contract run due solely to the timestamp freshness collision described above. Its interactive Windows workflow succeeded.

The corrected browser/CI head `37f273a4` has exact-head managed-browser E2E success in run `32963487090`. A final exact-head normal Windows CI is still required on the final documentation HEAD before this stage is considered fully synchronized.

Do not report a final docs HEAD as fully CI-verified until its normal Windows workflow completes successfully.

## Development-history audit note

An earlier empty root `noop` commit remains visible in history and was removed by a later normal fast-forward commit; no history rewrite was used.

During this maintenance pass, an accidental temporary file `docs/.tmp` was also created in commit `e3eb38cce090c6c268866f911cffc0d5ce288636` and removed immediately by normal fast-forward commit `37fe40556caafb9113a08c1e22d2beb519fc64b5`. It is absent from the product tree. No force push or history rewrite was used to hide the mistake.

## Next implementation order

The next browser action is `CLICK`, but only after the final documentation HEAD has green normal Windows CI.

Preferred order:

```text
1. finish final docs exact-head normal Windows CI
2. trace CLICK's real provider/action/effect call chain
3. reuse current target authority + exact-node revalidation boundary
4. implement one narrow click lifecycle only
5. independently verify a click-specific postcondition from fresh reality
6. add unit + real Chromium evidence
7. only then consider TYPE_TEXT
```

Do not infer click/type support from focus support and do not expose a generic Playwright method surface.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing and destructive self-maintenance changes continue to require human approval.
