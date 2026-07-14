<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

## 4. The Modularity Model

### 4.1 Composition: a profile is an assembly of modules

A profile composes exactly one workflows-bundle, one scaffold-bundle, and one
settings-bundle. There is **one profile per Consumer** (§3 scope) and **one
baseline strictness level** (no tiers).

```mermaid
flowchart TD
    P["PROFILE (thin manifest, one per repo)"]
    P --> WB["Workflows bundle"]
    P --> SB["Scaffold bundle"]
    P --> GB["Settings bundle"]

    WB --> PL1["Pipeline module A"]
    WB --> PL2["Pipeline module B"]
    SB --> T1["Template module A"]
    SB --> T2["Template module B"]
    GB --> SET["Declarative settings"]

    PL1 --> E1["Workflow envelope"]
    PL1 --> J1["Job fragment(s)"]
    PL2 --> E2["Workflow envelope"]
    PL2 --> J2["Job fragment(s)"]
    PL1 --> PT1["Owned template refs"]

    subgraph Plugin["A language or deployment plug-in is ONLY this:"]
        WBx["+ Workflows bundle entries"]
        SBx["+ Scaffold/template entries"]
        GBx["+ Settings entries / pipeline"]
        VSx["+ Version-source module (language)"]
    end
    Plugin -. "adds modules; never edits core" .-> P
```

### 4.2 Inheritance and override semantics (explicit, never silent)

Bundles and profiles may inherit from a base of the same kind. The semantics are
strict because the common failure is a child **silently losing** something it
should have kept.

- A module may `extend` another module of the same kind.
- **List-valued** properties (the set of pipelines, templates, required checks)
  are modified with **explicit `add` / `remove` operations only**. A child never
  restates a bare list (which would silently replace).
- **Map-valued** properties are merged by **deep merge** at the leaf — a child
  overriding one nested key must not drop sibling keys.
- Trigger list leaves use the same explicit `add` / `remove` semantics. A bare
  list, an orphan removal, or incompatible scalar contribution is a hard error.
- The resolved template set is the stable union of scaffold-bundle templates
  and template identities owned by selected pipelines. Removing the last
  pipeline owner removes that artifact.
- In workflow schema v2, job descriptors are the graph authority for runners,
  checks, environments, permissions, inputs, and secrets. A pipeline may retain
  legacy aggregate fields for compatibility, but they are optional and, when
  present, must exactly describe a representable job union. Multi-job pipelines
  may legitimately use distinct runners, checks, and environments.
- **Edge-case rules (normative):**
  - `remove` of an element **not present** in the resolved base → **hard error**
    (it signals a stale assumption; fail loud).
  - `add` of an element **already present** → **hard error** (signals a redundant
    or conflicting intent).
  - `add` and `remove` of the **same element in the same layer** → **hard error**.
  - **Ordering is deterministic:** ancestors resolve before descendants;
    list membership uses **set semantics** (no duplicates).
  - **Same-output-path collisions** in the scaffold set are resolved by overlay
    order (§5.3): the later/overriding source wins; ties at the same level are an
    error, not a silent pick.
    **Day-zero behavior (conservative):** the implementation treats **every**
    same-output-path collision in the applicable set as a **hard error**
    (`onboarding.check_output_collisions`), not just same-level ties. Cross-level
    overlay *resolution* (a descendant template deliberately overriding an ancestor's
    output) is **deferred**: silently letting a later source win is exactly the §8.1
    "child silently loses an inherited entry" failure mode, so day-zero fails loud
    rather than resolve. Day-zero profiles compose **no** two applicable templates at
    one path (variant-exclusive templates are filtered by `when` before this check),
    so the resolution branch is never legitimately exercised; implementing an explicit,
    reviewable cross-level override is a post-day-zero refinement.

```mermaid
flowchart TD
    Base["Base module<br/>(list: [a, b]; map: {x:1, y:2})"]
    Child["Child: extends Base<br/>add: [c]; remove: [a]<br/>map override: {y:3}"]
    Result["Resolved<br/>list: [b, c]<br/>map: {x:1, y:3}"]
    Base --> Child --> Result
    note["Lists: explicit add/remove, set semantics.<br/>remove-absent / add-duplicate = hard error.<br/>Maps: deep-merge at leaf. No silent replacement."]
    Child -.-> note
```

### 4.3 Adding a capability = adding a module

To support a new language, documentation generator, release mechanism, or
deployment target, the **only** permitted change is to **add modules** that
conform to §3.2 and to reference them from a profile. The core engine is not
touched. If a new capability seems to require editing the core, that is a signal
the core abstraction is wrong and must be revisited — not a license to
special-case.

---

## 5. Process Flows

Each subsection states trigger, actor, preconditions, steps, outputs, and failure
handling, followed by a diagram. All flows are language- and
deployment-agnostic; where a flow would call a language- or deployment-specific
unit, it calls it **through a module reference**, never by name.

### 5.1 Profile resolution & composition (pure)

**Trigger:** any process needing a concrete convention set.
**Actor:** core engine.
**Steps:** load the named profile → resolve each referenced bundle, applying
`extends` + `add`/`remove` for lists (with §4.2 edge-case rules) and deep-merge
for maps → apply Consumer overrides under the same rules → produce a
fully-resolved convention set (pipelines, pipeline-conditioned templates,
settings, required variables, version-source, workflow schema). For schema v2,
the compiler then validates the pipeline/job dependency graph and produces one
deterministic desired state: callers, artifacts, settings, environments,
privileges, and required checks all come from that same selected graph.
**Purity:** *profile/bundle composition is pure and deterministic* (no side
effects). **Variable resolution (§5.2) is a separate, impure step** — it reads
host state — and its results are captured into the declaration so downstream
composition stays reproducible.
**Failure handling:** a bare list under `extends`/override is rejected; a missing
referenced module is a hard error; §4.2 edge-case violations are hard errors.

```mermaid
flowchart TD
    A["Need convention set for profile P"] --> B["Load profile manifest"]
    B --> C["Resolve workflows bundle<br/>(extends + add/remove, edge rules)"]
    B --> D["Resolve scaffold bundle<br/>(extends + add/remove, edge rules)"]
    B --> E["Resolve settings bundle<br/>(extends + deep-merge)"]
    C --> F["Apply consumer overrides<br/>(same strict semantics)"]
    D --> F
    E --> F
    F --> G{"Bare list under extends/override,<br/>or add/remove edge violation?"}
    G -- yes --> H["REJECT (hard error)"]
    G -- no --> I{"All referenced<br/>modules exist?"}
    I -- no --> J["HARD ERROR: missing module"]
    I -- yes --> K["Resolved convention set<br/>(pure; pipelines · templates · settings · vars · version-source)"]
    K --> L{"workflow schema v2?"}
    L -- no --> M["Legacy read-only; mutation requires repin"]
    L -- yes --> N["Compile + validate one DesiredState<br/>callers · artifacts · settings · envs · checks"]
```
