# ZN Agent Handoff

Updated: 2026-08-28

## Current goal

P1 shared side-effect-attempt persistence, P2 bounded cumulative accounting/learning durability, P3 managed-browser frontier reconciliation, and the bounded P4 resident-owned live-page registry are complete and CI-verified. P5 broader Work checkpoint/restore remains **PARTIAL**: its first bounded ingress-checkpoint slice is complete and CI-verified, while general per-task restore/rollback remains open.

Broader Work durability remains **PARTIAL**. Nineteen concrete crash/restart windows are closed and verified. The nineteenth window covers an accepted Work task whose user message is durable but whose resident event does not yet exist; a short-lived ingress checkpoint restores the exact pending event/message/run linkage without executing it or creating replay authority.

A new product/architecture contract has been added for resident intelligence. It does **not** claim new runtime implementation. The governing direction is now explicit:

```text
resident-owned built-in competence
+ resident-owned learned competence
+ replaceable external cognition for genuine novelty
= ZN intelligence
```

Mature low-level engineering/computer-use knowledge should crystallize into ZN-owned mechanisms and tests instead of remaining repeated prompt instructions. Repeated familiar work should become faster and require less redundant model use without weakening current-state sensing, postcondition verification or prediction-error interruption. Model/provider replacement must not erase mature resident-owned competence.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- branch HEAD immediately before this HANDOFF synchronization commit: `7b8292be494b191538101119ba31e91c9d4e292a`
- P5 Work ingress checkpoint implementation/proof head: `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`
- resident intelligence architecture commits before this HANDOFF sync:
  - `76e2bb2bd7fc6b393ad2f534d8fe1c0d926cece1` — `docs: define resident intelligence ownership`
  - `6f1c41872d8dfc03b447476d2275d35c82cc4c83` — `docs: define resident intelligence product contract`
  - `7b8292be494b191538101119ba31e91c9d4e292a` — `docs: align next phase with resident intelligence contract`
- PR #6 remains the draft development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed stages

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

Authoritative proof:

```text
ZN Work Recovery E2E run 33117334326  success
ZN CI run 33117334321                 success
```

### P2 - bounded cumulative accounting/learning durability

Status: **COMPLETE / CI VERIFIED**

Authoritative proof head `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`:

```text
ZN Work Recovery E2E run 33119871079  success
ZN CI run 33119871129                 success
```

### P3 - managed-browser frontier reconciliation

Status: **COMPLETE / CI VERIFIED**

`SELECT_OPTION` and CHECK/UNCHECK are **VERIFIED NARROW**. `PRESS` remains genuinely OPEN; no arbitrary provider-success result is completion authority.

Authoritative proof:

```text
ZN Managed Browser E2E run 33120809421  success
ZN CI run 33120848980                   success
```

### P4 - resident-owned live-page registry

Status: **COMPLETE / CI VERIFIED NARROW**

Commit `fffb0f4b84a76cef21a088167c9eb4faceb93afc` adds resident-owned monotonic `page-N` identities, provider-page discovery, closed-page eviction, stale target/observation cleanup, deterministic default-page promotion, and real Chromium proof.

Authoritative proof:

```text
ZN Managed Browser E2E run 33122620361  success
ZN CI run 33122620398                   success
```

### P5 - durable Work checkpoint / restore foundation, ingress slice

Status: **PARTIAL / FIRST SLICE COMPLETE / CI VERIFIED**

Commit `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82` adds a short-lived `work_ingress_checkpoints` owner before accepted Work crosses into resident-event persistence.

Verified semantics:

- exact message/event identities are preallocated and durable before the message/event boundary;
- a hard crash after accepted Work message but before resident-event persistence restores only the exact pending event, with zero attempts and no execution;
- a hard crash after event persistence but before `work_runs` linkage repairs linkage without duplicate event creation;
- message, event and WorkRun identities must agree or recovery fails closed;
- ingress checkpoint disappears after ordinary linkage is durable;
- this checkpoint grants no replay permission once resident execution/outside-world effects may have begun.

Authoritative proof:

```text
ZN Work Recovery E2E run 33124662199  success
ZN CI run 33124662367                   success
```

Final pre-discussion head `86b7ae3d0d89751628976de2368923d016a259cc` also had:

```text
ZN CI run 33125310706  success
```

No local repository test run is claimed. Repository self-hosted Windows CI is the verification authority.

## Product / architecture contract update - resident intelligence

Status: **ARCHITECTURE DEFINED / NOT CLAIMED IMPLEMENTED**

The discussion about ZN not behaving like a naive model-driven agent has been converted into durable repository architecture rather than left in chat.

### Governing additions

`ZN.md` now explicitly defines:

- three intelligence sources: built-in resident competence, learned resident competence and replaceable external cognition;
- known recurring mechanics should become ZN-owned observation/invariant/procedure/verification rather than recurring prompt reminders;
- some truths, such as whether a side effect happened or a file/browser mutation actually completed, must come from state/evidence rather than model confidence;
- repeated work should proceduralize rather than become repeated prompting;
- strong familiarity must not override current-world drift;
- repeated-task reliability, anomaly detection, uncertainty calibration, self-correction, restart continuity and provider independence are intelligence criteria.

New document `docs/ZN-RESIDENT-INTELLIGENCE.md` expands the product contract with:

- knowledge crystallization rules;
- file/browser/repeated-work examples;
- the hundred-and-first repetition rule;
- prediction-error interruption;
- model-quality vs ZN-quality separation;
- repetition, drift, provider replacement and restart benchmarks;
- a maintainer/product-manager test for future capabilities.

`docs/ZN-NEXT-PHASE.md` now references the resident-intelligence contract and adds the same invariants to the next-phase success criteria.

This architecture update does not change the current verified implementation count, does not create a twentieth crash/restart window, and does not make mature general procedural competence complete.

## Current risks / incomplete work

- broader Work durability remains partial beyond nineteen verified crash/restart windows;
- durable per-task Work restore/rollback for workspace mutations remains OPEN/PARTIAL;
- generic side-effect guarding covers commands and append-style writes, while ordinary overwrite `write_text` / `write_file` directly mutates the target and remains the next bounded recovery audit;
- any overwrite-file recovery design must distinguish pre-state, intended post-state and current-world evidence and must not overwrite user/external changes merely because an old checkpoint exists;
- resident intelligence contract is broader than current runtime implementation; do not report it as complete;
- general procedural competence, long-horizon repetition/drift benchmarks and mature anomaly handling remain incomplete;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, explicit tab/popup/frame ownership, headed managed-browser UX and authenticated User Browser Bridge remain incomplete;
- isolated parallel Work remains open;
- Windows M8 continuity and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1

Status: **COMPLETE / CI VERIFIED**

### P2

Status: **COMPLETE / CI VERIFIED**

### P3

Status: **COMPLETE / CI VERIFIED**

### P4

Status: **COMPLETE / CI VERIFIED NARROW**

### P5 - durable Work checkpoint / restore foundation

Status: **PARTIAL / IN PROGRESS**

Completed first slice:

1. traced Work ingress through message, event, `work_runs`, resident checkpoint/recovery and terminal truth;
2. identified and closed the pre-event accepted-message crash gap;
3. added exact pending-event reconstruction without replay authority;
4. added hard-crash restart tests and focused workflow coverage;
5. passed focused Work Recovery E2E and full working-tree ZN CI;
6. increased concrete verified crash/restart-window count from eighteen to nineteen.

Next bounded P5 audit:

1. trace ordinary overwrite `write_text` / `write_file` from `NativeActionIntent` through `SideEffectAwareBody`, semantic verification, Work artifact capture and restart behavior;
2. decide whether a safe resident-owned pre-write checkpoint can preserve bounded prior file state and intended post-state without becoming unconditional rollback authority;
3. require current-world identity/evidence before any restore, especially when a file changed externally after interruption;
4. use the new resident-intelligence contract as a product test: known file/recovery mechanics should become explicit ZN-owned competence, not model rediscovery;
5. add a twentieth crash/restart window only if a real overwrite/restore gap is actually closed and independently verified.

## Next real target

Re-read final branch and CI after this HANDOFF synchronization commit. If docs-only CI is green, continue P5 with the ordinary overwrite-file restore/recovery call chain. Keep `main` untouched during ordinary development.
