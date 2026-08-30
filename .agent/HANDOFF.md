# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Keep repository truth synchronized while continuing vertical product closure. The currently verified dev stage contains two important product increments beyond canonical main:

```text
resident defect truth
-> privacy-safe durable local report outbox

ordinary durable Work
-> deterministic managed-browser navigation
-> observed URL postcondition
```

Normal installed ZN still has no official repository push/PR/merge/release/signing authority.

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Canonical `main`: `4b3a7f1c1bc45565abaeb894702e96b1f1b2881d` from promotion PR #92.
- Current `dev/zn-agent`: `b1c86ee2a20a26954d54450160144f921365617c`, 24 commits ahead of main.
- Full dev ZN CI `33286758708` is fully green on `b1c86ee2...` across Source Boundary, Kernel/Python and Electron/TypeScript.
- The immediate main push run after PR #92 (`33285157720`) was cancelled, so it must not be described as green canonical evidence. Fresh main CI is required after the next promotion.
- Current reconciliation branch: `work/reconcile-dev-main-docs`.

## Verified product reality

### Resident defect reporting

PR #95 connects repeated high-confidence `probable_zn_defect` maintenance truth to a durable privacy-safe local upstream-report outbox.

Current guarantees:

- health truth commits before best-effort report projection;
- repeated matching incidents deduplicate into one local envelope;
- restart can repair missing projection from durable maintenance-task truth;
- external payload uses installation-scoped pseudonymous incident/component tokens;
- raw error text, local paths, organ, task id, health fingerprint, repository identity and credentials are not exposed;
- different installations cannot directly correlate the same incident token;
- status explicitly says `authority=local_outbox_only`, `transport_available=false`;
- future transport must reserve dispatch durably; ambiguous results are `outcome_uncertain` and cannot be blindly replayed.

This is connected + locally verified, but remote transport/intake/acknowledgement is still missing.

### Managed browser ordinary Work entry

PR #96 connects one narrow natural user path to the already-owned managed-browser Body:

```text
ordinary Work
+ exactly one explicit HTTP(S) URL
+ unambiguous navigation cue
-> browser_navigate
-> managed Chromium
-> independently observed current URL
-> durable Work result
```

Multiple URLs, malformed URLs, embedded credentials, or prose that only discusses a URL do not create browser authority. The model does not invent the destination.

This closes navigation only. General page sensing, clicks, forms/text entry, downloads/uploads, stale-target recovery and the separate user-browser bridge remain incomplete.

### Source-maintenance authority

Trusted source-maintenance can still investigate, derive bounded repairs, execute in isolated `work/*`, run regression/diff checks, require independent semantic review, recover pending reviews, clean rejected attempts, and produce verified `local_commit_only` accepted-repair commits.

Ordinary installed ZN has no repository credential or official repository mutation authority.

## Exact evidence

- `33284716266` — targeted resident report-outbox validation success.
- PR #95 / merge `52a53965069b714c2d5ff376ac1967b1d8df0f80` — reporting-aware resident + privacy-safe durable local outbox.
- `33286593120` — ordinary user-entry browser navigation regressions + real local Chromium Work E2E success.
- `33286655544` — same natural path through durable `ResidentWorkLedger` + existing Chromium E2E success.
- PR #96 / merge `b1c86ee2a20a26954d54450160144f921365617c` — ordinary Work -> managed-browser navigation.
- `33286758708` — full dev ZN CI fully green on `b1c86ee2...`.

## Maintenance drift found in this takeover

The repository rules already required documentation reconciliation and timely promotion, but execution after #95/#96 did not close those steps. Result:

- `dev/zn-agent` became 24 commits ahead of `main`;
- `docs/ZN-IMPLEMENTATION-STATUS.md` and this HANDOFF still described the #92/#93/#94 stage;
- a fresh maintainer would therefore recover stale state and potentially duplicate or mis-prioritize work.

This is being corrected as one coherent reconciliation/promotion slice. Going forward, changed product truth must be reconciled in the same verified slice; documentation and HANDOFF are not deferred cleanup after a stage is already considered complete.

## Current gaps / risks

1. Complete this reconciliation branch through normal PR -> dev, verify CI, then promote the stable dev stage to `main` and require fresh main CI.
2. Upstream BUG/repair reporting remains local-only; bounded transport/intake/acknowledgement/reconciliation is the next missing layer if that path is chosen.
3. Managed browser remains navigation-only for ordinary Work; broader page observation/action/postcondition/recovery is still missing.
4. User Browser Bridge remains architecture-only.
5. Installed public update read/verify/update-available observation is still not fully product-closed.
6. Installed N -> N+1 replacement, rollback, signing and release trust remain approval-gated.
7. Unified health remains partial.

## Next dependency-ready work

After branch/doc/canonical synchronization is complete, re-evaluate active callers and choose the highest-value vertical closure, likely one of:

```text
local report outbox
-> bounded operator-controlled transport
-> durable dispatch/acknowledgement/reconciliation
-> maintainer intake

ordinary managed-browser navigation
-> fresh page observation
-> one bounded interaction class
-> independent postcondition
-> failure/restart recovery
```

Do not turn repository synchronization itself into the next product milestone. It is engineering hygiene required to make future autonomous continuation trustworthy.

No force push, history rewrite, repository credential expansion, updater replacement, rollback, release signing or destructive identity/memory migration is authorized by this handoff.
