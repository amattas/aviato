# Security architecture

The [`threat model`](../security/threat-model.md) defines risks, the
[`controls inventory`](../security/controls.md) defines mitigations, and the
[`traceability matrix`](../requirements/traceability.md) records evidence.

```mermaid
flowchart LR
    Contributor["Contributor or fork"] --> Verify["Read-only verify and security jobs"]
    Verify --> Evidence["SHA-bound checks, SARIF, artifacts"]
    Operator["Trusted operator"] --> Gate["Consent / release / environment gate"]
    Evidence --> Gate
    Gate --> Privileged["Narrow privileged job"]
    Privileged --> GitHub["Repository settings / tags / Pages"]
    Privileged --> Registry["PyPI / GHCR / App Store Connect"]
    Policy["Pinned policy and templates"] --> Verify
    Policy --> Privileged
```

## Control placement

| Boundary | Threats | Controls |
|---|---|---|
| Consumer/fork code → workflow | THREAT-001, THREAT-002 | SEC-001, SEC-002, SEC-003 |
| Dependency/template → execution | THREAT-003, THREAT-008 | SEC-004, SEC-009 |
| Verify → publish | THREAT-004, THREAT-005, THREAT-010 | SEC-002, SEC-003, SEC-005 |
| Operator → protected mutation | THREAT-006 | SEC-006, SEC-007 |
| Credentials → job/filesystem | THREAT-007 | SEC-001, SEC-008 |
| Source/release → security gate | THREAT-009 | SEC-007, SEC-010 |

Privileged jobs do not trust read-shaped API responses as write payloads and do
not rebuild verified artifacts. External platforms remain outside Aviato's
control; their required reviewers, ruleset state, registry identity, and Pages
configuration therefore require explicit live evidence in traceability.

## Managed release authorization

Release proposal and promotion are separate trust phases. Default-branch
pushes may open or update a release proposal but cannot create tags, floating
tags, releases, OIDC tokens, or deployments. Closed promotion mode binds the
merged SHA, tag, actual actor, and one fresh signed checkpoint digest. The
checkpoint uses a concrete current user reviewer distinct from collector,
submitter, and release actor; team-membership assertions alone are rejected.
Each privileged job revalidates that checkpoint before environment secrets,
OIDC, or hosted mutation.

Composite confirmations bind the full before-state and exact ruleset payload
fingerprints. There is no degraded tag-rule flag or implied-safe fallback: a
platform rejection remains non-ready and requires a newly previewed supported
policy. Lost responses are resolved only by semantic readback; unreadable
state is indeterminate and is never blindly retried.
