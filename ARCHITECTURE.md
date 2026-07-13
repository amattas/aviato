# Aviato Architecture

Split on 2026-07-11 into [docs/architecture/](docs/architecture/):

- `overview.md` — purpose, boundaries, non-goals
- `infrastructure.md` — components (workflows, templates, rulesets, core engine, scripts)
- `data-flow.md` — policy source → rendering → apply; release + branch-protection architecture
- `security.md` — trust boundaries and placement of security controls
- `validation.md` — the validation gate

Normative outcomes live in `docs/requirements/`; precise behavioral contracts
live in `docs/specifications/`; threats and controls live in `docs/security/`.
