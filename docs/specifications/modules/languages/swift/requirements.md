<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

### 12.3 Swift

**Scaffold bundle (managed files):** format config, lint config, language ignore
rules, editor config. (No package/project-manifest fragment is seeded — finding 48:
the Xcode project IS the manifest and it is seed-once operator-owned per the next
sentence, so a fragment would have nothing meaningful to manage.) The Xcode project
and app entrypoints are seed-once operator-owned (§6.3).

**Required tooling/standards (named, all gates blocking):** **swift-format**
(Apple) for formatting; **SwiftLint `--strict`** for linting (blocking);
Swift/Xcode toolchain build + test (macOS); Conventional Commits enforced. (DocC
exists for Swift API reference but produces an *archive*, not md/mdx — see Docs.)

**Version-source module:** the marketing version **and** a monotonic build number
(see deploy, §13.4) — the release process derives marketing version from SemVer
and ensures the build number is strictly increasing. The day-zero `swift-app`
version-source `locations` are a **placeholder** (`project.pbxproj`/`Info.plist` at
the root); a real Xcode project keeps these in `<Scheme>.xcodeproj/project.pbxproj`,
whose path varies, so the operator **overrides `version_source.locations`** in the
declaration to point at their actual file(s). `bump-version` names the expected
locations and exits non-zero if none exist (it never silently no-ops), so a wrong
default fails loud — consistent with the §13.4.7 operator-verified Swift DoD.

**Workflows bundle (pipelines):**
- **Verify** (**macOS**): swift-format `--lint` + SwiftLint `--strict` + build +
  test (format/lint blocking), plus the common lint (§12 intro).
- **Docs** (only when `docs: true`, §6.1): emit **narrative md/mdx** into the docs
  source tree for the Zensical site (§13.3). DocC API-reference emission to
  md/mdx is **deferred** (DocC produces an archive Zensical cannot consume); a
  linked DocC archive is a possible later addition. No docs step when `docs: false`.
- **Release** (§5.9): SemVer; marketing version + monotonic build number.
- **Deploy**: **App Store Connect** (§13.4).
- **Security (baseline, §2.13/§5.14):** CodeQL (Swift) SAST (no mature dedicated
  Swift security-linter exists beyond CodeQL); dependency scanning + dependency
  review (SwiftPM / OSV where available); secret scanning + push protection; SARIF
  to the Security tab; high/critical gates verify.

**Required variables:** product/scheme identifiers, bundle identifier, shared
metadata variables. (App-Store signing inputs are declared by the deploy plug-in,
§13.4.)

**Runner:** **macOS.** **Definition of done:** verify + release green in real CI on
macOS (plus the docs build when `docs: true`); App Store Connect deploy meets its
operator-verified DoD (§13.4.7).

---
