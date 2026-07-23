<!-- Split from ARCHITECTURE.md (2026-07-11). -->

# Aviato Architecture

This document describes the current lightweight architecture of this repository
and the near-term direction agreed for making it more consistent and modular.
`docs/requirements/` (§ index in `docs/requirements/README.md`) remains the
broader requirements document; this file is the implementation-facing map of
what Aviato is today.

Precise behavioral contracts live in `docs/specifications/`. Security is a
cross-cutting view: `docs/security/threat-model.md` owns risks,
`docs/security/controls.md` owns mitigations, and `security.md` shows where
those controls sit in this architecture. Current evidence is recorded in
`docs/requirements/traceability.md`.

## Purpose

Aviato is a reusable GitHub policy, CI, release, and onboarding conventions
library. It provides shared building blocks that can be consumed by many
repositories without requiring this library to keep a persistent registry of
those consumers.

The current implementation is intentionally small:

- reusable GitHub Actions workflows;
- reusable caller workflow templates and composition-backed scaffold bodies;
- GitHub repository ruleset payloads;
- operator-run scripts for auditing and applying rulesets;
- generated or local reporting artifacts.

The current implementation includes the day-zero workflow surface from
`docs/requirements/` (§ index in `docs/requirements/README.md`) **and** the
agnostic core engine (`aviato/core/`): profile
resolution/composition, the consumer declaration contract, managed-marker
scaffolding with seed-once, diagnosis, file/settings drift, the fail-closed
authorization gate, version-pin compatibility, bootstrap detection, Conventional
Commit version derivation, onboarding/sync, re-pin, and offboarding. The
*platform-side* orchestration of the §5.5–§5.7/§5.9 flows is implemented as
well: opening proposals, filing tracking issues, applying settings, and cutting
releases live in `aviato/core/` (`file_drift_flow`, `settings_drift_flow`,
`reconcile_flow`, `fleet`) behind the `aviato/github_platform.py` binding, and
are surfaced through the `reconcile`/`scan` CLI commands and the
`reusable-release.yml` workflow. Scheduled file/settings drift detection is now
owned by the sibling [aviato-bot](https://github.com/mattas-net/aviato-bot) service
(the retired `drift-report` command and `reusable-consumer-automation.yml`
workflow are gone); `doctor`/`scan` probe that service for per-repo coverage. What
remains is live end-to-end operator verification of those flows against a real
GitHub repository — the engine primitives and the binding's response-mapping
are unit-tested.

## Boundaries

The library owns reusable policy and automation. It should not own consumer
inventory.

Consumer repositories adopt Aviato by referencing reusable workflows, copying or
generating caller workflow files, and having rulesets applied by an
operator-initiated command.

The operator runs privileged commands from a local workstation. Audits may
discover repositories from a local root or target one explicit repository.
Onboarding should target explicit repositories. Persistent fleet inventory is
not part of the library contract.

## Non-Goals For The Current Implementation

- Persistent committed inventory of consumer repositories.
- Automatic unattended mutation of protected consumer repository settings.
- Multiple hosting-platform bindings.
- Release publishing from legacy release branches.
