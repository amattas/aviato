<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

## 12. Language Plug-ins

Each language plug-in is **only** a collection of generic module kinds. One
baseline strictness level (no tiers). For each: what it must **provide**, what it
**requires**, its **runner**, and its **definition of done**.

**Verify posture — opinionated and strict (all profiles).** Aviato names **one
canonical toolchain per language** (below), not "bring your own," and **every
code-quality gate blocks** the verify pipeline: lint, format-check, and
type-check are hard failures, never advisories. Coverage is the single
measured-but-not-gated exception (threshold opt-in, §12.1).

**Common lint — language-agnostic, every profile, all blocking:**
- **actionlint** — `.github/workflows/*` (catches the reusable-workflow
  privilege/syntax errors of the §8.9 class).
- **yamllint** — YAML files.
- **hadolint** — every discovered Dockerfile, where any exist (GHCR publishers,
  §13.2).
- **shellcheck** — shell scripts, where any exist.
- **helm lint** — Helm charts, where a `Chart.yaml` exists. (This lints charts
  that are present; k8s/Helm *deployment* stays out of day-zero scope, §10.1.)

actionlint and yamllint apply to every repo; hadolint, shellcheck, and helm lint
are no-ops when their files are absent. These run as a common verify step shared
by all profiles (independent of language).

### 10.2 Language → target mapping

| Language | Produces | Deploys to |
|---|---|---|
| Python | importable library **xor** containerized service **xor** no-publish component (one per repo, §3 scope) | **PyPI** (library) / **GHCR** (service) / **none** (component — GitHub release only) |
| Node (TS/JS) | containerized service | **GHCR** |
| Swift | application | **Apple App Store Connect** |

Any profile may enable the **multi-version Zensical docs** deploy by setting
`docs: true` in the declaration (§6.1, §13.3). It is **opt-in** (default off); when
enabled, the language plug-in emits md/mdx (§12) and the tag-gated docs deploy
builds and publishes it. The docs deploy is language-agnostic — it consumes md/mdx
and never inspects source.
