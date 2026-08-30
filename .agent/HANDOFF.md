# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Current objective

Continue vertical product closure from the managed-browser ordinary Work path while keeping changed repository truth synchronized in the same coherent slice.

The newest browser product capability is deliberately narrow but now user-meaningful:

```text
ordinary durable Work
+ one explicit HTTP(S) URL
+ one quoted exact accessible checkbox name
+ explicit checkbox intent
+ unambiguous check / uncheck state
-> managed Chromium
-> exact unique visible native-checkbox semantic target
-> fresh resident-owned accessibility authority
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

PR #102 connected the first bounded checkbox mutation using one explicit `#dom-id`. PR #103 proved that path in real local Chromium.

PR #106 removes the DOM-id requirement for one deliberately bounded semantic path instead of exposing a general page-control surface:

- exactly one explicit HTTP(S) URL is required;
- mutation intent must explicitly concern a checkbox / 复选框;
- exactly one quoted accessible name is required;
- check/uncheck intent must be unambiguous in supported English/Chinese cues;
- no model invents destination, target name or desired state;
- generic text such as "open this page to check status" remains normal navigation;
- malformed checkbox mutation text cannot silently degrade into navigation-only behavior;
- permission remains origin-bounded navigation + page interaction only;
- text-entry, download/upload and sensitive-field authority remain disabled;
- provider sensing uses exact role `checkbox` + exact accessible name in the main frame;
- zero matches and multiple exact matches fail closed;
- target must be connected, visible and a native `input[type=checkbox]`; custom ARIA widgets are intentionally outside this first slice;
- no page-wide text, fuzzy candidate list or model-chosen target is exposed;
- CHECK/UNCHECK authority is bound to the fresh resident-owned accessibility target;
- before dispatch, the provider re-resolves the exact role/name and requires the same exact node;
- provider success still requires the same exact node to be re-observed in the requested checked state;
- the ephemeral session closes before successful Work completion;
- the mutation uses the durable side-effect guard, so the same event/signature is not blindly replayed after uncertainty.

The real Chromium fixture now includes an idless checkbox labelled `Email updates`; run `33299073385` completed successfully with the semantic Work E2E included.

Capability maturity: **connected + verified for bounded checkbox interaction with either technical DOM-id authority or exact accessible-name authority**. This is not general semantic browsing or browser product closure.

Still missing:

- a second user-meaningful semantic interaction class with an explicit independently verifiable outcome;
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
- PR #102 — ordinary Work -> bounded explicit DOM-id checkbox mutation.
- `33297131660` — managed-browser contracts and real Chromium E2E green after #102.
- PR #103 — real Chromium durable Work checkbox evidence.
- `33297795844` — managed-browser contracts + real Chromium E2E green on #103 checkpoint `9668f883...`.
- `33297994892` — full dev ZN CI success on coherent pre-semantic checkpoint `f1114b62...`.
- PR #105 — normal canonical promotion of the DOM-id checkbox slice; promotion merge checkpoint `a92ecb53...`.
- PR #106 — exact accessible-name native-checkbox sensing and ordinary Work interaction; dev merge checkpoint `061f80f3...`.
- `33299073385` — managed-browser contract suite + real Chromium E2E success on #106 checkpoint, including idless named-checkbox Work.
- `33299073393` — Work restart-recovery verification steps succeeded on the same #106 checkpoint; read final workflow conclusion live if needed.
- Full ZN CI for the semantic checkpoint and canonical post-promotion CI must be read live before claiming repository closure.

## Current product gaps

1. Semantic interaction is connected only for exact accessible-name native checkboxes in the main frame; a second safe semantic interaction class with an explicit postcondition remains missing.
2. Browser interruption recovery is fail-closed but not fully reconciled; unknown external mutation outcomes need bounded re-sense/reclassification where possible.
3. Broader safe click/focus/text/form Work flows remain unconnected; expand one vertical class at a time.
4. Upstream BUG/repair reporting remains local-only; bounded operator-controlled transport/intake/acknowledgement/reconciliation is missing.
5. User Browser Bridge remains architecture-only.
6. Installed public update observation remains partial; installed N -> N+1 replacement, rollback, signing and release trust remain approval-gated.
7. Unified health remains partial.

## Next dependency-ready work

Re-check live Git/CI first. The strongest dependency-ready browser continuation is not generic clicking. It is one second semantic vertical with a user-supplied target and explicit postcondition, for example:

```text
ordinary Work
+ explicit page URL
+ exact semantic button name
+ explicit expected destination URL
-> unique fresh semantic button authority
-> controlled click
-> independently observed expected URL
-> cleanup / durable result
```

This should fail closed on ambiguity, preserve exact target continuity and avoid exposing page-wide text. Compare that slice against the report path before implementation:

```text
local report outbox
-> bounded operator-controlled transport
-> durable dispatch / acknowledgement / reconciliation
-> maintainer intake
```

The browser path is currently more dependency-ready because report transport still needs a real operator-controlled endpoint/intake contract. Do not turn repository synchronization itself into the product milestone.

No force push, history rewrite, repository credential expansion, updater replacement, rollback, release signing or destructive identity/memory migration is authorized by this handoff.
