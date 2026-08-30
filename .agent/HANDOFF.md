# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Current objective

Continue vertical product closure from the managed-browser ordinary Work path while keeping changed repository truth synchronized in the same coherent slice.

The newest browser product capability is deliberately narrow:

```text
ordinary durable Work
+ one explicit HTTP(S) URL
+ one explicit #dom-id
+ unambiguous check / uncheck intent
-> managed Chromium
-> fresh exact checkbox target authority
-> CHECK / UNCHECK
-> same-exact-node checked-state postcondition
-> session cleanup
-> durable Work result
```

Normal installed ZN still has no official repository push/PR/merge/release/signing authority.

## Repository recovery rule

Do not trust an exact `main`/`dev` SHA written in HANDOFF as a live oracle. Updating HANDOFF changes Git HEAD, and normal promotion adds a merge commit. A fresh maintainer must query live refs first.

Exact SHAs and run IDs below are evidence checkpoints only.

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

### Managed browser ordinary Work

PR #96 connected the first natural ordinary Work path: exactly one explicit safe HTTP(S) URL plus an unambiguous navigation cue forms `browser_navigate`, uses resident-owned managed Chromium, independently re-observes the current URL, and completes/fails durable Work without asking a model to invent the destination.

PR #102 connects one existing provider interaction to the real Work caller rather than broadening all browser authority at once:

- exactly one explicit HTTP(S) URL is required;
- exactly one explicit `#dom-id` is required;
- check/uncheck intent must be unambiguous in supported English/Chinese cues;
- URL fragments are not treated as target authority;
- no model invents destination, target or desired state;
- permission is origin-bounded and grants only navigation + page interaction for this path;
- text-entry, download and upload authority stay disabled;
- after navigation, ZN freshly observes the explicit DOM-id target and requires checkbox role;
- CHECK/UNCHECK authority is bound to that fresh observation;
- provider success requires the same exact node to be re-observed in the requested checked state;
- the ephemeral session closes before successful Work completion;
- the mutation uses the durable side-effect guard, so the same event/signature is not blindly replayed after uncertainty.

PR #103 adds a real local Chromium durable Work E2E for this mutation. The local fixture grants private-network authority explicitly in the structured E2E payload; natural ordinary Work does not silently gain private-network access.

Capability maturity: **connected + verified for one bounded checkbox interaction class**, not browser product closure.

Still missing:

- user-meaningful semantic/accessibility target discovery; the current ordinary path requires a technical `#dom-id`;
- general safe click/focus/text/form Work flows;
- complete reconciliation of an interrupted ephemeral mutation. Current behavior fails closed and refuses blind replay, but cannot always classify the outside-world result after process loss;
- User Browser Bridge.

### Resident defect reporting

PR #95 connects repeated high-confidence `probable_zn_defect` maintenance truth to a durable privacy-safe local upstream-report outbox.

Guaranteed now:

- health truth commits before best-effort report projection;
- repeated matching incidents deduplicate into one local envelope;
- restart repairs missing projection from durable maintenance-task truth;
- external payload uses installation-scoped pseudonymous incident/component tokens;
- raw error text, local paths, organ, task id, health fingerprint, repository identity and credentials are excluded;
- status is explicitly `authority=local_outbox_only`, `transport_available=false`;
- future external dispatch must be durably reserved first; ambiguous outcomes become `outcome_uncertain` and are not blindly replayed.

Network transport, acknowledgement and maintainer intake are still missing.

### Source-maintenance authority

Trusted source-maintenance can investigate, derive bounded repairs, execute in isolated `work/*`, run regression/diff checks, require independent semantic review, recover pending reviews, clean rejected attempts, and produce verified `local_commit_only` accepted-repair commits.

Ordinary installed ZN has no repository credential or official repository mutation authority.

## Evidence index

- `33284716266` — targeted resident report-outbox validation success.
- PR #95 — reporting-aware resident + privacy-safe durable local outbox.
- `33286593120` / `33286655544` — ordinary managed-browser navigation user-entry + durable ledger + real Chromium evidence.
- PR #96 — ordinary Work -> managed-browser navigation.
- `33286758708` — earlier full dev ZN CI green on product checkpoint `b1c86ee2...`.
- PR #102 — ordinary Work -> bounded explicit checkbox mutation.
- `33297131660` — managed-browser contract suite and real local Chromium E2E green after #102; includes browser Work checkbox core tests.
- `33297131654` — Source Boundary, full Kernel/Python core tests and Electron/TypeScript jobs all reached success on #102 checkpoint `f5a87ed...`; workflow conclusion later became `cancelled` only because PR #103's dev push superseded the final status-publication phase. Do not misreport the workflow itself as a completed-green run.
- PR #103 — adds real local Chromium durable Work checkbox evidence.
- `33297795844` — managed-browser contracts + real local Chromium E2E green on #103 checkpoint `9668f883...`, including the checkbox Work E2E.
- Read current full dev ZN CI and canonical post-promotion CI live before claiming final repository closure.

## Current product gaps

1. Managed browser needs bounded fresh semantic/accessibility sensing and user-meaningful target discovery; `#dom-id` is too technical for broad product use.
2. Browser interruption recovery is fail-closed but not fully reconciled; unknown external mutation outcomes need bounded re-sense/reclassification where possible.
3. Broader safe click/focus/text/form Work flows remain unconnected; expand one vertical class at a time.
4. Upstream BUG/repair reporting remains local-only; bounded operator-controlled transport/intake/acknowledgement/reconciliation is missing.
5. User Browser Bridge remains architecture-only.
6. Installed public update observation remains partial; installed N -> N+1 replacement, rollback, signing and release trust remain approval-gated.
7. Unified health remains partial.

## Next dependency-ready work

Re-check live Git/CI first. The strongest browser continuation is currently:

```text
ordinary managed-browser Work
-> bounded fresh accessibility/semantic observation
-> explicit user-meaningful target selection without invented authority
-> one controlled interaction
-> independent postcondition
-> interruption reconciliation / recovery
```

Before implementing it, compare active-caller value and security boundary against the alternative report path:

```text
local report outbox
-> bounded operator-controlled transport
-> durable dispatch / acknowledgement / reconciliation
-> maintainer intake
```

Do not turn repository synchronization itself into the product milestone. It is required engineering hygiene that keeps autonomous continuation trustworthy.

No force push, history rewrite, repository credential expansion, updater replacement, rollback, release signing or destructive identity/memory migration is authorized by this handoff.
