# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through **GitHub private vulnerability
reporting** for this repository (Security → Report a vulnerability). If that
channel is unavailable, email `anthony@mattas.net`. Do not open a public issue.
An acknowledgment should arrive within one week; coordinated disclosure is
appreciated.

## Scope

Reports may cover the `aviato` operator CLI, reusable workflows under
`.github/workflows/`, scaffold templates seeded into consumer repositories, and
policy/ruleset payloads applied by Aviato. A reusable-workflow vulnerability may
affect every consumer pinned to the affected version, so include suspected blast
radius when known.

## Supported versions

The latest release of each major line is supported. Consumers pin an exact
version or floating major (§2.6). Security fixes ship as new releases; a
floating major advances monotonically after the release gates pass.

## Current posture

The living security records are:

- [Threat model](docs/security/threat-model.md) — assets, actors, trust
  boundaries, threats, mitigations, assumptions, and accepted residual risks.
- [Control inventory](docs/security/controls.md) — stable `SEC-*` controls and
  their implementation/verification surfaces.
- [Security architecture](docs/architecture/security.md) — placement of
  controls across untrusted, verification, and privileged boundaries.
- [Traceability matrix](docs/requirements/traceability.md) — current state and
  evidence, including external gates that remain outstanding.
- [Supply-chain specification](docs/specifications/modules/security/supply-chain.md)
  and [security-baseline specification](docs/specifications/modules/security/scanning.md)
  — normative executable-input and scanning behavior.

These living documents, not dated plans or completed checklists, are the
authoritative internal posture record.
