<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

### 12.2 Node (TypeScript + JavaScript)

A **single** plug-in covers both. Type-checking is **required for TypeScript** and
**omitted for JavaScript**, selected by the `language-variant` enum variable
(§6.6), not by forking the plug-in.

**Scaffold bundle (managed files):** npm install-hardening config (`.npmrc`),
lint config, format config, TypeScript
compiler config (TS), language ignore rules, editor config, package-manifest
fragment (scripts + engines requiring Node >=24 and npm >=11). Lockfiles and
JSON-only files are seed-once (§6.3).

**Required tooling/standards (named, all gates blocking):** **ESLint** (flat
config) for linting; **Prettier** for formatting; **`tsc --noEmit`** type-checking
(**TS only**, blocking); a standard test runner with coverage in CI; a production
build/bundle suitable for a containerized service; Conventional Commits enforced.

**Version-source module:** the package-manifest version field.

**Workflows bundle (pipelines):**
- **Verify** (Linux): ESLint + Prettier `--check` + `tsc --noEmit` (TS) +
  tests+coverage (lint/format/type blocking), plus the common lint (§12 intro).
  The reusable workflow defaults to Node 24 and refuses npm <11 before install so
  `min-release-age=7` can be enforced; ESLint/Prettier/TypeScript are invoked
  through local package binaries (`npx --no-install`).
- **Docs** (only when `docs: true`, §6.1): emit API reference as **md/mdx** via
  TypeDoc (markdown output) into the docs source tree for the Docusaurus site
  (§13.3). No docs step runs when `docs: false`.
- **Release** (§5.9): SemVer; version via version-source.
- **Deploy**: **GHCR** (§13.2). **No npm/library publishing.**
- **Security (baseline, §2.13/§5.14):** CodeQL (JavaScript/TypeScript) SAST;
  **eslint-plugin-security** lint rules; dependency/supply-chain scanning (npm
  audit / OSV + Dependabot); secret scanning + push protection; SARIF to the
  Security tab; high/critical gates verify.

**Required variables:** project name, `language-variant` enum
(`typescript | javascript`), shared metadata variables.

**Runner:** Linux. **Definition of done:** verify + release green in real CI (plus
the docs build when `docs: true`); GHCR deploy meets its DoD.
