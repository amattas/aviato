#!/usr/bin/env bash
# Apply (or update) the starter rulesets on a repo. Idempotent — re-run any time.
#   ./apply-rulesets.sh OWNER/REPO
# Branch ruleset: PRs required (0 approvals — solo), `ci` check required, no
# force-push/deletion, admin bypass via the PR merge box for emergencies.
# Tag ruleset: tags are immutable (no deletion, no moving).
# Note: tag NAME-pattern rules are GitHub-Enterprise-only; tag format is enforced
# by the release workflow instead.
# Merge methods: normalize all three PR merge methods (merge/squash/rebase) to allowed
# for a consistent merge UI across the fleet.
set -euo pipefail

repo="${1:?usage: $0 OWNER/REPO}"
dir="$(cd "$(dirname "$0")" && pwd)"

for payload in "${dir}"/ruleset-*.json; do
  name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "${payload}")"
  existing="$(gh api "repos/${repo}/rulesets" --jq ".[] | select(.name == \"${name}\") | .id" | head -n1)"
  if [ -n "${existing}" ]; then
    gh api "repos/${repo}/rulesets/${existing}" --method PUT --input "${payload}" > /dev/null
    echo "updated ${name} (id ${existing}) on ${repo}"
  else
    gh api "repos/${repo}/rulesets" --method POST --input "${payload}" > /dev/null
    echo "created ${name} on ${repo}"
  fi
done

gh api --method PATCH "repos/${repo}" -F allow_merge_commit=true -F allow_squash_merge=true -F allow_rebase_merge=true > /dev/null
echo "normalized PR merge methods (merge/squash/rebase allowed) on ${repo}"
