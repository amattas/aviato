<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

## 18. Glossary

- **Library** — the central, publishable repository of conventions, modules, and
  tooling. Agnostic core + plug-in modules.
- **Consumer** — a repository that adopts a convention set via the declaration
  contract (§6).
- **Operator** — the single human who initiates privileged actions with their own
  credentials (day-zero single-operator scope, §3.4).
- **Module** — an independently-defined unit of one kind (§3.2) with a declared
  interface.
- **Profile** — a thin manifest composing one bundle of each kind; one per repo;
  contains no logic. A profile **name** is a stable public identity (§6.5).
- **Bundle** — a composition of modules of a single kind (workflows / scaffold /
  settings).
- **Version-source module** — a language plug-in's declaration of where it records
  its version, read/written by the core release process (§3.3).
- **Convention set** — the fully-resolved output of profile resolution (§5.1):
  pipelines, templates, settings, required variables, and version-source.
- **Declaration file** — the Consumer's `.github/aviato.yml` (§6.1); the only
  interface between Library and Consumer.
- **Managed marker** — the in-file annotation (normative format, §6.2) recording a
  generated file's profile, version, and content-hash.
- **Managed artifact** — a file produced by scaffolding that carries a managed
  marker.
- **Seed-once file** — a file scaffolded only when absent, never overwritten, and
  excluded from drift (§6.3): non-annotatable files and operator-owned source.
- **Overlay** — the §5.3 rule by which, when two templates target the same output
  path, the later/overriding source wins.
- **Drift** — divergence between a Consumer's actual state and its resolved desired
  state. For files, the status enum is **clean**, **mergeable-drift** (safe to
  regenerate), **dirty-drift** (needs human review), or **missing** (§5.4). For
  settings, a change is classified **additive** or **destructive** (§5.6).
- **Reconciliation** — the operator-gated, fail-closed application of desired
  settings to live settings (§5.7).
- **Consent record** — the diff-bound grant on a tracking issue authorizing a
  reconcile (§6.4); the single term for the grant (no "token"/"marker" synonyms).
- **Pin / floating major reference** — the version a Consumer follows: an exact
  version or a major reference that advances on each release (§5.9). **Compatible**
  is defined in §2.6.
- **Bootstrap state** — the Library applying its own conventions and running its
  own pipelines before a release exists, using self-contained local references;
  detected by structure (§5.10).
- **Deployment authorization** — the §2.12 model: release-cut is the human gate,
  plus a protected-environment reviewer gate for secret-bearing deploys.
- **Documentation site** — the Consumer's published docs: a **multi-version
  Zensical** site (version dropdown + `latest` alias, Zensical's built-in search,
  Mermaid rendering, and sitemap generation) built from authored
  md/mdx plus language-emitted API md/mdx (§12) and versioned onto the docs branch
  on release; served via Pages only when enabled (§13.3). **Opt-in** via `docs: true`
  (§6.1); off by default. The
  docs deploy consumes md/mdx only — language-agnostic, never inspecting source
  (§2.9).
- **Security baseline** — the always-on security scanning every profile includes
  (§2.13, §5.14): SAST, secret scanning + push protection, dependency/
  supply-chain scanning, and published-artifact security (image scan + SBOM +
  provenance). Not a tier, not opt-in.
- **Verify baseline** — the opinionated, all-blocking code-quality gates every
  profile runs (§12): one named toolchain per language (Ruff / ESLint+Prettier /
  SwiftLint+swift-format, with strict type-checking) plus the common
  actionlint/yamllint/hadolint/shellcheck/helm-lint. Coverage is measured but not
  gated.
- **SAST** — static application security testing (e.g. CodeQL) run per language;
  results uploaded as SARIF to the platform Security surface.
- **SBOM** — software bill of materials generated for a published artifact.
- **Provenance / attestation** — a signed, verifiable record of how an artifact
  was built (keyless OIDC), attached at publish.
- **Gate (security)** — high/critical findings fail the verify pipeline or block
  the deploy; medium/low report without blocking; secret push-protection always
  blocks (§2.13).
- **Plug-in (language / deployment)** — a collection of generic modules that adds
  language or deployment support without touching the core.
