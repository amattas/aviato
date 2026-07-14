<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

## 6. The Consumer Contract

The **only** interface between Library and Consumer is a small, declarative
surface, specified normatively below.

### 6.1 Declaration file

- **Name & location:** a single file at `.github/aviato.yaml` in the Consumer (the
  path is the GitHub binding's realization, §2.14; another platform binding could
  place it elsewhere).
- **Format:** YAML.
- **Versioned schema** with these fields:
  - `profile` (string) — the profile name (a stable public identity, §6.5).
  - `profile-identity` (string) — the profile manifest's immutable identity, written by
    onboarding (for example `aviato-profile/python-library/v1`). Legacy declarations
    without this field must sync against their own declared pin before they can re-pin.
  - `version` (string) — the Library version pin: an exact version (`X.Y.Z`) or
    a floating major reference (`X`). Bare SemVer is canonical (matching `policy.yml`
    and the CLI); a legacy leading `v` is tolerated on read but never emitted.
    The pin must resolve to an exact tag or branch and then to one commit SHA;
    unresolved pins have no installed-data fallback.
  - `docs` (boolean, optional, default `false`) — opt-in to building and
    publishing the multi-version documentation site (§13.3). When `true`, the
    language plug-in's docs step emits API/reference material as md/mdx (§12) and
    the docs deploy consumes it; when `false` (default), no docs site is built or
    published and no docs step runs.
  - `bootstrap` (boolean, optional, default `false`) — valid only for the Library
    repository itself (§5.10). It enables local self-reference during bootstrap
    and is rejected for non-Library repositories.
  - `variables` (map) — resolved variable values (§6.6), written by onboarding.
  - `overrides` (map, optional) — convention overrides under the §4.2 semantics.
- It is **declarative** (the Consumer states intent; the engine realizes it),
  **self-contained** (everything the Consumer needs is in its own repo plus the
  version-pinned Library reference), and carries **no secrets** for
  read/propose/report automation (§6.6).

Before reading this declaration, an operation resolves the supplied target and
requires it to equal Git's canonical repository root. Nested paths,
non-repositories, and nonexistent targets are rejected before render or write.
After reading the declaration, the operation resolves and fetches its pin once
and owns one immutable snapshot for its full lifetime. Profile manifests,
templates, rulesets, and policy must all come from that snapshot. Its recorded
requested pin, tag-or-branch outcome, commit SHA, and canonical repository
identity are the authoritative provenance for the operation.

### 6.2 Managed-marker format (normative)

- A managed file's **first non-blank line** is a marker using the file's native
  comment syntax, of the canonical form:
  `aviato:managed profile=<name> version=<pin> hash=<content-hash> inputs=<input-hash>`
  (e.g. `# aviato:managed profile=python-library version=1 hash=… inputs=…` for
  hash-comment files; the equivalent block/line comment for other syntaxes).
- The marker records **profile**, **version**, a **content-hash** of the rendered
  body (excluding the marker line), and an **input-hash** of canonical resolved
  non-secret variables. Drift therefore detects a changed render input even when
  the old body happens to remain byte-identical (§5.5). Legacy markers without
  `inputs` are readable for migration but are rewritten to the canonical form.
- A line that contains the `aviato:managed` token but does not parse to this exact
  grammar is **malformed** → treated per §5.4 (dirty-drift; never silently
  overwritten).
- A per-filetype comment-syntax mapping defines how the marker is rendered/parsed
  for each supported file type.

### 6.3 Non-annotatable & operator-owned files (seed-once)

Files that cannot carry an in-file marker (JSON-family configs, legal text such
as LICENSE, lockfiles, binaries) and explicitly configured operator-owned source
templates are **seed-once**: the scaffolder writes them only when **absent** and
**never overwrites them**. Container build definitions are a separate
operator-provided prerequisite: Aviato probes them but never seeds them. After
seeding, the operator owns the seed-once files, and they are **excluded from drift
*remediation*** (Aviato
never regenerates or clobbers them). However, at seed time the scaffolder
**records a content-hash for each seeded file in a report-only sidecar**;
diagnosis (§5.4) compares the live file to that recorded hash and **reports**
divergence — **report-only, never an overwrite** — so security-relevant seed-once
files are not invisible to integrity checks. The
sidecar is report-only, but its state is fail-closed: missing, malformed, duplicate-key,
or invalid-hash content is **unknown integrity**, never silently interpreted as a
clean baseline. After inspection, only the explicit operator command `aviato sync
<path> --rebaseline-seeds` may replace the sidecar with hashes of the current
resolved seed set. This gives tamper *visibility* without fighting the required
operator edits that make these files operator-owned. (This replaces the earlier
"no sidecar at all" stance, which left these files with zero integrity tracking.)

### 6.3a Managed inventory (normative)

`.github/aviato.managed.yml` is a generated, schema-versioned index of the last
successfully accepted desired state. It carries a normal managed marker and its
body is validated independently. The body records profile name and immutable
identity, declared pin, resolved Library commit, stable artifact identities by
output path, pipeline owners, expected marker/body/input hashes, reviewed legacy
aliases, and owned remote-ruleset fingerprints. It never lists itself.

The inventory is discovery metadata, not deletion authority. Every diagnosis or
transition reconciles it with a confined Git scan of tracked plus untracked
nonignored files, excluding Git metadata, nested repositories/worktrees, and
build roots. A valid live marker remains the authority that a file is managed.
A missing, malformed, truncated, hand-edited, or path-injecting inventory cannot
hide a marked file. An obsolete artifact is retirable only when its stable
identity is known, its marker belongs to the current profile (or an explicitly
authorized migration source profile), its version is recognized, and the live
body and marker match the prior receipt. Seed-once files are never inventory-
retired. Path identities are Unicode-normalized and compared case-insensitively
for portability; case-equivalent entries, aliases, protected roots, or multiple
Git-index spellings block rather than collapse silently. A single reviewed
legacy alias may be adopted; alias ambiguity blocks.

### 6.4 Consent record (normative)

- Consent to a settings reconcile is expressed by an explicit, defined record on
  the tracking issue (a designated label/marker added by a human), and is
  **bound to the diff it authorizes** (it carries the diff's content identity).
  The authoritative content identity is the **diff the operator's apply-time client
  recomputes from live state** (§5.7), **not** the human-readable diff the reporting
  automation rendered into the issue body — so an automation actor with issue-write
  access cannot bind a human's consent to content it authored. The operator
  confirms the locally-recomputed diff at apply time (§5.7).
- **Grant** and **revoke** are recorded as the platform's authoritative
  issue-event entries; "current consent" is the most recent grant for the current
  diff identity not later revoked.
- A consent record whose bound diff identity does not match the current diff is
  **stale** → DENY (§5.8).
- Because the record is carried as a hosting-platform label a **human must be able
  to create**, the diff identity is constrained to fit the platform's label-name
  limit (GitHub: 50 chars, including the binding's `aviato-consent:` prefix). The
  identity is a truncated content hash (`settingsdrift.CONSENT_ID_HEX_LEN` hex
  chars) — short enough to label, long enough to keep the content binding
  collision-resistant. The binding guards this invariant at import.

### 6.5 Profile name stability

A profile manifest carries an explicit immutable `identity` of the form
`aviato-profile/<profile-name>/v1`; onboarding persists it as `profile-identity`.
The identifier, not a digest of the profile's evolvable composition, establishes
continuity. Templates, variables, settings, privileges, and version sources may
legitimately evolve while identity remains stable. Changing the identity repurposes
the name and is a breaking change handled like "profile no longer exists" (§5.12
refuses); an alias/deprecation path is required if continuity is desired.

### 6.6 Variable schema

- Variables are **typed** (string, boolean, enum with a declared domain — e.g.
  the Node `language-variant` enum `typescript | javascript`).
- Each variable is marked **secret** or **non-secret**. Read/propose/report
  automation receives **no secret** variables. Secrets required by a deployment
  plug-in are supplied only at deploy time, in the protected environment (§11.4),
  **never via the declaration** — this invariant is *enforced*, not merely stated:
  onboarding (§5.2) excludes `secret`-typed variables from the declaration
  write-back as a **hard error** (§8.15), and diagnosis (§5.4) flags any
  `secret`-typed key found in a declaration.

---
