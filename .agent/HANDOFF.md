# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Current objective

Continue vertical product closure from the verified managed-browser Work path while protecting resident continuity, replay safety and privacy. Repository synchronization is required hygiene, not the product milestone.

The newest browser path is:

```text
ordinary durable Work
+ explicit start URL
+ quoted exact accessible button name
+ explicit click cue
+ explicit expected destination URL
-> browser_click_named_button_to_url
-> origin-bounded managed Chromium
-> fresh unique native button observation
-> exact-node revalidation
-> click
-> same-origin URL postcondition
-> durable Work result
```

ZN does not ask a model to invent the destination or target. Malformed button requests fail closed instead of degrading into navigation-only Work.

## Live-recovery rule

Do not trust exact branch SHAs in this file as live oracles. A new maintainer must query `main`, `dev/zn-agent`, relevant `work/*`, open PRs and current CI first.

At this checkpoint:

- `main` was `a92ecb5364d11dbc259977f941e3444cc3cfd0f0` when compared during takeover;
- product-code dev checkpoint after PR #111 is `ef7200976b649c5037924ee68cc9e4d8f2cbd1fb`;
- dev was 23 commits ahead of main and 0 behind at that comparison;
- stale PR #107 (old semantic status) and PR #101 (old pre-semantic focus implementation) were closed rather than merged into the current architecture.

Re-read all of those facts live before acting.

## What changed in this maintenance pass

### 1. Named-button restart recovery bug fixed

PR #108 had correctly made `browser_click_named_button_to_url` a durable Body-side guarded side effect, but `BrowserWorkResidentRuntime._generic_guarded_side_effect()` had not been updated. After process interruption, Body would refuse replay while resident recovery could misclassify the uncertainty as an ordinary local failure.

PR #109 fixed the ownership-layer classifier and added a restart regression that seeds a durable started attempt. The expected result is now `side_effect_recovery`, `replay_blocked=true`, `decision=user_decision_required`, with no second dispatch.

### 2. Exact named-button action connected to ordinary Work

Before PR #110, the exact semantic button action existed and was reachable through structured internal `body_action`, but ordinary user Work did not form it.

PR #110 adds one narrow natural path:

- exactly two explicit valid HTTP(S) URLs, in task order as start and expected destination;
- exactly one quoted accessible button name;
- explicit English/Chinese click cue;
- browser capability inferred only when this exact shape parses;
- zero model calls to invent target or destination;
- missing/ambiguous authority fails closed.

The existing Body/provider layer remains authoritative for same-origin policy, private-network policy, exact fresh semantic target evidence, target revalidation, click dispatch and URL postcondition.

### 3. Real Chromium E2E contract error repaired

After #110, Managed Browser E2E showed the actual button Work completed, then the test crashed with `KeyError: 'output'`. `ResidentWorkLedger.progress()` intentionally exposes a bounded `body_actions[].summary`, not raw/private `output`.

PR #111 changed only that assertion to `summary`. No product behavior or progress privacy boundary was broadened.

## Verified evidence

- `33334989444` — ZN Work Recovery E2E: success on `f62c19b...`, covering durable Work restart/recovery after the ordinary named-button connection.
- `33335159923` — ZN Managed Browser E2E: success on `ef720097...`; managed-browser contract tests and real local Chromium E2E both passed after the progress-contract repair.
- `33335159900` — full dev ZN CI for `ef720097...`; Electron/TypeScript and Source Boundary were already green when this handoff was written, while Kernel/Python was still running. Read the run live before claiming final workflow success.

Windows Clean Install and Windows Release Candidate can currently fail before any runner/step starts (`runner_id=0`, empty steps). The same failure mode was observed on the pre-takeover `eb9d761...` checkpoint, so it is not evidence of a browser regression. Do not weaken signing/release/update trust merely to clear this infrastructure condition.

## Current browser maturity

Verified/connected ordinary Work now includes:

- exact URL navigation;
- exact DOM-id checkbox set/unset;
- exact quoted accessible-name native checkbox set/unset;
- exact quoted accessible-name native button click with explicit same-origin destination.

Semantic sensing is deliberately bounded: exact user-supplied role/name, main frame, unique visible supported native node, no page-wide candidate enumeration.

Browser side-effect uncertainty is fail-closed and replay-blocked, but cross-process automatic outcome reconciliation is not product-closed. Ephemeral sessions may be gone after restart, so unknown outside-world results cannot always be classified safely.

## Important privacy finding before text-entry work

Provider-level `BrowserActionKind.TYPE_TEXT` exists and has strong same-node/digest postconditions, but it is not safe to connect to ordinary Work yet.

`NativeBody._record()` currently persists full `BodyAction` args to `native_body_actions.action_json`. A naive Work path would therefore durably store raw text, potentially including tokens, passwords or other sensitive values. The next text-entry slice must first define a redacted/secret-safe durable action representation and prove restart/recovery semantics without leaking the entered text.

Do not bypass this by merely suppressing the public Work projection; the raw durable Body row is the relevant boundary.

## Other durable product facts

- Resident Self/identity, lived memory/reference continuity, Work/thread state and zero-model boot remain protected product continuity surfaces.
- Upstream BUG/repair reporting is connected only to a local privacy-safe durable outbox; network transport/intake/acknowledgement/reconciliation remains missing.
- User Browser Bridge remains architecture-only.
- Installed public update observation remains partial.
- Installed N -> N+1 replacement, rollback, signing and release trust remain approval-gated.
- Ordinary installed ZN has no official repository write/release credential authority.

## Next dependency-ready work

First read live Git/CI. Then prefer the highest-value complete vertical slice, currently likely one of:

```text
uncertain browser side effect
-> persist only the minimal reconciliation evidence needed
-> restart
-> safe re-sense/reconcile where possible
-> classify succeeded / failed / still uncertain
-> never blind replay
```

or, after fixing the persistence boundary:

```text
explicit user text-entry Work
-> exact semantic target
-> secret-safe durable action representation
-> TYPE_TEXT
-> same-node digest/length postcondition
-> failure/restart recovery
```

Compare those against the still-open report transport/intake closure before choosing. Do not resurrect old PR #101 wholesale; if focus becomes the best next capability, re-derive it from current semantic browser ownership and tests.

No force push, history rewrite, repository credential expansion, updater replacement, rollback, release signing or destructive identity/memory migration is authorized by this handoff.