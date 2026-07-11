<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

## 1. Purpose

Aviato is a reusable **GitOps conventions system**. It lets one operator define
release, branching, protection, scaffolding, documentation, and drift-handling
conventions **once**, in a central library, and apply them consistently across
many repositories — without copy-paste, without per-repository drift, and
without the central library needing any knowledge of the repositories that
consume it.

The system has three actors and one rule that governs all of them:

- **Library** — the central, publishable source of conventions and tooling.
- **Consumer** — a repository that adopts a convention set.
- **Operator** — the human who runs privileged actions from their workstation.
  Day zero assumes exactly **one** operator; multi-operator/team coordination is
  an explicit non-goal (§3.4).

The governing rule: **the Library never knows about Consumers, and privileged
mutation never happens automatically — with the single, explicitly-defined
exception of deployment (§2.12).**

---
