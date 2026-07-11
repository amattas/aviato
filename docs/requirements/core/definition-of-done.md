<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

## 9. Definition of Done (process-level, agnostic)

A capability is "done" only when **all** hold:

1. It is expressed entirely as modules (§3.2) composed by a profile — the core
   engine was not edited to accommodate it.
2. Resolution, scaffolding, diagnosis, and (where applicable) reconciliation pass
   on a **real, non-mocked** end-to-end exercise (§8.10).
3. Its automation **actually starts and runs** on the real hosting platform (a
   real pipeline run reaching a real result), not merely validated for syntax or
   string content.
4. Every privilege it needs is **declared** by the unit that needs it and
   **granted** by the unit that calls it (§8.9).
5. It honors every applicable core principle in §2 — verified, not assumed.
6. The bootstrap/self-reference path (§5.10) is satisfied where the capability
   touches the Library itself.
7. Any credential it requires is part of its declared module interface and is
   surfaced explicitly; it never weakens the no-secrets posture of
   read/propose/report automation (§2.3, §6.6).
8. **Baseline security scanning runs and gates** (§2.13, §5.14): the four scan
   categories execute on the real platform, upload SARIF, and the high/critical
   gate is demonstrated to fail verify / gate deploy — not asserted.
9. **Author-unverifiable exception:** where a capability cannot be verified by the
   system author (day zero: Apple App Store Connect, §13.4), its done-state is an
   **operator-performed** real run on the operator's own account (§13.4.7) — this
   substitutes for criteria 2–3 for that capability only.

### 9b. Core-level Definition of Done (falsifiable agnosticism)

<a id="9b"></a>
_(Referenced throughout as "§9b" — the core-level, falsifiable agnosticism DoD.)_

**Core-level Definition of Done (falsifiable agnosticism):** beyond per-capability
DoD, the **core itself** is done only when: (a) the core loads and all core tests
pass with **zero plug-ins present**; (b) a static check confirms the core has **no
import/dependency edge into the plug-in module tree** *and* its source contains
**none of the enumerated day-zero target/tool identifiers** — the denylist
(`python`, `node`, `swift`, `pypi`, `ghcr`, `pages`, `docusaurus`, `apple`/`app
store`, `ruff`, `eslint`, `swiftlint`, `codeql`, …), maintained alongside the
day-zero catalog (§10), is **part of the check**, so (b) is falsifiable rather than
depending on an unstated word list; and (c) the same unmodified core drives **at
least two unrelated plug-ins** in the end-to-end exercise. Clauses (a) and (c)
falsify outward coupling **behaviorally** even if the denylist is incomplete; the
import-edge half of (b) needs no list at all.

**Precedence:** §9 applies **in full** to every plug-in; §16 *adds*
plug-in-specific criteria and relaxes nothing in §9.

---
