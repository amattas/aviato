# Aviato

A copy-paste starter kit that keeps my repos consistent: CI, tag-push
releases, Docusaurus docs, rulesets, Dependabot. No engine, no CLI, no shared
runtime dependencies — each repo carries its own copies of a few small
workflow files, and this repo is the master they're copied from.

**Everything lives in [`starter/`](starter/README.md)** — what to copy for
each repo type, the one-time setup checklist, and the conventions.

The model in one paragraph: CI runs on PRs and main pushes (job `ci`, the
required check). **Releasing is `git tag 1.2.3 && git push origin 1.2.3`** —
the release workflow validates the tag, verifies it matches the repo's
version source, publishes (PyPI / GHCR / GitHub release), and creates the
GitHub release last. Docs deploy on every main push, decoupled from releases.
Updating a repo means copying the master file again and reviewing the diff in
a normal PR.

This repo previously housed a full policy/CI/release management engine
(operator CLI, drift detection, reconciliation, 700+ tests). It worked, but
it was enterprise-grade machinery for a solo developer's fleet — the kit
replaced it. The history is all here if archaeology ever calls.
