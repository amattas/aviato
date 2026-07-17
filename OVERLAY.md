# Starter-kit overlay — all repos, local + remote (2026-06-11)

Operator working artifact, committed 2026-07-16 to track the fleet migration
(corrections from the dependency-matrix audit folded in). Survey: 30 local dirs +
33 remote repos under `amattas`. Forks, archived repos, coursework, and CTF/CVP
artifacts excluded from migration scope.

## The headline

Ten active repos share ONE legacy release model the kit directly replaces:
`release/<version>` branch pushes trigger publishes (`create-release.yml` draft
on branch create, `docker-build-push.yml` on `release/*`, `publish.yml` on
`release/latest`, mkdocs `docs.yml` on main+release pushes). The starter kit
replaces all of it with tag-push. Migration per repo = delete 2-4 legacy
workflows, copy 3-4 kit files, run `apply-rulesets.sh`, delete stale `release/*`
branches.

## Tier 1 — full kit fits (migrate)

| Repo | Today | Kit overlay | Notes |
|---|---|---|---|
| **pydmp** (PyPI library) | pythonpackage, create-release, publish (release/latest), validate-branch-flow, codeql, mkdocs docs | `python-library/` (ci+release+dependabot) | **Pilot candidate** — exercises the PyPI path the kit just fixed. Update the PyPI publisher registration to workflow `aviato-ci.yml` + environment `pypi` (kit standard per README §Trusted Publishing + wf-python-library.yml; today: `publish.yml` + `publish`). CodeQL → default setup. Docs already Zensical (migrated independently; G1 superseded). Kill branch flow + stale release/* branches. |
| **todoist-mcp** | quartet (pythonpackage, create-release, docker-build-push, docs) | `python-app/ci.yml` + `container-service/release.yml` + dependabot | mkdocs docs (G1). Most recently active repo. |
| **homeassistant-mcp** | quartet | same as todoist-mcp | compose for local dev unaffected |
| **calendar-mcp** | quartet | same | no pyproject at root — adjust ci install command |
| **ics-combiner** | quartet | same | |
| **adhdbytes-com-next** | docker-build-push (release/* branches, multi-arch) | `node-service/` (ci+npmrc+dependabot) + `container-service/release.yml` | arm64: gap G2 |
| **anthonymattas-com-next** | same | same | |
| **law18-app-next** | same | same | |
| **mattas-net-next** | same | same | |
| **mattas-net-strapi** | same | same | |
| **hass-dmp** (HA integration) | pythonpackage + hassfest | `python-app/` ci+release+dependabot; **keep hassfest.yaml** | tag-push releases suit HACS (GitHub releases) |
| **hass-colorlogic** | nothing | `python-app/ci.yml` (lint/test only) + dependabot | no pyproject — trim ci to fit |
| **neewer-sacn** (local: `neewer`) | ci, codeql | swap ci → kit `python-app/ci.yml`; codeql → default setup; add release.yml | |

## Tier 2 — partial / when-ready

| Repo | State | Overlay |
|---|---|---|
| **retail-demo** | custom (claude review, mkdocs-pages, tests, type-check) | optional: tests+type-check → kit ci.yml; keep claude + mkdocs workflows |
| **pbi-ontology-skill** | remote-only, no workflows | `python-app/ci.yml` + dependabot |
| **reinsurance-demo** | remote-only, no workflows | same, low priority |
| **law18** (Swift, not cloned locally) | no workflows | `swift-app/` ci + dependabot |
| **music-mcp** | empty shell | kit when it grows code |
| **security-mcp**, **OKRocket**, **dog-button** | local-only, no remote | kit at first push (security-mcp → python-app; OKRocket → swift-app/xcodebuild) |
| **mattas-net-infra** (terraform+helm) | no workflows | gap G3 — no infra profile; optional tiny ci (fmt/validate/helm lint) |
| **aviato** itself | 16 workflows + engine | post-demolition: becomes master copy + kit-style ci/release/docs for the starter kit itself |

## Out of scope

Forks (GetEmbedToken, obfuscation_analysis, reverser_ai, canvas-todoist) ·
archived (ask-tim, agentic-coding, anthonymattas-com, speedtrap, sonos-reboot) ·
coursework/CTF/CVP (omscs, flag, tkctf_2025, webc2-greencat-2, policies) ·
not-git (aviato-scratch, trackpad, law18 local dir, Obsidian Vault).

## Kit gaps — RESOLVED 2026-06-11

- **G1 — docs: SUPERSEDED 2026-07-11 → Zensical everywhere.** The original
  Docusaurus decision was replaced by the settled starter-kit decision
  (docs/requirements/modules/starter-kit/backlog.md): Zensical with built-in
  search is the sole docs baseline. pydmp already migrated independently
  (117e2ba). Remaining mkdocs repos (todoist-mcp, homeassistant-mcp,
  calendar-mcp, ics-combiner) convert to Zensical as part of migration.
- **G2 — multi-arch container builds: REQUIRED (GKE ARM nodes).** Kit
  `container-service/release.yml` updated: amd64+arm64 matrix on native runners
  (the proven legacy pattern), per-arch scan-then-push, manifest assembly,
  release last.
- **G3 — infra profile: dropped** (operator decision — don't care).
- **Migration chore per repo:** delete stale `release/*` / `release/latest`
  branches once tag-push lands (same cleanup approved for aviato).

## Suggested order

1. **pydmp** (pilot: hardest path — PyPI + docs + branch-flow teardown)
2. todoist-mcp → homeassistant-mcp → calendar-mcp → ics-combiner (identical quartet, assembly-line)
3. The five node sites (identical, after G2 decision)
4. hass-dmp, hass-colorlogic, neewer-sacn
5. Tier 2 stragglers opportunistically
