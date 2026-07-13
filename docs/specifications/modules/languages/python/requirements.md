<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

### 12.1 Python

**Scaffold bundle (managed files):** lint+format config, static type-check
config, test+coverage config, language ignore rules, editor config, and a
project-manifest fragment. (Shared common files — license, contributing, code
owners, issue/PR templates — come from the common scaffold; LICENSE and any
JSON/lockfile are seed-once per §6.3.)

**Required tooling/standards (named, all gates blocking):** **Ruff** for linting
**and** formatting — `ruff format` is black-compatible, so it provides black's
formatting in one fast tool (no separate black); **mypy `--strict`** type-checking
as a **blocking** gate; **pytest** with **coverage measured in CI** (threshold
opt-in, measure-only by default, no external coverage service); a standards-based
build backend producing source and wheel distributions; Conventional Commits
enforced.

**Version-source module:** declares the project-manifest version field (and any
in-code version constant) so the core release process (§5.9) bumps both in sync
without the core knowing the location.

**Workflows bundle (pipelines):**
- **Verify** (Linux): Ruff lint + `ruff format --check` + mypy `--strict` +
  pytest+coverage (lint/format/type blocking), plus the common lint (§12 intro).
- **Docs** (only when `docs: true`, §6.1): emit API reference from docstrings as
  **md/mdx** into the docs source tree for the Zensical site; the docs deploy
  (§13.3) builds and publishes it. No docs step runs when `docs: false`.
- **Release** (§5.9): SemVer from Conventional Commits; version via version-source.
- **Deploy**: **PyPI** for `python-library`, **GHCR** for `python-service`,
  **none** for `python-component` (GitHub release only — zero deployment plug-ins, §13).
- **Security (baseline, §2.13/§5.14):** CodeQL (Python) SAST; **bandit** security
  linting (Ruff's `S`/flake8-bandit rules cover much of it; bandit adds depth);
  dependency/supply-chain scanning (pip-audit / OSV + Dependabot); secret scanning
  + push protection (platform-native); SARIF to the Security tab; high/critical
  gates verify.

**Required variables:** for the **library** model (`python-library`/`python-component`),
the distribution name and import/package name (typed, non-secret). For the **container
service** model (`python-service`, below), only the GHCR image name.

**Container-service model (`python-service`).** A Python *service* whose build artifact
is its **Dockerfile image** (§13.2), not a wheel — so it follows the same packaging-free
shape as `node-service`, **not** the library model above:
- declares **no** distribution/import name (only the GHCR `image-name`);
- versions via a plain **`VERSION`** file (the release flow bumps the bare SemVer), not a
  `pyproject.toml` — there is no wheel/package metadata;
- CI installs from **`requirements.txt`** (the same file the Dockerfile uses) plus a seeded
  **`requirements-dev.txt`** for tools — it never installs the project as an editable package
  and **builds no wheel** (`run-build: false`); type-checking is **non-strict** `mypy` (lower
  adoption friction than the library default's `mypy --strict`);
- docs (when `docs: true`) are **narrative-only** (no docstring API reference — a service has
  no importable library API), mirroring `swift-app`.
The Dockerfile remains an operator-provided §17 prerequisite that Aviato probes
but never seeds; the GHCR deploy (§13.2) builds it. This keeps "service = container"
symmetric across Python and Node.

**Runner:** Linux. **Definition of done:** verify + release green in real CI (plus
the docs build when `docs: true`); the attached deploy plug-in meets its DoD.
