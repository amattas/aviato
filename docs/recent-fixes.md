# Recent Fixes

This log records review-remediation changes that future Aviato scans should treat
as intentional hardening work, not unexplained churn. It is not a release
changelog; it exists to keep repeated requirements reviews from flapping on the
same fixed surfaces.

## 2026-06-09 hardening pass

- Added npm install hardening for Node and Docusaurus projects:
  `min-release-age=7` and `ignore-scripts=true` are scaffolded into managed
  `.npmrc` files with `engine-strict=true`, package manifests declare
  `node >=24` / `npm >=11`, and CI sets the same options before npm installs.
  CI defaults Node/npm projects to Node 24 and blocks npm <11 before any npm
  install path, because older npm rejects `min-release-age`.
- Added Docusaurus docs hardening/features: first-party Docusaurus ESLint
  plugin linting, Algolia search theme, Mermaid rendering, and explicit sitemap
  configuration through the classic preset.
- Limited `local-install: true` in reusable workflows to structural Library
  bootstrap checkouts before running `pip install -e .`.
- Scoped App Store Connect and Apple signing secrets to the specific steps that
  need them, and moved the caller-controlled version command before signing
  assets are installed.
- Replaced the Library's self-consumption declaration with the internal
  `aviato-library` profile so bootstrap validation matches only the artifacts
  this repo actually self-applies.
- Strengthened Library bootstrap validation to compare every managed artifact
  resolved by the declaration instead of a hard-coded workflow pair.
- Added a published-ref check for fresh onboarding/provisioning pins, with
  `--allow-unresolved-pin` reserved for intentional offline or test scaffolds.
- Changed committed example templates from `@main` to `@EXAMPLE_PIN`, and added
  validation coverage so `@main` does not return.
- Fixed forced scaffolding so a profile migration restamps managed markers even
  when the managed body is otherwise unchanged.

## 2026-06-09 prior remediation already in this checkout

- Fresh onboarding/provisioning no longer silently defaults to `@0`; fresh writes
  require an explicit pin.
- Library bootstrap rendering supports local reusable workflow refs and
  `local-install: true` for the Library's own callers.
- Swift app scaffolding now carries the expected Xcode/App Store inputs and
  requires either `workspace` or `project`.
- Common lint now checks every discovered Dockerfile, not only the first one.
