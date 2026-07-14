<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

## 7. State & Sources of Truth

| Concern | Single source of truth |
|---|---|
| Desired conventions | The Library's profiles/bundles/modules at the pinned version |
| A Consumer's chosen conventions | The Consumer's `.github/aviato.yaml` declaration (§6.1) |
| Whether a file is managed | The managed marker in the file (§6.2); seed-once files (§6.3) are operator-owned |
| Prior managed paths and remote ownership receipts | The marker-bearing, schema-versioned `.github/aviato.managed.yml` index, reconciled with the complete live marker universe; the index alone never proves ownership or authorizes deletion |
| Live protected settings | The hosting platform (read at diagnosis/apply time) |
| Consent to mutate settings | The tracking issue's authoritative event history (§6.4) |
| Per-Consumer audit of actions taken | That Consumer's tracking issues (left open, §5.6/§5.7) |
| The Library's version | The Library's own version record + release tags |
| Which repos an operator manages | The operator's **local, ephemeral** scan input (§5.11) — never the Library |
| In-progress local file mutation | A checksummed, per-worktree write-ahead journal under Git administrative storage; never a tracked Consumer path |

There is no central registry of Consumers anywhere in the Library (§2.2).

---

## 8. Failure Modes the Structure Must Prevent

Each maps to a principle and must be designed out, not patched later.

- **§8.1** A child/override silently loses an inherited entry → prevented by
  explicit `add`/`remove` list semantics with edge-case hard-errors and deep map
  merge (§4.2).
- **§8.2** Automation silently reverts a human's emergency change → prevented by
  report-before-mutate and operator-gated apply (§2.4, §5.6, §5.7).
- **§8.3** Stale consent authorizes a changed mutation → prevented by binding
  consent to the current diff (§6.4) and apply-time recompute over settings **and**
  the consent channel (§2.8, §5.7).
- **§8.4** A lookup failure or unknown actor is treated as approval → prevented by
  fail-closed authorization (§2.7, §5.8).
- **§8.5** A hand-edited or seed-once file is clobbered → prevented by the
  managed-marker guard and the seed-once rule (§2.5, §6.2, §6.3).
- **§8.6** Read-shaped data replayed into a write is rejected by the platform →
  prevented by purpose-built write payloads (§2.9).
- **§8.7** A new resource sits unprotected, or its first operation deadlocks on its
  own protection → prevented by staged provisioning with a specified
  partially-provisioned state and idempotent recovery (§2.11, §5.2).
- **§8.8** The Library cannot build itself because its automation (including the
  release pipeline) references a release that does not yet exist → prevented by
  self-reference resolution covering all self-applied pipelines (§2.10, §5.10).
- **§8.9** Automation is granted privileges it cannot obtain (a caller that does
  not grant a callee's needed privileges) → prevented by requiring each pipeline
  to **declare** its privileges (read/report and deploy alike, §11.3) and each
  caller to **grant** them, validated as part of the module interface.
- **§8.10** Validation that only checks shape, not behavior → the Definition of
  Done (§9) requires a real end-to-end run, not static/string checks.
- **§8.11** Concurrent actors race on the same output → prevented by deterministic
  proposal identity and apply-time re-validation of the consent/issue channel
  (§5.5, §5.7).
- **§8.12** Benign release/tag movement causes churn, or a real marker corruption
  is missed → prevented by hashing the body excluding the marker version, with the
  version reconciled only via upgrade (§5.5, §5.12).
- **§8.13** A vulnerability ships because scanning was skipped, disabled, or
  silently broken → prevented by always-on baseline security scanning with a
  high/critical gate, and by §5.4 surfacing a scan that cannot run rather than
  reading "clean" (§2.13, §5.14).
- **§8.14** A slower, older release's deploy finishes last and moves a mutable
  published alias (e.g. a `latest` image tag or docs alias) **backward** →
  prevented by a **per-alias deploy concurrency group** plus a **monotonic-version
  guard** that moves the alias only if the deploying tag is the highest released
  version (§13.2, §13.3); the §2.12 recompute exemption does not cover this. The
  guard is inlined into the deploy workflows (to avoid a self-reference install) but
  is **validation-checked against the core `is_highest` comparator** so the hand-copied
  copy cannot silently drift from the tested implementation.
- **§8.15** A `secret`-typed variable is persisted into the declaration → prevented
  by onboarding excluding secret-typed variables from the write-back as a hard
  error, and diagnosis flagging any present (§5.2, §5.4, §6.6).
- **§8.16** The always-on security baseline fails **open** (a caller did not grant
  the findings-upload scope, or a scan never ran, leaving the repo reading
  "clean") → prevented by a runtime privilege probe that hard-fails and a per-run
  heartbeat whose absence reads as broken, not clean (§5.14, §5.4, §8.9).
- **§8.17** A stale generated workflow survives because the current profile no
  longer names it, or a corrupt inventory hides it → prevented by scanning every
  tracked and untracked nonignored Git file for managed markers and reconciling
  that universe with desired and prior state. The inventory is only an index;
  retirement additionally requires a valid current/source-profile marker, a
  known version, a stable artifact identity, and a live body matching the
  marker and recorded receipt. Modified, foreign, malformed, unreadable,
  symlinked, ambiguous, and seed-once paths fail closed and remain untouched.
- **§8.18** A crash, concurrent command, or parent-directory swap leaves a
  falsely successful or externally redirected multi-file update → prevented by
  one digest-bound transition plan, a per-worktree no-follow lock, durable
  preimages and `PREPARED`/`APPLIED` WAL records, dirfd-relative atomic mutation,
  verified rollback, and explicit journal-confirmed recovery. `--allow-dirty`
  never admits a dirty path that overlaps the plan.

---
