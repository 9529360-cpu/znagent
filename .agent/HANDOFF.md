# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Current objective

Continue vertical product closure from the verified report/browser stage while keeping repository truth synchronized in the same coherent slice.

The two newest product capabilities are:

```text
resident defect truth
-> privacy-safe durable local report outbox

ordinary durable Work
-> deterministic managed-browser navigation
-> observed URL postcondition
```

Normal installed ZN still has no official repository push/PR/merge/release/signing authority.

## Repository recovery rule

Do not trust an exact `main`/`dev` SHA written in HANDOFF as a live oracle. Updating HANDOFF changes Git HEAD, and normal promotion adds a merge commit. A fresh maintainer must query live refs first.

At the latest completed promotion checkpoint:

- PR #97 reconciled implementation status and HANDOFF after product PRs #95/#96;
- PR #98 promoted that verified stage to canonical `main`;
- `dev/zn-agent` was then fast-forwarded, without force, to the promotion merge so the long-lived branches were equal at that checkpoint;
- product-code head `b1c86ee2...` had full green ZN CI `33286758708` before the documentation-only reconciliation;
- canonical/post-promotion CI status must be read live from GitHub and must not be inferred from this text.

The maintenance invariant is:

```text
coherent product slice
-> targeted evidence
-> full/risk-proportional CI
-> reconcile changed status + HANDOFF now, not next session
-> normal promotion
-> canonical CI
-> branch sync
```

If a later change makes any of those facts obsolete, update the affected durable docs in that same slice. Do not leave documentation reconciliation as deferred cleanup.

## Verified product reality

### Resident defect reporting

PR #95 connects repeated high-confidence `probable_zn_defect` maintenance truth to a durable privacy-safe local upstream-report outbox.

Guaranteed now:

- health truth commits before best-effort report projection;
- repeated matching incidents deduplicate into one local envelope;
- restart repairs missing projection from durable maintenance-task truth;
- external payload uses installation-scoped pseudonymous incident/component tokens;
- raw error text, local paths, organ, task id, health fingerprint, repository identity and credentials are excluded;
- equivalent incidents on separate installations receive unrelated tokens;
- status is explicitly `authority=local_outbox_only`, `transport_available=false`;
- any future external dispatch must be durably reserved first; ambiguous outcomes become `outcome_uncertain` and are not blindly replayed.

This capability is connected + locally verified. Network transport, acknowledgement and maintainer intake are still missing.

### Managed browser ordinary Work entry

PR #96 connects one narrow natural user path to the managed-browser Body:

```text
ordinary Work
+ exactly one explicit HTTP(S) URL
+ unambiguous navigation cue
-> browser_navigate
-> managed Chromium
-> independently observed current URL
-> durable Work result
```

Multiple URLs, malformed URLs, embedded credentials, or prose merely discussing a URL do not create browser authority. ZN does not ask a model to invent the destination.

This closes navigation only. General page sensing, click/form/text-entry authority, downloads/uploads, stale-target recovery and the separate user-browser bridge remain incomplete.

### Source-maintenance authority

Trusted source-maintenance can investigate, derive bounded repairs, execute in isolated `work/*`, run regression/diff checks, require independent semantic review, recover pending reviews, clean rejected attempts, and produce verified `local_commit_only` accepted-repair commits.

Ordinary installed ZN has no repository credential or official repository mutation authority.

## Evidence index

- `33284716266` — targeted resident report-outbox validation success.
- PR #95 — reporting-aware resident + privacy-safe durable local outbox.
- `33286593120` — ordinary user-entry browser navigation + real local Chromium Work E2E success.
- `33286655544` — durable `ResidentWorkLedger` user-entry path + Chromium E2E success.
- PR #96 — ordinary Work -> managed-browser navigation.
- `33286758708` — full dev ZN CI green on product-code head `b1c86ee2...`.
- PR #97 — durable documentation reconciliation after #95/#96.
- PR #98 — canonical promotion of the report/browser stage.

Read current post-promotion/main CI live before making any new verified-state claim.

## Maintenance drift lesson

The earlier drift was an execution failure, not a missing rule: #95/#96 reached verified dev while main and durable docs still described the earlier authority/privacy stage. That allowed a future maintainer to recover stale priorities.

The correction is not "write more docs". The correction is that changed product truth, HANDOFF, promotion and branch synchronization are part of the same normal engineering closure. Dynamic Git state should be queried live rather than copied into prose that invalidates itself on the next commit.

## Current product gaps

1. Upstream BUG/repair reporting remains local-only; bounded transport/intake/acknowledgement/reconciliation is missing.
2. Managed browser remains navigation-only for ordinary Work; broader fresh page observation and bounded interaction/recovery are missing.
3. User Browser Bridge remains architecture-only.
4. Installed public update read/verify/update-available observation remains partial.
5. Installed N -> N+1 replacement, rollback, signing and release trust remain approval-gated.
6. Unified health remains partial.

## Next dependency-ready work

Re-check live Git/CI first, then choose the highest-value vertical closure from active caller evidence, most likely:

```text
local report outbox
-> bounded operator-controlled transport
-> durable dispatch/acknowledgement/reconciliation
-> maintainer intake

or

ordinary managed-browser navigation
-> fresh page observation
-> one bounded interaction class
-> independent postcondition
-> failure/restart recovery
```

Do not turn repository synchronization itself into the product milestone. It is required engineering hygiene that keeps autonomous continuation trustworthy.

No force push, history rewrite, repository credential expansion, updater replacement, rollback, release signing or destructive identity/memory migration is authorized by this handoff.
