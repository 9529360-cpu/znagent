# ZN Maintainer Handoff

This is a lightweight engineering work site and fact index, not a chat transcript, execution script, or live Git database. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

SHAs, CI runs and branch states written here are **observed/verified checkpoints**. A fresh maintainer must query current `main`, `dev/zn-agent`, relevant `work/*`, open PRs and CI again instead of treating any checkpoint below as the current ref value.

## Recent verified checkpoint

Observed development checkpoint: merge `f586c2fc9816e5724f4a0a33a2126a8b3eb0f81b` on `dev/zn-agent`, merging PR #127, **Connect bounded upstream BUG report transport and intake**.

Executable evidence for that checkpoint:

- ZN CI `33358941761` completed with conclusion `success` for head `f586c2fc9816e5724f4a0a33a2126a8b3eb0f81b`.
- The transport/intake tranche therefore has repository-native full ZN CI evidence, not only static code review.
- Hosted clean-install/release-candidate jobs that fail before any step executes remain runner-allocation/infrastructure evidence unless a later run actually executes product steps.

Canonical `main` was observed at `0dbec575fc128bd1cc1837e7485b5a37e0ac8393` before this handoff update. Treat that SHA only as an observation checkpoint and re-query live refs before promotion or comparison.

## Upstream BUG / repair reporting reality

The former transport/intake lane is no longer merely planned or isolated. PR #127 is merged into `dev/zn-agent` and the merged checkpoint above has full ZN CI success.

The implemented resident-side path now includes:

- bounded privacy-safe local BUG report formation and durable outbox accounting;
- explicit operator-configured HTTPS transport;
- durable reservation before external dispatch;
- no blind automatic replay after uncertain external outcome;
- explicit reconciliation path;
- maintainer-side bounded intake/deduplication primitive;
- resident/provider configuration wiring for the transport.

This is not yet a complete product loop. Important remaining gaps include:

1. reconciliation semantics still need review so an ambiguous HTTP 404 cannot incorrectly prove authoritative absence and unlock a duplicate external side effect;
2. the persistent daemon/RPC/desktop control surface does not yet expose the explicit dispatch/reconcile actions;
3. maintainer intake is a storage/protocol primitive, not yet a deployed HTTP service;
4. authenticated transport is being developed separately and must remain credential-reference based rather than embedding secrets in resident config/status.

Normal installed ZN still has no official repository push, PR, merge, release or signing authority.

## Active durable work

`work/upstream-report-auth` is an **active** lane because it has durable Git evidence and an open PR: draft PR #128, **Protect upstream report transport with credential references**.

At the last observed comparison against `dev/zn-agent` checkpoint `f586c2fc...`, the branch had 4 unique commits and no behind commits. Re-query the PR and branch before editing or merging it; these counts are an observation, not a permanent live-state claim.

The lane is intended to keep maintainer endpoint credentials behind ZN's existing credential-reference boundary and out of resident config/status/database evidence. It must receive repository-native executable validation before merge.

## Handoff discipline

Do not write a lane as `active`, `in progress`, or `isolated` merely because a previous maintainer intended to work on it. Such claims require durable recoverable evidence: a real branch delta or corresponding open PR. Planned ownership without implementation evidence must be labeled `planned` or `reserved`.

Do not try to keep a literal “current HEAD” permanently synchronized inside this file. Updating this file itself changes HEAD. Record meaningful verified checkpoints when useful, then let the next maintainer recover live refs from Git/GitHub.

Update this handoff as a low-cost closeout step after a coherent engineering slice, explicit interruption/handoff, or a material change in product maturity/risk. Do not make every commit produce Markdown churn, and do not let documentation maintenance displace product work.

## Current product priorities

Re-rank these from live code and evidence rather than treating this list as command authority:

1. preserve at-most-once external BUG-report behavior by tightening reconciliation so only explicit authoritative receiver evidence can unlock retry;
2. complete authenticated upstream report transport without exposing repository or maintainer credentials to installed ZN;
3. expose explicit operator dispatch/reconcile through the real resident control surface, without automatic health-driven upload;
4. close the maintainer intake deployment/authentication path;
5. continue broader ZN product gaps only after re-checking whether a higher-severity identity, memory, lifecycle, security or main-path issue has appeared.

## Safety / authority boundary

No force push, history rewrite, repository credential expansion, updater replacement, rollback, release signing, destructive identity/memory migration, or self-approval of maintenance safety rules is authorized by this handoff.

Normal reversible code changes, tests, work branches, commits, pushes, PRs, CI repair and low-risk branch synchronization remain ordinary maintainer work under repository rules.
