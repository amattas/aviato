# Starter kit backlog

## Open

- (none)

## Settled — do not reopen

- Multi-arch container builds REQUIRED — amd64+arm64 native-runner matrix (G2).
- No infra/terraform profile (G3, operator decision).
- Zensical with built-in search is the sole docs baseline (operator decision 2026-07-11); prior Docusaurus and external-search decisions are historical and superseded.
- The fleet Python floor is 3.12 (operator decision 2026-07-18, made during the pydmp adoption): every fleet project targets >=3.12, and the managed lint/typecheck configs (ruff target-version py312, mypy python_version 3.12) assume it. Floor-awareness machinery (deriving config targets from a consumer's requires-python) is deliberately NOT built — revisit only if a sub-floor consumer ever needs adopting.
