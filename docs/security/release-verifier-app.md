# Release verifier GitHub App prerequisite

Managed release, PyPI, GHCR, App Store Connect, and Pages workflows require a
dedicated GitHub App installation for authority readback. This is an operational
prerequisite for onboarding a repository that will use a privileged publisher;
Aviato does not create the App, install it, or persist its private key.

## Required App configuration

Create or reuse a private GitHub App with access limited to the repositories
managed by Aviato. Grant only these repository permissions:

- Administration: read
- Actions: read
- Contents: read
- Metadata: read

Do not grant repository write permissions. Install the App on each Consumer
repository before its first managed promotion, then configure these Actions
secrets in that repository or its owning organization:

- `AVIATO_VERIFIER_APP_ID`: the App ID
- `AVIATO_VERIFIER_APP_PRIVATE_KEY`: one active App private key in PEM form

The reusable workflows default the installation owner to the Consumer
repository owner. Set their `verifier-app-owner` input only when the App
installation is owned elsewhere and can still mint a repository-limited token
for the Consumer.

## Runtime boundary

Each privileged workflow mints a short-lived token with the permissions above,
scoped to the current repository. The token remains a step output: it is not a
job output, artifact, managed file, or input to Consumer-controlled commands.
Before any authority-dependent mutation, the workflow fails closed unless that
token can read the repository default branch, effective branch protection,
repository-owned rulesets, and protected environments.

The signed checkpoint selects the verifier source by repository, ref, path, and
Git blob SHA. The workflow fetches that exact Contents API object with the App
token, validates strict base64 and size bounds, recomputes the Git blob hash,
and executes the verified bytes in an isolated in-memory Python namespace. A
predictable executable verifier file is never created on the runner.

App Store Connect keeps the stronger runner boundary: the unsigned Consumer
archive is produced and attested without an environment or secrets. A fresh
trusted runner validates its digest, provenance, and archive members, executes
the verifier, and only then imports Apple signing material. Any custom submit
command runs later in a separate no-secret job.

## Rotation and failure behavior

Rotate the App private key by adding the new key, replacing
`AVIATO_VERIFIER_APP_PRIVATE_KEY`, proving one managed workflow can complete its
capability probe, and then revoking the old key. A missing secret, missing App
installation, insufficient permission, inaccessible protection surface,
ambiguous signing key, or verifier blob mismatch blocks publication without a
fallback to the ambient `GITHUB_TOKEN`.
