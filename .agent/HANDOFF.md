# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Current objective

Close one real managed-browser user scenario vertically rather than adding more disconnected primitives:

```text
explicit start URL
-> fresh exact semantic textbox observation
-> explicit text entry in one managed session
-> independently verified length/digest + exact-node continuity
-> fresh exact semantic button observation
-> submit click in the same session
-> independently re-observed explicit same-origin result URL
-> durable Work result
-> crash/restart recovery without blind replay
```

Normal installed ZN still has no official repository push/PR/merge/release/signing authority.

## Repository recovery rule

Do not trust exact SHAs below as live branch oracles. A fresh maintainer must query `main`, `dev/zn-agent`, relevant `work/*`, open PRs and current CI first.

The maintenance invariant remains:

```text
coherent product slice
-> targeted evidence
-> full/risk-proportional CI
-> reconcile changed status + HANDOFF
-> normal promotion
-> canonical CI
-> branch sync
```

Repository synchronization is engineering hygiene, not the product milestone.

## Current live worksite

### Baseline Body-health regression repair

The recent managed-browser named-text composition exposed a real active-caller regression in full ZN CI: `HealthAwareResidentRuntime` installed its Body dispatch health observer, then a later browser runtime replaced `resident.body` with `BrowserTextWorkBody`. The final active Body therefore bypassed durable Body health accounting.

The repair is on `dev/zn-agent` checkpoint `fb720e3a6facf3514fd8ff2952751082460487bd` (`Restore Body health observation after browser text composition`). `ReportingMaintenanceResidentRuntime` now rebinds the idempotent Body-health observer after final browser Body composition and before report projection.

Evidence currently known for that checkpoint:

- Managed Browser E2E `33338816911`: **success**.
- Work Recovery E2E `33338816913`: **success**.
- ZN CI `33338816909`: Source Boundary **success**, Electron/TypeScript **success**, Kernel/Python still executing the full core test step at the time of this handoff update. Do not claim the baseline full CI green until that job completes successfully.
- Hosted Windows Clean Install / Release Candidate jobs may fail with `steps=[]` / `runner_id=0`; classify those as runner-allocation infrastructure evidence unless executable steps actually ran.

If Kernel/Python fails, read the actual job log and repair the demonstrated root cause on dev before merging the product candidate below.

### Same-session form-submit candidate

Branch: `work/browser-form-submit`

PR: **#120 — Close one same-session managed-browser form submission**

This candidate exists because named textbox Work and named button Work were individually connected and verified but each owned a separate ephemeral navigation/session. Chaining them would reload the page and could discard entered state, so those primitives did not yet form a product-level form transaction.

Candidate behavior:

- one guarded Body movement owns navigation + text mutation + submit click;
- start URL and expected final URL are explicit; expected URL must remain same-origin;
- textbox and button use exact user-supplied accessible names and fresh semantic observations;
- text is explicit and bounded by the existing text-entry contract;
- provider text evidence must match the Body-computed request SHA-256, character length and UTF-16 units, with exact-node continuity;
- button authority is freshly observed immediately before the click;
- final success requires an independent same-session URL observation matching the explicit expected URL;
- the browser session closes before successful Work completion;
- natural English/Chinese Work parsing is deterministic and requires exactly two URLs, quoted text, exact textbox name and exact button name; no model invents destination, target, text or expected result;
- natural Work does not gain private-network authority; only the local E2E structured payload grants it explicitly;
- password/sensitive textbox targets remain refused by the existing semantic provider;
- plaintext is not duplicated into the durable Body action/result ledger; the user-authored Work/message and active Work state retain normal explicit-text semantics;
- the whole transaction is replay-guarded as one side effect;
- restart recovery accepts only a durable observed Body result whose text and submit evidence exactly prove the original intent; otherwise replay stays blocked and the recovery path remains fail-closed.

Candidate evidence added but **not yet runtime-verified**:

- `tests/zn_agent/core/test_browser_work_form_submit.py` — bilingual/fail-closed natural parsing, zero-model ordinary Work, same-origin boundary, Body-ledger plaintext redaction and bounded digest evidence.
- `tests/zn_agent/core/test_browser_work_form_submit_recovery.py` — durable observed-result recovery without replay and fail-closed incomplete-evidence recovery.
- `tests/zn_agent/e2e/test_windows_managed_browser_form_submit.py` — real local Chromium transaction whose `/done` result depends on the exact typed value still being present when the button is clicked, proving same-session state retention rather than merely sequential actions.
- dedicated Managed Browser and Work Recovery workflow path filters/compile/test lists include the new form modules so future form-only changes cannot bypass those suites.

PR #120 is currently intended to remain unmerged until the `fb720e3` baseline full ZN CI clears. After merge, its own dev ZN CI + Managed Browser E2E + Work Recovery E2E are the runtime authority. Code presence or mergeability is not validation.

## Verified product reality before #120

The development tree already goes materially beyond the older checkbox-only HANDOFF state:

- ordinary managed-browser navigation is connected and verified;
- semantic checkbox targeting by exact accessible name exists on dev and has real Chromium evidence;
- exact named semantic button Work is connected, verifies the explicit expected URL, has real Chromium evidence, and has durable observed-result restart recovery;
- exact named semantic textbox Work is connected, verifies same-node text digest/length state, keeps plaintext out of durable Body action/result history, has real Chromium evidence, and has durable observed-result restart recovery;
- browser result recovery refuses blind replay when outside-world mutation outcome is not durably proven.

Do not regress these paths back to technical `#dom-id`-only product claims when reconciling `docs/ZN-IMPLEMENTATION-STATUS.md` after the candidate is verified.

### Resident defect reporting

Repeated high-confidence `probable_zn_defect` maintenance truth projects to one durable privacy-safe local upstream-report outbox. Health truth commits before best-effort report projection; raw error text, local paths, repository identity and credentials are excluded from external payloads. Network transport, acknowledgement and maintainer intake are still missing.

### Source-maintenance authority

Trusted source-maintenance can investigate, derive bounded repairs, execute in isolated `work/*`, run regression/diff checks, require independent semantic review, recover pending reviews, clean rejected attempts, and produce verified `local_commit_only` accepted-repair commits. Ordinary installed ZN has no repository credential or official repository mutation authority.

## Current product gaps after this candidate

If #120 passes real validation, the strongest remaining gaps are:

1. Broader semantic multi-control scenarios remain partial; expand only through complete user scenarios, not a pile of provider primitives.
2. Browser interruption recovery remains fail-closed for external mutations that never reached a trustworthy durable observed result; bounded re-sense/reclassification is still incomplete.
3. Upstream BUG/repair reporting remains local-only; bounded operator-controlled transport, acknowledgement, reconciliation and maintainer intake are missing.
4. User Browser Bridge remains architecture-only; do not solve authenticated-session reality by copying profile credentials.
5. Installed public update observation remains partial; formal N -> N+1 replacement, rollback, signing and release trust remain approval-gated.
6. Unified health remains partial.

## Immediate continuation

1. Read live ZN CI `33338816909` (or the current replacement run if superseded).
2. If baseline Kernel/Python fails, fix that root cause on `dev/zn-agent` and revalidate before touching PR #120 merge state.
3. If baseline is fully green, re-read PR #120 head/mergeability and merge normally into `dev/zn-agent`.
4. Validate the merged dev checkpoint with full ZN CI, Managed Browser E2E and Work Recovery E2E. Treat hosted runner-allocation failures separately from executed code failures.
5. Repair any real candidate failures rather than weakening tests or restoring foreign control-plane behavior.
6. Once runtime evidence is green, reconcile `docs/ZN-IMPLEMENTATION-STATUS.md` and this HANDOFF to the verified semantic checkbox/button/text/form reality, then promote dev -> main normally and verify canonical CI.
7. Reassess product value. Strong next candidates are the report transport/intake loop or another complete browser user scenario; do not make Git synchronization itself the next milestone.

No force push, history rewrite, repository credential expansion, updater replacement, rollback, release signing or destructive identity/memory migration is authorized by this handoff.
