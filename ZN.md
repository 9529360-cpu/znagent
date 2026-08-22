# ZN Agent — Product and Engineering Blueprint

> Active development branch: `dev/zn-agent`
>
> This document is the architecture and product contract for ZN.
>
> Current implementation details live in [`docs/ZN-IMPLEMENTATION-STATUS.md`](docs/ZN-IMPLEMENTATION-STATUS.md). Mature-source extraction rules and the current extraction ledger live in [`docs/ZN-SOURCE-EXTRACTION.md`](docs/ZN-SOURCE-EXTRACTION.md). Self-maintenance, self-repair and self-update rules live in [`docs/ZN-SELF-MAINTENANCE.md`](docs/ZN-SELF-MAINTENANCE.md). Repository handoff rules live in [`AGENTS.md`](AGENTS.md).
>
> **ZN.md must stay ahead of architecture changes.** Code is authoritative for what currently exists; this file is authoritative for where the product is going and which directions are prohibited.

---

## 0. Development contract: inspect first, document architecture, then code

The repository started from a mature inherited codebase. A locally convenient implementation can therefore accidentally keep the old product as ZN's real control plane.

The required development order is:

```text
inspect current repository code
→ identify the actual active boundary
→ read this blueprint completely
→ if architecture/direction must change, update ZN.md first
→ implement the smallest coherent ZN-owned step
→ test the real active path
→ update implementation/extraction status after verification
```

Rules:

1. Do not choose an architecture merely because an inherited module already exists.
2. Do not let a compatibility path silently become permanent product architecture.
3. Do not describe transitional code as complete ZN ownership.
4. If code proves a current-state statement in this blueprint wrong, synchronize that statement before continuing.
5. Tests specify behavior but do not replace the product architecture.
6. A green inherited test suite does not prove the ZN product boundary is correct.
7. `main` remains untouched until the explicit M10 migration/promotion milestone.
8. Mature mechanisms should be studied and extracted; old product control planes should not be embedded.
9. Ordinary development CI stays cheap. Multi-OS packaging/clean-machine release work runs only when the milestone needs it.

### 0.1 Maintainer-independent continuity

ZN development and release must not belong to one GPT, one model, one chat session or one development computer.

```text
replace GPT / Claude / Gemini / human maintainer
→ read repository contracts and handoff
→ inspect real Git/CI state
→ continue development
```

The durable engineering state belongs to the repository and project-owned infrastructure:

```text
source + architecture + implementation status + HANDOFF
+ tests + CI + release workflow + project-level secure credentials
```

A lost chat or lost development computer must not destroy the ability to maintain or release ZN. Secrets are not committed to source; they live in project-level secure stores such as GitHub Secrets or the relevant release platform. Maintainers trigger the repository-defined process rather than owning the secret values.

Formal release behavior must be reproducible from repository automation. A client update must come from verified release artifacts and the ZN update channel, not from an arbitrary maintainer's local checkout.

Detailed takeover rules are defined in `AGENTS.md`. Detailed self-maintenance rules are defined in `docs/ZN-SELF-MAINTENANCE.md`.

---

## 1. Product definition

ZN is a long-lived resident digital subject that lives on a computer.

The central inversion is:

**ZN uses models. Models do not own ZN.**

GPT, Claude, Gemini, DeepSeek, local models, search systems, browsers, code interpreters and future cognitive systems are replaceable resources. They are not the holder of ZN's identity, memory, Will or continuity.

For this project, “alive” means persistent computational continuity of self, state, perception, intention, thought, action, experience and adaptation even when no chat session or external model is active. It is not a claim of biological consciousness.

Product ownership:

- ZN is the subject.
- Models are bounded cognitive resources ZN may consult.
- Tools are ways ZN's body can affect the computer/world.
- Senses are ways ZN obtains current evidence from the computer/world.
- Memory is lived experience that changes the resident itself.
- Code is part of ZN's computational body.
- Communication channels are I/O organs for the same resident, not separate agent identities.
- Electron/Desktop is a face and work surface, not the owner of ZN's life.
- Installation, runtime selection, configuration, updates and user data are owned by ZN.

Disconnecting every external model must not erase ZN's identity, memory, resident state or ability to continue native pulses.

## 2. Architecture continuation notice

The remainder of this blueprint is intentionally preserved by Git history and the previous `dev/zn-agent` revision. This commit only establishes the maintainer-independent continuity contract and links the self-maintenance contract. Future architecture edits must retain the full existing blueprint rather than treating this short section as a replacement specification.
