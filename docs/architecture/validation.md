<!-- Split from ARCHITECTURE.md (2026-07-11). -->

## Validation

This repository should validate itself because it is policy infrastructure.

The validation entrypoint is:

```bash
./scripts/validate.sh
```

Validation should cover:

- shell syntax and linting while shell scripts remain;
- Ruff lint/format plus Black compatibility for the Library source tree;
- strict mypy type-checking of the Library package **and the complete test
  suite** (the Library's own declaration sets `run-typecheck: true`);
- GitHub Actions workflow linting;
- YAML syntax for `aviato/library/policy.yml` and `aviato/library/rulesets.yml`;
- JSON syntax for `aviato/library/rulesets/*.json`;
- drift checks that compare embedded release tag patterns against `policy.yml`,
  and that the inline `highest.py` monotonic-alias guards embedded in the deploy
  workflows still agree with the core `is_highest` comparator (§8.14/§13.2);
- finite subprocess checks: embedded comparator execution has a timeout and a
  timeout becomes one actionable validation error rather than a hung gate;
- deterministic `scripts/regen-templates.py --check` and
  `scripts/sync-docs-toolchain-pins.py --check` guards, including required-source
  presence, rendered docs-caller name parity, and all generated pin copies;
- exact-pin inspection of the root development extras as well as scaffolded
  requirements, while the build-system floor remains intentionally outside the
  runtime-tool exact-pin policy;
- project metadata, installed runtime metadata, and built-wheel version parity;
- distribution-based tool detection (`importlib.metadata`) so a source-tree
  `build/` directory cannot shadow a missing packaging tool;
- bootstrap checks that the Library declaration resolves every expected managed
  artifact through local self-reference and that none use released refs;
- workflow guard tests for npm install hardening, docs linting, App Store secret
  scoping, and `local-install` bootstrap confinement;
- the Python test suite (`pytest`).

CI should install required validation tools and run the validation script on
pull requests and default-branch pushes.
