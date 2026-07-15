<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

### 5.2 Repository onboarding (provision-new and adopt-existing)

**Trigger:** operator wants a repository to follow a convention set.
**Actor:** operator (local CLI), own credentials.
**Variable resolution (impure):** required variables resolve by precedence
**flags > declaration file > environment > auto-detection**, then the resolved
set is **written into the declaration** for reproducibility — **except variables
typed `secret` (§6.6), which are NEVER written to the declaration**; resolving a
secret-typed variable into the persisted set is a **hard error** (§8.15), so the
declaration carries no secrets (§6.6/§11.4). "Auto-detection"
derives from a **defined, enumerated** set of host sources (e.g. repository
name, the platform's repository metadata, the operator's configured identity);
nothing outside that enumerated set is auto-detected. **Day-zero scope:** the
resolution honors the auto-detection tier (it is the lowest-precedence source in
`resolve_variables`), but **day-zero profiles deliberately auto-map no
identity-bearing variable** (distribution / import / image / project / bundle
names). Because a resolved variable is **persisted into the declaration** (above),
auto-detecting one would silently write a *guess* — and these identifiers need
language-specific normalization (a directory name is not a PyPI distribution name),
so a wrong guess is worse than failing closed. Day-zero therefore resolves these
from flag / declaration / environment and **fails closed** (lists the missing
variable) when unset; populating the auto-detection tier with safe, normalized
sources is a post-day-zero refinement.
**Preconditions:** every *required* variable resolves; for adopt, the working
tree is clean unless overridden. A fresh provision/adopt **must** record an
explicit Library pin supplied by the operator; the process never fabricates a
default pin. That pin must resolve to a published Library tag/branch before
write/provision proceeds. `--allow-unresolved-pin` is retained only to reject
legacy invocations with a compatibility error; there is no offline/test escape
from verified Library bytes. Before declaration inspection or any write, the
target path is resolved and must equal its Git top level. The pin is resolved
once to an exact tag-or-branch outcome and commit SHA, and all planning,
rendering, policy, and ruleset reads share that one snapshot.
For workflow schema v2 the pinned resolved set and typed variables are compiled
once into `DesiredState`. The same graph owns generated callers, template
artifacts, settings, environments, required checks, and privileges. Exact
onboarding requires every typed variable. A fresh preview may instead compile a
`PartialDesiredState` that lists definite and conditional outputs and missing
inputs, but it never has a plan ID and cannot mutate. A missing schema is legacy
v1: read-only inspection remains available, while graph-changing onboarding
fails with repin guidance.
The graph composes shared `ci`, `drift`, and optional `docs` envelopes. Pipeline
modules contribute the complete job AST plus their trigger slices; the compiler
derives exact job-level permissions, required checks, protected environments,
and managed-artifact owners from that selected union. Documentation opt-in is
composed before the consumer add/remove delta, so an explicit removal is
authoritative. A release removal must also remove any dependent deployment
pipeline; missing graph dependencies fail closed.
**Two paths, one shape:**
- *Provision-new*: create the repository, apply **minimal** protection (§2.11),
  scaffold, first commit, then apply **full** protection.
- *Adopt-existing*: write/merge the declaration, scaffold onto a branch, open a
  proposal for review.

Both paths use the same pure, digest-bound local `TransitionPlan`. The plan
enumerates every managed write/retirement, seed addition, sidecar update,
declaration update, and final inventory receipt before any mutation. Conflicts
abort without creating transition state. `--allow-dirty` tolerates only
unrelated paths and never an overlap with a planned path. Local execution is
serialized per worktree and journaled in Git administrative storage; the
managed inventory is the final operation and success requires a final local
convergence diagnosis before journal removal.

Local `--write` and `--open-pr` are two delivery modes for identical transition
bytes. Proposal mode first clones the repository, plans and executes the
transition inside that clone, and gives the complete worktree diff (including
deletions, seed sidecar, declaration, and inventory) to the proposal publisher.
It never constructs a second ad-hoc file dictionary. A collision, dirty managed
artifact, foreign or malformed marker, invalid seed record, or pending recovery
journal prevents both local success and proposal creation. Existing seed-once
files remain operator-owned and are enumerated in proposal output. A proposal
with no resulting diff is a successful no-op and does not attempt an empty
commit. A pre-existing invalid or operator-owned inventory path is a collision,
never a fresh-state signal, and is not overwritten.

Profile migration validates the saved source declaration against the immutable
source commit recorded by its managed inventory, even when the declared branch
or tag now resolves elsewhere. The newly resolved snapshot supplies only the
target profile and target artifacts. Local and proposal migrations share these
same source-trust and clean-marker checks.

An interrupted transition blocks ordinary onboarding, sync, repin, and
offboarding mutation. `aviato recover-transition PATH` inspects it without
mutation. Resume or rollback requires exactly one requested action and the
exact displayed journal id through `--confirm JOURNAL_ID`; unknown third-party
edits leave the journal indeterminate rather than being overwritten.
**Guards:** never change an already-declared profile to a different one without
an explicit migrate override; enumerate files left untouched (seed-once,
unmanaged) in the proposal.
**Solo-maintainer review exception (normative):**
Full protection resolves its required-review count from the profile plus the
consumer declaration. The profile default remains one approval. A repository
may declare `overrides.settings.default_branch.required_reviews` as
`required_reviews: 0` only while it has no independent eligible reviewer and
the sole eligible reviewer cannot approve their own proposal. This is a
liveness exception, not bypass authority: the pull-request, required-check,
CodeQL, review-thread, stale-review, deletion, non-fast-forward,
active-enforcement, and no-bypass protections remain unchanged. Remove the
override before or in the same settings change that makes another reviewer
eligible, restoring the profile default of one approval without an unprotected
interval. All onboarding completion guidance uses
`--declaration .github/aviato.yaml`, never `--profile`, so the apply path
preserves these repository-specific settings. Fresh previews sequence writing
or merging the declaration before that command.
For `python-library`, the managed CI caller includes the consumer-local `pypi`
environment job required by PyPI Trusted Publishing. Register that exact caller
path and environment with PyPI/TestPyPI after onboarding. The reusable build
workflow requires `consumer-publisher-present: true`; older callers fail loudly
with an `aviato sync` instruction instead of completing without publishing.
The local publisher retains annotated-tag peeling, repeated fresh-tag checks,
HTTPS/index validation, attestations, alternate-index support, and published-file
hash confirmation; graph generation changes ownership, not release trust.
**Partially-provisioned state & recovery (normative):** between minimal and full
protection the repo is in a defined **partially-provisioned** state. Minimal
protection (no force-push, no deletion; no PR-required gate that would block the
first commit) is **safe to persist** indefinitely. If full protection fails after
the first commit, the process reports the partial state and exposes an
**idempotent `complete-protection` recovery operation** that re-applies full
protection and is safe to re-run any number of times.
When GitHub rejects the `tag_name_pattern` metadata restriction with an explicit
HTTP 422 unsupported-rule response, full-protection application retries exactly
once with only that rule omitted. The CLI reports the repository and omitted rule
as **DEGRADED**; deletion and non-fast-forward protections, conditions,
enforcement, and the no-bypass posture remain intact. No other API, authentication,
network, malformed-response, or validation failure is downgraded. A later failure
does not roll back earlier successful mutations, which are reported as they occur.
The correlated response may be a structured type-error object or a whole-entry
string inside `errors`. The observed literal was
`Invalid rule 'tag_name_pattern':`; the accepted whole-entry grammar is
`^\s*invalid\s+rule\s+["']tag_name_pattern["']\s*:\s*$`. Matching is
case-insensitive, accepts either single or double quotes, and permits
surrounding whitespace, including terminal whitespace after the colon. Matching
examines one error entry at a time and never combines entries.

```mermaid
flowchart TD
    Start["Operator: onboard repo with profile P"] --> Root["Canonicalize target<br/>require exact Git root"]
    Root --> Pin["Resolve explicit pin once<br/>tag/branch → commit snapshot"]
    Pin --> Vars["Resolve required variables<br/>(flags > declaration > env > enumerated auto-detect),<br/>then write NON-SECRET into declaration (secret-typed = hard error, §8.15)"]
    Vars --> V{"All required vars present?"}
    V -- no --> Vfail["FAIL CLOSED: list missing vars + how to set"]
    V -- yes --> Compile["Compile + validate one pinned DesiredState<br/>ci + drift + optional docs envelopes<br/>jobs · triggers · artifacts · settings · envs · checks"]
    Compile --> Mode{"New or existing?"}

    Mode -- new --> N1["Create repository"]
    N1 --> N2["Apply MINIMAL protection<br/>(safe to persist; does not block first commit)"]
    N2 --> N3["Clone and execute the same WAL transition<br/>declaration + seeds + sidecar + managed files + inventory"]
    N3 --> N4["First commit + push"]
    N4 --> N5["Apply FULL protection"]
    N5 --> N6{"Full protection applied?"}
    N6 -- no --> N7["REPORT partial-provisioned state +<br/>idempotent complete-protection recovery op"]
    N6 -- yes --> Done["Onboarded"]

    Mode -- existing --> E0{"Already declares a different profile?"}
    E0 -- "yes & no override" --> Emig["REFUSE: require explicit --migrate-profile"]
    E0 -- "no / override" --> E1{"Working tree clean (or override)?"}
    E1 -- no --> Edirty["REFUSE: clean tree or pass --allow-dirty"]
    E1 -- yes --> E2["Build one pure transition plan<br/>(all bytes, modes, preimages, inventory)"]
    E2 --> E3["Execute WAL transition onto a branch<br/>inventory last; final local diagnosis"]
    E3 --> E4["Publish the complete worktree diff;<br/>enumerate preserved seed-once files"]
    E4 --> Done
```
